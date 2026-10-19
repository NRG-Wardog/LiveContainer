"""Bounded, fail-closed retention of the actual bytes used by a local capture.

This module makes no build-success claim. Callers must retain its returned index
in their evidence manifest. Blobs live below ``blobs/sha256/XX/SHA256`` and can be
replayed without the original checkout, tool installation, or artifact directory.

Reviewed ceilings are deliberately fixed: 512 MiB per file accommodates large
native tools/libraries, 8 GiB logical bytes accommodates a narrow Phase A capture,
and 100,000 files / 20,000 directories prevent tiny-file amplification. Duplicate
content still consumes logical budgets. Increasing any ceiling requires review.
Ordinary paths never follow symlinks. Artifact trees preserve only internal,
resolvable symlinks as literal bytes. Git symlinks retain the link's literal bytes; explicitly approved executable resolution is the sole
filesystem-symlink traversal exception. Gitlink approvals name exact commits.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import uuid

MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
MAX_FILES = 100_000
MAX_DIRECTORIES = 20_000
MAX_PATH_BYTES = 4096
MAX_DEPTH = 128
MAX_SYMLINK_HOPS = 32
MAX_GIT_OUTPUT_BYTES = 32 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
BOUNDS = {"file_bytes": MAX_FILE_BYTES, "total_bytes": MAX_TOTAL_BYTES,
          "files": MAX_FILES, "directories": MAX_DIRECTORIES,
          "path_bytes": MAX_PATH_BYTES, "depth": MAX_DEPTH,
          "symlink_hops": MAX_SYMLINK_HOPS, "git_output_bytes": MAX_GIT_OUTPUT_BYTES}


class RetentionError(ValueError):
    """Capture is incomplete, unsafe, mutated, or outside reviewed bounds."""


def _require(condition, message):
    if not condition:
        raise RetentionError(message)


def _absolute(path):
    path = Path(path)
    _require(".." not in path.parts, "parent traversal is not an approved input path")
    path = Path(os.path.abspath(path))
    _require(len(os.fsencode(path)) <= MAX_PATH_BYTES, "input path exceeds reviewed bound")
    _require(len(path.parts) <= MAX_DEPTH, "input path depth exceeds reviewed bound")
    return path


def _identity(s):
    return s.st_dev, s.st_ino, s.st_mode


def _snapshot(s):
    return (_identity(s), s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _dir_flags():
    _require(hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"),
             "platform lacks required no-follow directory support")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@contextmanager
def _directory(path, *, create=False):
    """Anchor every component with no-follow descriptors; reject substitution."""
    path = _absolute(path)
    fds, links = [], []
    try:
        fd = os.open(path.anchor, _dir_flags())
        fds.append(fd)
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            before = os.stat(part, dir_fd=fd, follow_symlinks=False)
            _require(stat.S_ISDIR(before.st_mode), "symlink or non-directory path component: " + str(path))
            child = os.open(part, _dir_flags(), dir_fd=fd)
            fds.append(child)
            _require(_identity(before) == _identity(os.fstat(child)), "directory substituted while opening")
            links.append((fd, part, before))
            fd = child
        yield fd
        for parent, part, before in links:
            _require(_identity(os.stat(part, dir_fd=parent, follow_symlinks=False)) == _identity(before),
                     "directory substituted during retention")
    except OSError as exc:
        raise RetentionError("unsafe or missing directory: " + str(path) + ": " + str(exc)) from exc
    finally:
        for fd in reversed(fds):
            os.close(fd)


def _validate_name(name):
    _require(isinstance(name, str) and name and not name.startswith("/"), "invalid relative tree path")
    _require(all(p not in ("", ".", "..") for p in name.split("/")), "unsafe relative tree path")
    _require(len(os.fsencode(name)) <= MAX_PATH_BYTES and len(name.split("/")) <= MAX_DEPTH,
             "tree path exceeds reviewed bound")


def _inside(path, roots):
    return any(path == root or root in path.parents for root in roots)


class RawStore:
    """Stream immutable raw blobs into a fresh evidence root with fixed bounds.

    Returned records are JSON-serializable. ``blob_path`` is evidence-root-relative,
    ``sha256`` hashes the exact bytes, and ``length`` is their byte count. Source
    paths are descriptive only and are never needed to resolve retained blobs.
    The evidence root must not be nested within a captured artifact tree.
    """

    def __init__(self, evidence_root):
        self.root = _absolute(evidence_root)
        self.file_count = 0
        self.total_bytes = 0
        self.directory_count = 0
        self.unique_blobs = set()
        with _directory(self.root / "blobs" / "sha256", create=True) as namespace:
            with os.scandir(namespace) as existing:
                _require(next(existing, None) is None,
                         "raw blob namespace must be fresh; refusing to reset capture budgets")

    def _claim(self, length):
        _require(isinstance(length, int) and 0 <= length <= MAX_FILE_BYTES,
                 "file exceeds reviewed byte bound")
        _require(self.file_count < MAX_FILES, "file count exceeds reviewed bound")
        _require(self.total_bytes + length <= MAX_TOTAL_BYTES, "aggregate bytes exceed reviewed bound")
        # Failed attempts consume budget too; a failed capture is not publishable.
        self.file_count += 1
        self.total_bytes += length

    def _claim_directory(self):
        _require(self.directory_count < MAX_DIRECTORIES, "directory count exceeds reviewed bound")
        self.directory_count += 1

    def _store(self, chunks, length, *, label, metadata=None):
        self._claim(length)
        digest = hashlib.sha256()
        git_sha1 = hashlib.sha1(b"blob " + str(length).encode("ascii") + b"\0")
        git_sha256 = hashlib.sha256(b"blob " + str(length).encode("ascii") + b"\0")
        temp = ".raw-" + uuid.uuid4().hex
        count = 0
        with _directory(self.root) as rootfd:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=rootfd)
            try:
                for chunk in chunks:
                    _require(isinstance(chunk, bytes), "raw retention requires bytes")
                    count += len(chunk)
                    _require(count <= length and count <= MAX_FILE_BYTES, "input grew while being retained")
                    digest.update(chunk)
                    git_sha1.update(chunk)
                    git_sha256.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(fd, view)
                        _require(written > 0, "short write retaining raw bytes")
                        view = view[written:]
                _require(count == length, "input shortened while being retained")
                os.fsync(fd)
                os.close(fd)
                fd = None
                sha = digest.hexdigest()
                relative = Path("blobs") / "sha256" / sha[:2] / sha
                with _directory(self.root / relative.parent, create=True) as destination:
                    try:
                        os.link(temp, sha, src_dir_fd=rootfd, dst_dir_fd=destination, follow_symlinks=False)
                    except FileExistsError:
                        self._verify_blob(destination, sha, length)
                    os.fsync(destination)
                self.unique_blobs.add(sha)
                return {"label": label, "blob_path": relative.as_posix(), "sha256": sha,
                        "length": length, "git_blob_sha1": git_sha1.hexdigest(),
                        "git_blob_sha256": git_sha256.hexdigest(), **(metadata or {})}
            finally:
                if fd is not None:
                    os.close(fd)
                os.unlink(temp, dir_fd=rootfd)

    @staticmethod
    def _verify_blob(parent, name, length):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_size == length,
                     "existing retained blob is invalid")
            digest, count = hashlib.sha256(), 0
            while True:
                chunk = os.read(fd, min(CHUNK_BYTES, length - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                _require(count <= length, "existing retained blob grew")
                digest.update(chunk)
            after = os.stat(name, dir_fd=parent, follow_symlinks=False)
            _require(count == length and digest.hexdigest() == name and
                     _snapshot(before) == _snapshot(os.fstat(fd)) == _snapshot(after),
                     "existing retained blob is corrupt or mutated")
        finally:
            os.close(fd)

    def retain_bytes(self, data, *, label, mode=None):
        """Retain already bounded bytes, e.g. a tracked symlink's literal target."""
        _require(isinstance(data, bytes), "retain_bytes requires bytes")
        metadata = {"kind": "bytes"}
        if mode is not None:
            metadata["mode"] = mode
        return self._store((data,), len(data), label=label, metadata=metadata)

    def _file(self, parent, name, path, label):
        fd = None
        try:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            _require(stat.S_ISREG(before.st_mode), "input is not an ordinary file: " + str(path))
            _require(before.st_size <= MAX_FILE_BYTES, "file exceeds reviewed byte bound")
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            _require(_snapshot(before) == _snapshot(os.fstat(fd)), "input changed while opening")

            def chunks():
                read = 0
                while True:
                    chunk = os.read(fd, min(CHUNK_BYTES, before.st_size - read + 1))
                    if not chunk:
                        break
                    read += len(chunk)
                    yield chunk
                after = os.stat(name, dir_fd=parent, follow_symlinks=False)
                _require(_snapshot(before) == _snapshot(os.fstat(fd)) == _snapshot(after),
                         "input mutated during retention: " + str(path))

            return self._store(chunks(), before.st_size, label=label,
                               metadata={"kind": "file", "source_path": str(path),
                                         "mode": format(stat.S_IMODE(before.st_mode), "04o")})
        except OSError as exc:
            raise RetentionError("unsafe or missing input: " + str(path) + ": " + str(exc)) from exc
        finally:
            if fd is not None:
                os.close(fd)

    def retain_file(self, path, *, label=None, root=None):
        """Retain one regular file; reject missing paths and all symlink components.

        If ``root`` is supplied, the lexical source path must be inside that root.
        Both root and the actual opened path are independently no-follow checked.
        """
        path = _absolute(path)
        if root is not None:
            root = _absolute(root)
            _require(path != root and root in path.parents, "input escaped approved root")
            with _directory(root):
                pass
        with _directory(path.parent) as parent:
            return self._file(parent, path.name, path, label or str(path))

    def _symlink(self, path, *, label):
        with _directory(path.parent) as parent:
            try:
                before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                _require(stat.S_ISLNK(before.st_mode), "tracked symlink missing: " + str(path))
                target = os.readlink(os.fsencode(path.name), dir_fd=parent)
                _require(len(target) <= MAX_PATH_BYTES, "symlink target exceeds reviewed bound")
                result = self.retain_bytes(target, label=label, mode="120000")
                after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                _require(_snapshot(before) == _snapshot(after) and
                         target == os.readlink(os.fsencode(path.name), dir_fd=parent),
                         "symlink mutated during retention")
                return {**result, "kind": "symlink", "source_path": str(path),
                        "target": os.fsdecode(target)}
            except OSError as exc:
                raise RetentionError("unsafe or missing symlink: " + str(path)) from exc

    def retain_tree(self, root, *, label=None):
        """Retain an artifact tree, including bounded internal symlink target bytes.

        Symlink targets are resolved against the retained index, never followed
        for file reads. Escaping, dangling, cyclic links, devices, FIFOs, sockets,
        added/removed entries, and directory replacement fail closed. Empty
        directories and permission modes are explicitly indexed.
        """
        root = _absolute(root)
        _require(root != self.root and root not in self.root.parents,
                 "evidence store is inside the captured tree")
        entries = []

        def walk(path, relative, depth):
            _require(depth <= MAX_DEPTH, "artifact depth exceeds reviewed bound")
            self._claim_directory()
            with _directory(path) as directory:
                before = os.fstat(directory)
                entries.append({"path": relative, "kind": "directory",
                                "mode": format(stat.S_IMODE(before.st_mode), "04o")})
                # scandir is incremental; never materialize an unbounded listing.
                seen = set()
                with os.scandir(directory) as iterator:
                    for item in iterator:
                        _require(len(seen) < MAX_FILES + MAX_DIRECTORIES, "directory entry count exceeds bound")
                        _require(item.name not in seen, "duplicate artifact directory entry")
                        seen.add(item.name)
                        name = item.name if not relative else relative + "/" + item.name
                        _validate_name(name)
                        info = os.stat(item.name, dir_fd=directory, follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):
                            walk(path / item.name, name, depth + 1)
                        elif stat.S_ISLNK(info.st_mode):
                            entries.append({"path": name, **self._symlink(path / item.name,
                                                                       label=(label or str(root)) + ":" + name)})
                        else:
                            _require(stat.S_ISREG(info.st_mode), "unapproved artifact special file: " + name)
                            entries.append({"path": name, **self._file(directory, item.name, path / item.name,
                                                                       (label or str(root)) + ":" + name)})
                _require(_snapshot(before) == _snapshot(os.fstat(directory)),
                         "artifact directory mutated during retention")
        walk(root, "", 0)
        self._validate_tree_links(entries)
        return {"kind": "filesystem-tree", "label": label or str(root), "source_path": str(root),
                "entries": sorted(entries, key=lambda item: os.fsencode(item["path"]))}

    @staticmethod
    def _validate_tree_links(entries):
        index = {record["path"]: record for record in entries}
        for record in entries:
            if record["kind"] != "symlink":
                continue
            current = record["path"].split("/")[:-1]
            pending = deque(record["target"].split("/"))
            _require(record["target"] and not record["target"].startswith("/"),
                     "absolute or empty artifact symlink target")
            hops = 0
            while pending:
                part = pending.popleft()
                if part in ("", "."):
                    continue
                if part == "..":
                    _require(current, "artifact symlink escaped capture root")
                    current.pop()
                    continue
                candidate = "/".join(current + [part])
                _require(candidate in index, "dangling artifact symlink target: " + candidate)
                target = index[candidate]
                if target["kind"] == "symlink":
                    hops += 1
                    _require(hops <= MAX_SYMLINK_HOPS, "artifact symlink cycle or excessive chain")
                    _require(target["target"] and not target["target"].startswith("/"),
                             "absolute or empty artifact symlink target")
                    pending.extendleft(reversed(target["target"].split("/")))
                else:
                    if pending:
                        _require(target["kind"] == "directory", "artifact symlink traverses a non-directory")
                    current.append(part)
                _require(len(current) + len(pending) <= MAX_DEPTH,
                         "artifact symlink resolution exceeds depth bound")
            record["resolved_target"] = "/".join(current)

    @staticmethod
    def _git_command(root, arguments):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_GRAFT_FILE=os.devnull,
                   GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1")
        command = ["git", "--no-replace-objects", "-C", str(root),
                   "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false",
                   "-c", "core.untrackedCache=false", *arguments]
        return command, env

    @staticmethod
    def _git_output(root, arguments, runner=None):
        if runner is not None:
            output = runner(root, *arguments)
            _require(isinstance(output, bytes) and len(output) <= MAX_GIT_OUTPUT_BYTES,
                     "Git listing exceeds reviewed bound")
            return output
        command, env = RawStore._git_command(root, arguments)
        with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            output = process.stdout.read(MAX_GIT_OUTPUT_BYTES + 1)
            if len(output) > MAX_GIT_OUTPUT_BYTES:
                process.kill()
                process.wait()
                raise RetentionError("Git listing exceeds reviewed bound")
            _require(process.wait() == 0, "Git could not read the requested source tree")
        return output

    @staticmethod
    @contextmanager
    def _git_batch(root):
        command, env = RawStore._git_command(root, ["cat-file", "--batch"])
        process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            yield process
            process.stdin.close()
            _require(process.wait(timeout=30) == 0, "Git object retention failed")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()

    def _retain_git_blob(self, process, oid, *, label, metadata):
        process.stdin.write(oid.encode("ascii") + b"\n")
        process.stdin.flush()
        header = process.stdout.readline(256)
        try:
            actual_oid, kind, length = header.decode("ascii").strip().split()
            length = int(length)
        except (ValueError, UnicodeError) as exc:
            raise RetentionError("missing or malformed Git blob response") from exc
        _require(actual_oid == oid and kind == "blob", "Git returned the wrong object")
        _require(0 <= length <= MAX_FILE_BYTES, "Git blob exceeds reviewed byte bound")
        if metadata.get("kind") == "symlink":
            _require(length <= MAX_PATH_BYTES, "Git symlink target exceeds reviewed bound")

        def chunks():
            remaining = length
            while remaining:
                chunk = process.stdout.read(min(CHUNK_BYTES, remaining))
                _require(chunk, "missing Git object bytes")
                remaining -= len(chunk)
                yield chunk
            _require(process.stdout.read(1) == b"\n", "Git blob framing is incomplete")

        result = self._store(chunks(), length, label=label, metadata=metadata)
        expected = result["git_blob_sha1"] if len(oid) == 40 else result["git_blob_sha256"]
        _require(oid == expected, "Git blob bytes do not match their object ID")
        return result

    def retain_git_tree(self, root, revision="HEAD", *, label=None, approved_gitlinks=None, git_runner=None):
        """Retain committed Git object bytes, including exact tracked link bytes.

        This deliberately does not substitute observed working-tree bytes. The
        adapter must verify the actual checkout separately and retain any exact
        approved resolver-lock override with ``retain_file``. Each record carries
        path, Git mode/object ID, length, SHA-256 and a raw blob reference.
        ``approved_gitlinks`` maps full relative submodule paths to exact commits;
        unknown, mismatched, missing, or unused gitlinks fail closed. Optional
        ``git_runner(root, *arguments)`` supplies audited metadata primitives;
        large blobs always stream through the bounded native Git batch reader.
        """
        root = _absolute(root)
        approvals = dict(approved_gitlinks or {})
        _require(len(approvals) <= MAX_FILES, "Gitlink approval count exceeds reviewed bound")
        for name, commit in approvals.items():
            _validate_name(name)
            _require(isinstance(commit, str) and len(commit) in (40, 64) and
                     all(c in "0123456789abcdef" for c in commit), "invalid gitlink approval")
        used = set()

        def git(path, *args):
            return self._git_output(path, args, git_runner)

        def capture(path, ref, prefix):
            with _directory(path):
                pass
            toplevel = git(path, "rev-parse", "--show-toplevel")
            _require(toplevel.endswith(b"\n") and os.fsdecode(toplevel[:-1]) == str(path), "source root is not the actual Git checkout root")
            commit = git(path, "rev-parse", "--verify", ref + "^{commit}").decode("ascii").strip()
            _require(len(commit) in (40, 64) and all(c in "0123456789abcdef" for c in commit),
                     "invalid retained commit")
            _require(git(path, "rev-parse", "HEAD").decode("ascii").strip() == commit,
                     "checkout HEAD differs from retained revision")
            tree = git(path, "rev-parse", "--verify", commit + "^{tree}").decode("ascii").strip()
            _require(len(tree) in (40, 64) and all(c in "0123456789abcdef" for c in tree),
                     "invalid retained tree")
            listing = git(path, "ls-tree", "-rzt", "--full-tree", commit)
            _require(not listing or listing.endswith(b"\0"), "incomplete Git tree listing")
            entries, names, directories = [], set(), []
            self._claim_directory()
            with self._git_batch(path) as process:
                for row in listing.split(b"\0"):
                    if not row:
                        continue
                    _require(len(names) < MAX_FILES + MAX_DIRECTORIES, "Git entry count exceeds reviewed bound")
                    try:
                        header, rawname = row.split(b"\t", 1)
                        mode, kind, oid = header.decode("ascii").split()
                    except (ValueError, UnicodeError) as exc:
                        raise RetentionError("malformed Git tree listing") from exc
                    _require(len(oid) in (40, 64) and all(c in "0123456789abcdef" for c in oid),
                             "invalid Git object ID")
                    name = os.fsdecode(rawname)
                    _validate_name(name)
                    _require(name not in names, "duplicate Git tree path")
                    names.add(name)
                    if mode == "040000":
                        _require(kind == "tree", "unsupported Git directory object")
                        self._claim_directory()
                        directories.append({"path": name, "git_mode": mode, "git_tree_oid": oid})
                        continue
                    full_name = prefix + name
                    if mode == "160000":
                        _require(kind == "commit" and approvals.get(full_name) == oid,
                                 "unapproved or mismatched gitlink: " + full_name)
                        used.add(full_name)
                        child = capture(path / name, oid, full_name + "/")
                        entries.append({"path": name, "kind": "gitlink", "git_mode": mode,
                                        "git_blob_oid": oid, "checkout": child})
                        continue
                    _require(kind == "blob" and mode in ("100644", "100755", "120000"),
                             "unsupported Git tree object")
                    record = self._retain_git_blob(process, oid,
                        label=(label or str(root)) + ":" + full_name,
                        metadata={"kind": "symlink" if mode == "120000" else "file",
                                  "source_path": str(path / name), "mode": mode,
                                  "byte_source": "committed-git-object"})
                    entries.append({"path": name, "git_mode": mode, "git_blob_oid": oid, **record})
            _require(git(path, "rev-parse", "HEAD").decode("ascii").strip() == commit,
                     "checkout HEAD changed during retention")
            return {"kind": "git-tree", "source_path": str(path), "commit": commit,
                    "tree": tree, "directories": directories, "entries": entries}
        result = capture(root, revision, "")
        _require(used == set(approvals), "unused Gitlink approval")
        return {"label": label or str(root), **result}

    def retain_executable(self, path, *, label=None, approved_roots=None):
        """Retain an executable plus each literal link in its resolution chain.

        Paths must be explicit (no PATH lookup). Any symlink requires explicit
        ``approved_roots``; the resolved executable must remain within those
        no-follow-validated roots. Every link is rechecked after final-byte capture.
        """
        requested = _absolute(path)
        roots = tuple(_absolute(root) for root in (approved_roots or ()))
        for root in roots:
            with _directory(root):
                pass
        pending = deque(requested.parts[1:])
        current = Path(requested.anchor)
        chain, snapshots = [], []
        while pending:
            part = pending.popleft()
            if part in ("", "."):
                continue
            if part == "..":
                current = current.parent
                continue
            candidate = current / part
            _require(len(os.fsencode(candidate)) <= MAX_PATH_BYTES, "executable resolution path exceeds bound")
            with _directory(current) as parent:
                try:
                    before = os.stat(part, dir_fd=parent, follow_symlinks=False)
                except OSError as exc:
                    raise RetentionError("missing executable path: " + str(candidate)) from exc
            if stat.S_ISLNK(before.st_mode):
                _require(roots, "executable symlink traversal requires approved roots")
                _require(len(chain) < MAX_SYMLINK_HOPS, "executable symlink chain exceeds bound")
                record = self._symlink(candidate, label=(label or str(requested)) + ":symlink")
                chain.append(record)
                snapshots.append((candidate, before, os.fsencode(record["target"])))
                target = Path(record["target"])
                pending.extendleft(reversed(target.parts[1:] if target.is_absolute() else target.parts))
                if target.is_absolute():
                    current = Path(target.anchor)
            else:
                if pending:
                    _require(stat.S_ISDIR(before.st_mode), "non-directory in executable path")
                current = candidate
        _require(not roots or _inside(current, roots), "resolved executable escaped approved roots")
        result = self.retain_file(current, label=label or str(requested))
        _require(int(result["mode"], 8) & 0o111, "resolved tool is not executable")
        for link, before, target in snapshots:
            with _directory(link.parent) as parent:
                try:
                    after = os.stat(link.name, dir_fd=parent, follow_symlinks=False)
                    _require(_snapshot(before) == _snapshot(after) and
                             target == os.readlink(os.fsencode(link.name), dir_fd=parent),
                             "executable symlink chain changed during retention")
                except OSError as exc:
                    raise RetentionError("executable symlink chain disappeared") from exc
        return {**result, "kind": "executable", "requested_path": str(requested),
                "resolved_path": str(current), "symlink_chain": chain}

    def summary(self):
        """Return consumption and explicit reviewed bounds for the evidence index."""
        return {"format": "p0defensive-raw-store-v1", "hash": "sha256", "logical_files": self.file_count,
                "logical_bytes": self.total_bytes, "directories": self.directory_count,
                "unique_blobs": len(self.unique_blobs),
                "limits": dict(BOUNDS)}
