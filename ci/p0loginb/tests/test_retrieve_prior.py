"""Synthetic offline transport tests. No real token, API call or capture claim."""
import copy
import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
HELPER = HERE.parent / "retrieve_prior.py"
spec = importlib.util.spec_from_file_location("synthetic_retrieval_subject", HELPER)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
TOKEN = "synthetic-offline-token-NEVER-A-REAL-CREDENTIAL"


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.output = self.root / "output"
        self.inputs = self.root / "inputs.json"
        self.calls = self.root / "synthetic-calls.jsonl"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("synthetic-only.bin", b"\x00\xff\xfe\x1b\r\nnever execute\x00")
            archive.writestr("untrusted.py", b"raise RuntimeError('must not execute')\n")
        self.archive = stream.getvalue()
        self.expected = {"repository": r.REPOSITORY, "run_id": 101, "run_attempt": 2,
            "host_commit": "a" * 40, "host_tree": "b" * 40, "artifact_id": 202,
            "artifact_sha256": hashlib.sha256(self.archive).hexdigest(),
            "artifact_size": len(self.archive), "lock_sha256": "c" * 64,
            "evidence_index_sha256": "d" * 64}
        self.urls = r.endpoints(self.expected)
        self.bodies = {
            "run_api": json.dumps({"id": 101, "run_attempt": 2, "head_sha": "a" * 40,
                "repository": {"full_name": r.REPOSITORY}, "status": "completed",
                "conclusion": "success"}, indent=3).encode() + b"\n",
            "artifact_api": json.dumps({"id": 202, "expired": False,
                "url": self.urls["artifact_api"], "size_in_bytes": len(self.archive),
                "digest": "sha256:" + self.expected["artifact_sha256"],
                "workflow_run": {"id": 101, "head_sha": "a" * 40}}).encode(),
            "commit_api": json.dumps({"sha": "a" * 40, "tree": {"sha": "b" * 40}}).encode(),
            "archive": self.archive,
        }
        self.environment = {"PATH": str(self.bin), "GH_TOKEN": TOKEN,
            "GITHUB_REPOSITORY": r.REPOSITORY, "GITHUB_REF": r.PHASE_B_REF,
            "GITHUB_RUN_ID": "303", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "e" * 40,
            # These must never reach the nested executable.
            "GH_DEBUG": "api", "GH_HOST": "attacker.invalid", "GH_REPO": "attacker/repo",
            "GH_CONFIG_DIR": "/untrusted", "GH_FORCE_TTY": "1", "CLICOLOR_FORCE": "1",
            "GITHUB_TOKEN": "alternate-secret", "HTTPS_PROXY": "https://attacker.invalid",
            "http_proxy": "http://attacker.invalid", "SSL_CERT_FILE": "/untrusted-ca",
            "LD_PRELOAD": "/untrusted-loader", "PYTHONPATH": "/untrusted-python",
            "PAGER": "untrusted-pager", "GH_PAGER": "untrusted-pager"}
        self.write_inputs()
        self.install_fake()

    def tearDown(self):
        self.tmp.cleanup()

    def write_inputs(self, expected=None):
        self.inputs.write_text(json.dumps({"prior_phase_a": {
            "expected": self.expected if expected is None else expected}}))

    def install_fake(self, *, status=200, exit_code=0, stderr=b"", mode="ordinary", extra_header=b""):
        responses = {}
        for key, url in self.urls.items():
            body = self.bodies[key]
            content_type = "application/zip" if key == "archive" else "application/json"
            header = ("HTTP/2.0 %d Synthetic\nContent-Type: %s\r\nContent-Length: %d\r\n"
                      % (status, content_type, len(body))).encode()
            header += (b"X-GitHub-Request-Id: synthetic-offline-request\r\n"
                       b"Location: https://signed.invalid/?opaque=do-not-persist\r\n"
                       b"Set-Cookie: synthetic-cookie-do-not-persist\r\n")
            header += extra_header + b"\r\n"
            responses[url] = header + body
        source = ("#!" + sys.executable + "\n"
            "import json, os, sys, time\n"
            "responses = " + repr(responses) + "\n"
            "assert sys.argv[1:5] == ['api', '--method', 'GET', '--include']\n"
            "assert sys.argv[5] in responses and len(sys.argv) == 6\n"
            "for key in ('GH_DEBUG', 'GH_HOST', 'GH_REPO', 'GH_FORCE_TTY', 'CLICOLOR_FORCE', "
            "'GITHUB_TOKEN', 'HTTPS_PROXY', 'http_proxy', 'SSL_CERT_FILE', 'LD_PRELOAD', 'PYTHONPATH'):\n"
            "    assert key not in os.environ\n"
            "assert os.environ['GH_TOKEN'] == " + repr(TOKEN) + "\n"
            "assert os.environ['GH_PAGER'] == os.environ['PAGER'] == ''\n"
            "assert os.environ['GH_CONFIG_DIR'] == os.getcwd() + '/gh-config'\n"
            "with open(" + repr(str(self.calls)) + ", 'a') as f:\n"
            "    f.write(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd(), 'pgid': os.getpgrp()}) + '\\n')\n"
            "mode = " + repr(mode) + "\n"
            "if mode == 'sleep': time.sleep(10)\n"
            "if mode == 'overflow_stdout': os.write(1, b'Q' * 4096); time.sleep(10)\n"
            "if mode == 'overflow_stderr': os.write(2, b'Q' * 4096); time.sleep(10)\n"
            "raw = responses[sys.argv[5]]\n"
            "if mode == 'bad_length': raw = raw.replace(b'Content-Length:', b'X-Original-Length:')"
            ".replace(b'Content-Type:', b'Content-Length: 999999\\r\\nContent-Type:')\n"
            "if mode == 'split_token_stderr':\n"
            "    token = os.environ['GH_TOKEN'].encode(); os.write(2, token[:13]); time.sleep(.02); os.write(2, token[13:])\n"
            "else: os.write(2, " + repr(stderr) + ")\n"
            "for index in range(0, len(raw), 7): os.write(1, raw[index:index+7])\n"
            "sys.exit(" + str(exit_code) + ")\n")
        executable = self.bin / "gh"
        executable.write_text(source)
        executable.chmod(0o700)

    def run_cli(self, environment=None, output=None):
        # This is always the synthetic local gh in the isolated PATH. It cannot
        # invoke a real gh or access the network; no user credentials are used.
        env = self.environment if environment is None else environment
        # Loader/Python overrides are only injected for gh_environment unit
        # coverage, not into the test's Python interpreter itself.
        env = {k: v for k, v in env.items() if k not in ("LD_PRELOAD", "PYTHONPATH")}
        return subprocess.run([sys.executable, "-B", str(HELPER), "--inputs", str(self.inputs),
            "--output-dir", str(self.output if output is None else output)], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, timeout=8)

    def request(self, *, body_limit=r.MAX_JSON):
        output = r.FreshOutput(self.output)
        try:
            env = r.gh_environment(self.environment, output.config_path)
            return r.capture_request("run_api", self.urls["run_api"], output,
                                     env, time.monotonic() + 4, body_limit)
        finally:
            output.close()

    def assert_no_secret(self):
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN.encode(), path.read_bytes(), str(path))

    def test_cli_preserves_actual_body_bytes_and_binds_exact_four_commands(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"PRIOR_RETRIEVED_PENDING_OUTER_SETTLEMENT\n")
        metadata = json.loads((self.output / "retrieval-helper.json").read_bytes())
        self.assertEqual(metadata["status"], "RETRIEVED_UNSETTLED")
        self.assertIs(metadata["execution_admitted"], False)
        self.assertEqual(metadata["expected"], self.expected)
        self.assertEqual(metadata["request_order"], ["run_api", "artifact_api", "commit_api", "archive"])
        self.assertEqual(metadata["current_run"]["run_id"], 303)
        self.assertEqual(metadata["helper"]["pid"], metadata["helper"]["pgid"])
        self.assertEqual(metadata["helper"]["sha256"], r.sha(HELPER.read_bytes()))
        self.assertEqual(metadata["inputs"]["sha256"], r.sha(self.inputs.read_bytes()))
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 4)
        for index, (key, name) in enumerate(r.RECEIPT_FILES.items()):
            body = (self.output / name).read_bytes()
            row = metadata["requests"][key]
            self.assertEqual(body, self.bodies[key])
            self.assertEqual(stat.S_IMODE((self.output / name).stat().st_mode), 0o444)
            self.assertEqual(row["sha256"], r.sha(body))
            self.assertEqual(row["bytes"], len(body))
            self.assertEqual(row["status"], 200)
            self.assertEqual(row["command"]["argv"], ["gh", "api", "--method", "GET", "--include", self.urls[key]])
            self.assertEqual(calls[index]["argv"], row["command"]["argv"][1:])
            self.assertEqual(row["command"]["cwd"], str(self.output))
            self.assertEqual(row["command"]["returncode"], 0)
            self.assertEqual(row["command"]["pgid"], metadata["helper"]["pgid"])
            self.assertTrue(row["command"]["leaderReaped"])
            self.assertTrue(row["command"]["pipesJoined"])
            self.assertNotIn("ownedProcessGroup", row["command"])
            self.assertNotIn("authenticated", row)
            self.assertEqual(row["stderr"], {"bytes": 0, "sha256": r.sha(b"")})
            self.assertGreater(row["stdout"]["bytes"], len(body))
            self.assertEqual(set(row["headers"]), {"content-type", "content-length", "x-github-request-id"})
        evidence = b"".join(p.read_bytes() for p in self.output.iterdir() if p.is_file())
        for value in (b"signed.invalid", b"synthetic-cookie", TOKEN.encode()):
            self.assertNotIn(value, evidence)
        self.assertFalse((self.output / "retrieval-failure.json").exists())
        self.assertEqual(list((self.output / "gh-config").iterdir()), [])

    def test_inherited_environment_is_allowlisted_and_not_recorded(self):
        env = r.gh_environment(self.environment, str(self.output / "gh-config"))
        self.assertEqual(env["GH_TOKEN"], TOKEN)
        self.assertEqual(env["HOME"], env["GH_CONFIG_DIR"])
        for key in ("GH_DEBUG", "GH_HOST", "GH_REPO", "GITHUB_TOKEN", "HTTPS_PROXY",
                    "http_proxy", "SSL_CERT_FILE", "LD_PRELOAD", "PYTHONPATH"):
            self.assertNotIn(key, env)
        self.request()
        self.assert_no_secret()

    def test_unresolved_or_malformed_prior_fails_before_output_or_subprocess(self):
        cases = [(key, None) for key in self.expected]
        cases += [("run_id", True), ("run_attempt", 0), ("artifact_id", "202"),
                  ("repository", "attacker/repo"), ("host_commit", "main"),
                  ("host_tree", "0" * 40), ("artifact_sha256", "0" * 64),
                  ("artifact_size", r.MAX_ARCHIVE + 1)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                expected = dict(self.expected, **{key: value})
                self.write_inputs(expected)
                result = self.run_cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.calls.exists())

    def test_wrong_current_identity_and_missing_token_fail_without_effects(self):
        cases = [("GITHUB_REPOSITORY", "attacker/repo"), ("GITHUB_REF", "refs/heads/main"),
                 ("GITHUB_RUN_ID", "101"), ("GITHUB_RUN_ID", "0"), ("GITHUB_RUN_ID", "0303"),
                 ("GITHUB_RUN_ATTEMPT", "true"), ("GITHUB_SHA", "short"),
                 ("GH_TOKEN", ""), ("GH_TOKEN", "contains whitespace"), ("PATH", ".")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                result = self.run_cli(dict(self.environment, **{key: value}))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.calls.exists())

    def test_direct_unowned_helper_cannot_claim_outer_settlement(self):
        with mock.patch.object(r.os, "getpgrp", return_value=0):
            with self.assertRaisesRegex(r.RetrievalError, "owned_outer_process_group_required"):
                r.retrieve(str(self.inputs), str(self.output), self.environment)
        self.assertFalse(self.output.exists())

    def test_fresh_output_never_overwrites_existing_file_directory_or_symlink(self):
        victim = self.root / "victim"
        victim.write_bytes(b"untouched")
        for kind in ("file", "directory", "symlink"):
            output = self.root / ("existing-" + kind)
            if kind == "file":
                output.write_bytes(b"untouched")
            elif kind == "directory":
                output.mkdir()
            else:
                output.symlink_to(victim)
            with self.subTest(kind=kind):
                result = self.run_cli(output=output)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.calls.exists())
                self.assertEqual(victim.read_bytes(), b"untouched")

    def test_no_symlink_ancestors_input_links_relative_paths_or_parent_traversal(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            r.read_ordinary(alias / self.inputs.name, r.MAX_JSON)
        with self.assertRaises(OSError):
            r.FreshOutput(alias / "output")
        link = self.root / "input-link.json"
        link.symlink_to(self.inputs)
        with self.assertRaises(OSError):
            r.read_ordinary(link, r.MAX_JSON)
        for path in ("relative", str(self.root) + "/../output", str(self.root) + "//output"):
            with self.subTest(path=path), self.assertRaises(r.RetrievalError):
                r.FreshOutput(path)

    def test_nonzero_exit_records_actual_code_and_never_success(self):
        self.install_fake(exit_code=3, stderr=b"synthetic failure detail\n")
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        failure = json.loads((self.output / "retrieval-failure.json").read_bytes())
        row = failure["requests"]["run_api"]
        self.assertEqual(row["command"]["returncode"], 3)
        self.assertEqual(row["status"], 200)
        self.assertEqual(row["stderr"]["sha256"], r.sha(b"synthetic failure detail\n"))
        self.assertFalse((self.output / "retrieval-helper.json").exists())
        self.assertNotIn(b"synthetic failure detail", (self.output / "retrieval-failure.json").read_bytes())
        self.assertNotIn(b"synthetic failure detail", result.stderr)

    def test_zero_exit_with_failed_http_status_is_not_success(self):
        self.install_fake(status=401)
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        failure = json.loads((self.output / "retrieval-failure.json").read_bytes())
        self.assertEqual(failure["requests"]["run_api"]["status"], 401)
        self.assertEqual(failure["error"], "unexpected_http_status")

    def test_mismatched_api_identity_stops_before_next_endpoint(self):
        run = json.loads(self.bodies["run_api"])
        run["id"] = 999
        self.bodies["run_api"] = json.dumps(run).encode()
        self.install_fake()
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.assertFalse((self.output / "artifact-api.json").exists())

    def test_altered_archive_bytes_fail_pinned_digest(self):
        self.bodies["archive"] = self.archive[:-1] + bytes([self.archive[-1] ^ 1])
        self.install_fake()
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        failure = json.loads((self.output / "retrieval-failure.json").read_bytes())
        self.assertEqual(failure["error"], "prior_archive_digest_mismatch")
        self.assertEqual((self.output / "artifact.zip").read_bytes(), self.bodies["archive"])

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        for raw in (b'{"id":101,"id":101}', b'{"value":NaN}', b'{"value":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(r.RetrievalError):
                r.parse(raw)

    def test_body_length_mismatch_fails_and_does_not_create_success(self):
        self.install_fake(mode="bad_length")
        with self.assertRaisesRegex(r.RetrievalError, "response_content_length_mismatch"):
            self.request()

    def test_timeout_kills_and_reaps_nested_leader_without_group_signals(self):
        self.install_fake(mode="sleep")
        start = time.monotonic()
        with mock.patch.object(r, "REQUEST_SECONDS", .15), mock.patch.object(r.os, "killpg") as group_signal:
            with self.assertRaisesRegex(r.RetrievalError, "retrieval_timeout") as caught:
                self.request()
        self.assertLess(time.monotonic() - start, 2)
        self.assertTrue(caught.exception.request_receipt["command"]["leaderReaped"])
        self.assertLess(caught.exception.request_receipt["command"]["returncode"], 0)
        group_signal.assert_not_called()

    def test_oversized_stdout_header_and_stderr_are_bounded(self):
        self.install_fake(mode="overflow_stdout")
        with mock.patch.object(r, "MAX_HEADERS", 64):
            with self.assertRaisesRegex(r.RetrievalError, "stdout_limit_exceeded"):
                self.request(body_limit=16)
        self.assertLessEqual((self.output / "run-api.json").stat().st_size, 16)
        self.output = self.root / "stderr-output"
        self.install_fake(mode="overflow_stderr")
        with mock.patch.object(r, "MAX_STDERR", 64):
            with self.assertRaisesRegex(r.RetrievalError, "stderr_limit_exceeded"):
                self.request()

    def test_body_limit_catches_full_body_even_while_secret_tail_is_delayed(self):
        stream = io.BytesIO()
        capture = r.BodyCapture(stream, 3, TOKEN.encode())
        with self.assertRaisesRegex(r.RetrievalError, "body_limit_exceeded"):
            capture.feed(b"HTTP/2.0 200 OK\nContent-Type: application/json\r\n\r\n1234")
        self.assertEqual(stream.getvalue(), b"")

    def test_token_in_body_headers_or_chunked_diagnostics_never_persists(self):
        self.bodies["run_api"] += TOKEN.encode()
        self.install_fake()
        self.assertEqual(self.run_cli().returncode, 1)
        self.assert_no_secret()
        self.bodies["run_api"] = self.bodies["run_api"][:-len(TOKEN)]
        self.output = self.root / "header-secret-output"
        self.install_fake(extra_header=b"X-Private: " + TOKEN.encode() + b"\r\n")
        self.assertEqual(self.run_cli().returncode, 1)
        self.assert_no_secret()
        self.output = self.root / "stderr-secret-output"
        self.install_fake(mode="split_token_stderr")
        self.assertEqual(self.run_cli().returncode, 1)
        self.assert_no_secret()

    def test_streaming_token_guard_rejects_every_possible_boundary(self):
        header = b"HTTP/2.0 200 OK\nContent-Type: application/json\r\n\r\n"
        for split in range(1, len(TOKEN)):
            stream = io.BytesIO()
            capture = r.BodyCapture(stream, 4096, TOKEN.encode())
            capture.feed(header + b"prefix" + TOKEN.encode()[:split])
            with self.subTest(split=split), self.assertRaisesRegex(r.RetrievalError, "credential_in_response_body"):
                capture.feed(TOKEN.encode()[split:])
            self.assertNotIn(TOKEN.encode(), stream.getvalue())


if __name__ == "__main__":
    unittest.main()
