"""Portable local tests: retention integrity, boundaries, links, and Git replay."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "retention.py"
SPEC = importlib.util.spec_from_file_location("p0defensive_retention_under_test", MODULE_PATH)
retention = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retention)
RawStore, RetentionError = retention.RawStore, retention.RetentionError


class RetentionTestBase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        # Canonicalize the test fixture only: macOS /var and /tmp can be links.
        self.root = Path(self.temporary.name).resolve()
        self.store = RawStore(self.root / "evidence")
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def file(self, name="file", content=b"payload", mode=0o644):
        path = self.inputs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)
        return path

    def blob(self, record):
        return (self.store.root / record["blob_path"]).read_bytes()

class RetentionTests(RetentionTestBase):
    def test_regular_file_roundtrip_and_json_index(self):
        content = b"\x00\xff\nactual bytes\x00"
        record = self.store.retain_file(self.file(content=content), root=self.inputs, label="lock")
        self.assertEqual(self.blob(record), content)
        self.assertEqual(record["length"], len(content))
        self.assertEqual(record["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(record["label"], "lock")
        self.assertEqual(record["mode"], "0644")
        self.assertEqual(json.loads(json.dumps(record)), record)
        self.assertEqual(self.store.summary()["limits"], retention.BOUNDS)

    def test_dedup_still_consumes_logical_budgets(self):
        first = self.store.retain_bytes(b"same", label="a")
        second = self.store.retain_bytes(b"same", label="b")
        self.assertEqual(first["blob_path"], second["blob_path"])
        self.assertEqual(self.store.summary()["unique_blobs"], 1)
        self.assertEqual(self.store.file_count, 2)
        self.assertEqual(self.store.total_bytes, 8)

    def test_reopening_nonempty_namespace_cannot_reset_budgets(self):
        self.store.retain_bytes(b"one", label="one")
        with self.assertRaisesRegex(RetentionError, "refusing to reset"):
            RawStore(self.store.root)

    def test_empty_input_retained(self):
        record = self.store.retain_file(self.file(content=b""))
        self.assertEqual(self.blob(record), b"")
        self.assertEqual(record["length"], 0)

    def test_missing_and_nonordinary_inputs_rejected(self):
        for path in [self.inputs / "missing", self.inputs]:
            with self.subTest(path=path), self.assertRaises(RetentionError):
                self.store.retain_file(path)
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.inputs / "fifo")
            with self.assertRaises(RetentionError):
                self.store.retain_file(self.inputs / "fifo")

    def test_regular_file_rejects_leaf_and_parent_symlink(self):
        target = self.file()
        (self.inputs / "link").symlink_to(target)
        (self.root / "alias").symlink_to(self.inputs, target_is_directory=True)
        for path in [self.inputs / "link", self.root / "alias" / "file"]:
            with self.subTest(path=path), self.assertRaises(RetentionError):
                self.store.retain_file(path)

    def test_root_escape_and_parent_traversal_rejected(self):
        outside = self.root / "outside"
        outside.write_bytes(b"x")
        with self.assertRaises(RetentionError):
            self.store.retain_file(outside, root=self.inputs)
        with self.assertRaises(RetentionError):
            self.store.retain_file(self.inputs / ".." / "outside")

    def test_evidence_symlink_rejected(self):
        (self.root / "alias").symlink_to(self.store.root, target_is_directory=True)
        with self.assertRaises(RetentionError):
            RawStore(self.root / "alias")

    def test_blob_collision_or_corruption_rejected(self):
        first = self.store.retain_bytes(b"same", label="a")
        (self.store.root / first["blob_path"]).write_bytes(b"evil")
        with self.assertRaisesRegex(RetentionError, "corrupt"):
            self.store.retain_bytes(b"same", label="b")

    def test_existing_blob_symlink_rejected(self):
        first = self.store.retain_bytes(b"same", label="a")
        blobpath = self.store.root / first["blob_path"]
        blobpath.unlink()
        blobpath.symlink_to(self.file(content=b"same"))
        with self.assertRaises(RetentionError):
            self.store.retain_bytes(b"same", label="b")

    def test_all_byte_and_count_bounds_fail_closed(self):
        with mock.patch.object(retention, "MAX_FILE_BYTES", 3):
            with self.assertRaisesRegex(RetentionError, "file exceeds"):
                self.store.retain_bytes(b"1234", label="large")
        with mock.patch.object(retention, "MAX_TOTAL_BYTES", 3):
            with self.assertRaisesRegex(RetentionError, "aggregate"):
                self.store.retain_bytes(b"1234", label="aggregate")
        with mock.patch.object(retention, "MAX_FILES", 1):
            self.store.retain_bytes(b"a", label="one")
            with self.assertRaisesRegex(RetentionError, "file count"):
                self.store.retain_bytes(b"a", label="two")

    def test_file_is_streamed_in_bounded_chunks(self):
        path = self.file(content=b"x" * 4097)
        real_read = os.read
        requests = []
        def reading(fd, size):
            requests.append(size)
            return real_read(fd, size)
        with mock.patch.object(retention, "CHUNK_BYTES", 127), mock.patch.object(retention.os, "read", side_effect=reading):
            record = self.store.retain_file(path)
        self.assertEqual(len(self.blob(record)), 4097)
        self.assertGreater(len(requests), 20)
        self.assertLessEqual(max(requests), 127)

    def test_same_size_mutation_during_read_rejected(self):
        path = self.file(content=b"original")
        inode = path.stat().st_ino
        real_read = os.read
        changed = False
        def reading(fd, size):
            nonlocal changed
            value = real_read(fd, size)
            if not changed and os.fstat(fd).st_ino == inode:
                changed = True
                path.write_bytes(b"modified")
            return value
        with mock.patch.object(retention.os, "read", side_effect=reading):
            with self.assertRaisesRegex(RetentionError, "mutated"):
                self.store.retain_file(path)
        self.assertEqual(list(self.store.root.glob(".raw-*")), [])

    def test_file_replacement_during_read_rejected(self):
        path = self.file(content=b"original")
        inode = path.stat().st_ino
        real_read = os.read
        changed = False
        def reading(fd, size):
            nonlocal changed
            value = real_read(fd, size)
            if not changed and os.fstat(fd).st_ino == inode:
                changed = True
                path.unlink()
                path.write_bytes(b"original")
            return value
        with mock.patch.object(retention.os, "read", side_effect=reading):
            with self.assertRaisesRegex(RetentionError, "mutated"):
                self.store.retain_file(path)

    def test_tree_keeps_files_empty_directories_and_framework_links(self):
        self.file("Thing.framework/Versions/A/Thing", b"binary", 0o755)
        self.file("Thing.framework/Versions/A/Resources/info", b"plist")
        framework = self.inputs / "Thing.framework"
        (framework / "Versions" / "Current").symlink_to("A", target_is_directory=True)
        (framework / "Thing").symlink_to("Versions/Current/Thing")
        (framework / "Resources").symlink_to("Versions/Current/Resources", target_is_directory=True)
        (self.inputs / "empty").mkdir()
        tree = self.store.retain_tree(self.inputs)
        index = {record["path"]: record for record in tree["entries"]}
        self.assertEqual(index["empty"]["kind"], "directory")
        link = index["Thing.framework/Thing"]
        self.assertEqual(self.blob(link), b"Versions/Current/Thing")
        self.assertEqual(link["resolved_target"], "Thing.framework/Versions/A/Thing")
        self.assertEqual(self.blob(index[link["resolved_target"]]), b"binary")

    def test_tree_rejects_escape_dangling_and_cycle(self):
        for target in ["../../outside", "missing", "link", "/etc/passwd"]:
            link = self.inputs / "link"
            link.symlink_to(target)
            try:
                with self.subTest(target=target), self.assertRaises(RetentionError):
                    self.store.retain_tree(self.inputs)
            finally:
                link.unlink()

    def test_tree_rejects_cross_link_escape(self):
        (self.inputs / "first").symlink_to("second/outside")
        (self.inputs / "second").symlink_to("..", target_is_directory=True)
        with self.assertRaises(RetentionError):
            self.store.retain_tree(self.inputs)

    def test_tree_rejects_evidence_nested_in_source(self):
        with self.assertRaisesRegex(RetentionError, "evidence store"):
            self.store.retain_tree(self.root)

    def test_directory_and_depth_caps(self):
        (self.inputs / "a" / "b").mkdir(parents=True)
        with mock.patch.object(retention, "MAX_DIRECTORIES", 1):
            with self.assertRaisesRegex(RetentionError, "directory count"):
                self.store.retain_tree(self.inputs)
        with mock.patch.object(retention, "MAX_DEPTH", 2):
            with self.assertRaisesRegex(RetentionError, "depth"):
                self.store.retain_tree(self.inputs)

    def test_tree_directory_mutation_rejected(self):
        self.file()
        original = self.store._file
        def capture(*args, **kwargs):
            result = original(*args, **kwargs)
            self.file("new")
            return result
        with mock.patch.object(self.store, "_file", side_effect=capture):
            with self.assertRaisesRegex(RetentionError, "directory mutated"):
                self.store.retain_tree(self.inputs)

    def test_executable_retains_resolution_chain_and_bytes(self):
        final = self.file("real", b"tool bytes", 0o755)
        (self.inputs / "second").symlink_to("real")
        first = self.inputs / "first"
        first.symlink_to("second")
        result = self.store.retain_executable(first, approved_roots=[self.inputs])
        self.assertEqual(result["resolved_path"], str(final))
        self.assertEqual(self.blob(result), b"tool bytes")
        self.assertEqual([self.blob(r) for r in result["symlink_chain"]], [b"second", b"real"])

    def test_executable_unapproved_escape_nonexecutable_and_cycle_rejected(self):
        real = self.file("real", mode=0o755)
        link = self.inputs / "link"
        link.symlink_to("real")
        with self.assertRaisesRegex(RetentionError, "requires approved"):
            self.store.retain_executable(link)
        with self.assertRaisesRegex(RetentionError, "escaped approved"):
            self.store.retain_executable(link, approved_roots=[self.store.root])
        real.chmod(0o644)
        with self.assertRaisesRegex(RetentionError, "not executable"):
            self.store.retain_executable(real)
        link.unlink()
        link.symlink_to("link")
        with mock.patch.object(retention, "MAX_SYMLINK_HOPS", 3):
            with self.assertRaisesRegex(RetentionError, "chain exceeds"):
                self.store.retain_executable(link, approved_roots=[self.inputs])

    def test_executable_resolves_symlinked_directory_and_relative_parent(self):
        self.file("versions/a/tool", mode=0o755)
        (self.inputs / "current").symlink_to("versions/a", target_is_directory=True)
        (self.inputs / "launch").symlink_to("current/../a/tool")
        result = self.store.retain_executable(self.inputs / "launch", approved_roots=[self.inputs])
        self.assertEqual(result["resolved_path"], str(self.inputs / "versions/a/tool"))


@unittest.skipUnless(shutil.which("git"), "Git is required for source-object tests")
class GitRetentionTests(RetentionTestBase):
    def git(self, root, *arguments, input=None):
        return subprocess.check_output(["git", "-C", str(root), *arguments], input=input, stderr=subprocess.PIPE)

    def repository(self, root=None):
        root = root or self.inputs
        root.mkdir(parents=True, exist_ok=True)
        self.git(root, "init", "-q")
        self.git(root, "config", "user.name", "Retention Test")
        self.git(root, "config", "user.email", "retention@example.invalid")
        return root

    def commit(self, root):
        self.git(root, "add", "-A")
        self.git(root, "commit", "-qm", "fixture")
        return self.git(root, "rev-parse", "HEAD").decode().strip()

    def test_git_committed_bytes_modes_symlinks_and_lock_override(self):
        root = self.repository()
        self.file("Package.resolved", b"committed lock")
        self.file("run", b"executable", 0o755)
        (root / "tracked-link").symlink_to("../../external-is-not-followed")
        commit = self.commit(root)
        (root / "Package.resolved").write_bytes(b"observed lock")
        result = self.store.retain_git_tree(root, commit)
        index = {record["path"]: record for record in result["entries"]}
        self.assertEqual(self.blob(index["Package.resolved"]), b"committed lock")
        self.assertEqual(index["run"]["git_mode"], "100755")
        self.assertEqual(index["tracked-link"]["git_mode"], "120000")
        self.assertEqual(self.blob(index["tracked-link"]), b"../../external-is-not-followed")
        observed = self.store.retain_file(root / "Package.resolved")
        self.assertEqual(self.blob(observed), b"observed lock")
        for record in result["entries"]:
            content = self.blob(record)
            self.assertEqual(record["git_blob_oid"], self.git(root, "hash-object", "--stdin", input=content).decode().strip())
        shutil.rmtree(root)
        self.assertEqual(self.blob(index["run"]), b"executable")

    def test_git_batch_streams_large_blobs(self):
        root = self.repository()
        self.file(content=b"x" * 30001)
        self.commit(root)
        with mock.patch.object(retention, "CHUNK_BYTES", 101):
            result = self.store.retain_git_tree(root)
        self.assertEqual(len(self.blob(result["entries"][0])), 30001)

    def test_git_unapproved_gitlink_rejected(self):
        root = self.repository()
        self.file()
        commit = self.commit(root)
        self.git(root, "update-index", "--add", "--cacheinfo", "160000," + commit + ",module")
        self.git(root, "commit", "-qm", "gitlink")
        with self.assertRaisesRegex(RetentionError, "unapproved"):
            self.store.retain_git_tree(root)

    def test_git_approved_gitlink_retains_nested_source(self):
        root = self.repository()
        self.file()
        self.commit(root)
        child = self.repository(root / "module")
        (child / "child").write_bytes(b"nested source")
        child_commit = self.commit(child)
        self.git(root, "update-index", "--add", "--cacheinfo", "160000," + child_commit + ",module")
        self.git(root, "commit", "-qm", "gitlink")
        result = self.store.retain_git_tree(root, approved_gitlinks={"module": child_commit})
        module = next(record for record in result["entries"] if record["path"] == "module")
        self.assertEqual(self.blob(module["checkout"]["entries"][0]), b"nested source")

    def test_git_missing_object_rejected(self):
        root = self.repository()
        self.file()
        self.commit(root)
        oid = self.git(root, "rev-parse", "HEAD:file").decode().strip()
        (root / ".git" / "objects" / oid[:2] / oid[2:]).unlink()
        with self.assertRaisesRegex(RetentionError, "missing or malformed"):
            self.store.retain_git_tree(root)

    def test_git_empty_directories_and_independent_tree_replay(self):
        root = self.repository()
        self.file(content=b"source")
        initial = self.commit(root)
        blob = self.git(root, "rev-parse", "HEAD:file").decode().strip()
        empty_tree = self.git(root, "mktree", input=b"").decode().strip()
        tree = self.git(root, "mktree", input=(
            "100644 blob " + blob + "\tfile\n040000 tree " + empty_tree + "\tempty\n"
        ).encode()).decode().strip()
        commit = self.git(root, "commit-tree", tree, "-p", initial, "-m", "empty directory").decode().strip()
        self.git(root, "update-ref", "HEAD", commit)
        capture = self.store.retain_git_tree(root)
        self.assertEqual(capture["directories"], [{"path": "empty", "git_mode": "040000", "git_tree_oid": empty_tree}])
        shutil.rmtree(root)
        replay = self.repository(self.root / "replay")
        children = {"": []}
        for directory in capture["directories"]:
            children[directory["path"]] = []
        for record in capture["entries"]:
            oid = self.git(replay, "hash-object", "-w", "--stdin", input=self.blob(record)).decode().strip()
            parent, _, name = record["path"].rpartition("/")
            children[parent].append(record["git_mode"] + " blob " + oid + "\t" + name + "\n")
        for directory in sorted(capture["directories"], key=lambda item: item["path"].count("/"), reverse=True):
            oid = self.git(replay, "mktree", input="".join(children[directory["path"]]).encode()).decode().strip()
            parent, _, name = directory["path"].rpartition("/")
            children[parent].append("040000 tree " + oid + "\t" + name + "\n")
        replay_tree = self.git(replay, "mktree", input="".join(children[""]).encode()).decode().strip()
        self.assertEqual(replay_tree, capture["tree"])

    def test_git_rejects_subdirectory_as_checkout_root(self):
        root = self.repository()
        self.file("sub/file")
        self.commit(root)
        with self.assertRaisesRegex(RetentionError, "actual Git checkout root"):
            self.store.retain_git_tree(root / "sub")

    def test_git_blob_bound_applies_before_streaming(self):
        root = self.repository()
        self.file(content=b"12345")
        self.commit(root)
        with mock.patch.object(retention, "MAX_FILE_BYTES", 4):
            with self.assertRaisesRegex(RetentionError, "Git blob exceeds"):
                self.store.retain_git_tree(root)

    def test_git_listing_bounds_and_unused_approval(self):
        root = self.repository()
        self.file()
        commit = self.commit(root)
        with mock.patch.object(retention, "MAX_GIT_OUTPUT_BYTES", 5):
            with self.assertRaisesRegex(RetentionError, "listing exceeds"):
                self.store.retain_git_tree(root)
        with self.assertRaisesRegex(RetentionError, "unused"):
            self.store.retain_git_tree(root, approved_gitlinks={"missing": commit})


if __name__ == "__main__":
    unittest.main()
