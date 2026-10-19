#!/usr/bin/env python3
"""Bounded binary, authenticated GET transport for the Phase B candidate.

This helper is only a transport. Run it at its sealed path inside CommandRunner's
owned process group, then bind the real outer command and settlement receipts.
Its local JSON never establishes authentication, review or execution admission
on its own. It does not extract, import, execute or rewrite downloaded bodies.

gh's documented --include output supplies the final status and response headers:
https://cli.github.com/manual/gh_api . Its non-TTY output is captured as bytes.
Only body bytes are persisted; headers and diagnostics can contain signed URLs.
"""
import argparse
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path


REPOSITORY = "NRG-Wardog/LiveContainer"
PHASE_B_REF = "refs/heads/validation/p0-defensive-diagnostic-phase-b"
API_ROOT = "https://api.github.com/repos/" + REPOSITORY
EXPECTED_KEYS = frozenset(("repository", "run_id", "run_attempt", "host_commit",
    "host_tree", "artifact_id", "artifact_sha256", "artifact_size",
    "lock_sha256", "evidence_index_sha256"))
RECEIPT_FILES = {"run_api": "run-api.json", "artifact_api": "artifact-api.json",
    "commit_api": "commit-api.json", "archive": "artifact.zip"}
MAX_JSON = 16 * 1024 * 1024
MAX_ARCHIVE = 8 * 1024 * 1024 * 1024
MAX_HEADERS = 64 * 1024
MAX_STDERR = 64 * 1024
REQUEST_SECONDS = 900
TOTAL_SECONDS = 1500
SAFE_HEADERS = frozenset(("content-type", "content-length", "x-github-request-id",
    "x-github-api-version-selected", "etag", "date", "last-modified"))


class RetrievalError(ValueError):
    """Messages are fixed codes; never include response bytes or credentials."""


def require(condition, code):
    if not condition:
        raise RetrievalError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def parse(raw):
    def invalid_constant(_):
        raise RetrievalError("nonfinite_json_number")
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise RetrievalError("invalid_json_body") from error


def _positive(value):
    require(type(value) is int and value > 0, "positive_integer_required")
    return value


def _digest(value, length):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{%d}" % length, value)
            and value != "0" * length, "full_nonzero_digest_required")
    return value


def endpoints(expected):
    """No caller-provided URL, host, repository, branch or query is accepted."""
    require(isinstance(expected, dict) and set(expected) == EXPECTED_KEYS,
            "exact_prior_tuple_required")
    require(expected["repository"] == REPOSITORY, "wrong_repository")
    for key in ("run_id", "run_attempt", "artifact_id", "artifact_size"):
        _positive(expected[key])
    require(expected["artifact_size"] <= MAX_ARCHIVE, "archive_limit_exceeded")
    for key in ("host_commit", "host_tree"):
        _digest(expected[key], 40)
    for key in ("artifact_sha256", "lock_sha256", "evidence_index_sha256"):
        _digest(expected[key], 64)
    return {
        "run_api": API_ROOT + "/actions/runs/%d/attempts/%d" %
            (expected["run_id"], expected["run_attempt"]),
        "artifact_api": API_ROOT + "/actions/artifacts/%d" % expected["artifact_id"],
        "commit_api": API_ROOT + "/git/commits/" + expected["host_commit"],
        "archive": API_ROOT + "/actions/artifacts/%d/zip" % expected["artifact_id"],
    }


def current_identity(environment, expected):
    require(environment.get("GITHUB_REPOSITORY") == REPOSITORY
            and environment.get("GITHUB_REF") == PHASE_B_REF,
            "wrong_current_repository_or_ref")
    result = {"repository": REPOSITORY,
              "host_commit": _digest(environment.get("GITHUB_SHA"), 40)}
    for key, variable in (("run_id", "GITHUB_RUN_ID"), ("run_attempt", "GITHUB_RUN_ATTEMPT")):
        value = environment.get(variable, "")
        require(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value),
                "invalid_current_run_identity")
        result[key] = int(value)
    require(result["run_id"] != expected["run_id"], "prior_is_current_run")
    return result


def _parts(path):
    raw = os.fspath(path)
    require(isinstance(raw, str) and raw.startswith("/") and "\x00" not in raw
            and "\\" not in raw and all(p not in ("", ".", "..") for p in raw.split("/")[1:]),
            "ordinary_absolute_path_required")
    return raw.split("/")[1:]


def _directory_fd(parts):
    # Each component is opened relative to a retained directory descriptor.
    # Resolving first would hide symlink ancestors and permit substituted paths.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for part in parts:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_ordinary(path, limit):
    parts = _parts(path)
    parent = _directory_fd(parts[:-1])
    try:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, "bounded_regular_file_required")
        raw = source.read(limit + 1)
        require(len(raw) <= limit, "file_grew_beyond_limit")
        return raw


class FreshOutput:
    def __init__(self, path):
        self.path = str(path)
        parts = _parts(path)
        parent = _directory_fd(parts[:-1])
        try:
            os.mkdir(parts[-1], mode=0o700, dir_fd=parent)
            self.fd = os.open(parts[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        finally:
            os.close(parent)
        self.config_path = self.path + "/gh-config"
        os.mkdir("gh-config", mode=0o700, dir_fd=self.fd)

    def create(self, name):
        require(re.fullmatch(r"[a-z][a-z0-9.-]*", name), "unsafe_output_name")
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     mode=0o600, dir_fd=self.fd)
        return os.fdopen(fd, "wb")

    def write_json(self, name, value, secret):
        raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        require(secret not in raw, "credential_in_metadata")
        with self.create(name) as out:
            out.write(raw)
            freeze(out)

    def read(self, name, limit):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, "bounded_body_required")
            raw = source.read(limit + 1)
            require(len(raw) <= limit, "body_grew_beyond_limit")
            return raw

    def close(self):
        os.close(self.fd)


def freeze(out):
    out.flush()
    os.fsync(out.fileno())
    os.fchmod(out.fileno(), 0o444)


def gh_environment(environment, config_path):
    token = environment.get("GH_TOKEN")
    require(isinstance(token, str) and 0 < len(token) <= 8192
            and all(33 <= ord(c) <= 126 for c in token), "valid_inherited_gh_token_required")
    path = environment.get("PATH", os.defpath)
    require(isinstance(path, str) and path and all(p.startswith("/") for p in path.split(os.pathsep)),
            "absolute_search_path_required")
    # Construct, rather than redact, the child environment. GH_DEBUG, GH_HOST,
    # GH_REPO, aliases/config, alternate tokens, proxies, custom CAs, pagers,
    # forced terminal/color output and loader/runtime overrides cannot leak in.
    return {"PATH": path, "HOME": config_path, "GH_CONFIG_DIR": config_path,
        "GH_TOKEN": token, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1",
        "GH_NO_EXTENSION_UPDATE_NOTIFIER": "1", "GH_PAGER": "", "PAGER": "",
        "NO_COLOR": "1", "CLICOLOR": "0", "LC_ALL": "C", "TZ": "UTC",
        "DO_NOT_TRACK": "1"}


class BodyCapture:
    def __init__(self, out, limit, secret):
        self.out, self.limit, self.secret = out, limit, secret
        self.header_buffer = b""
        self.pending = b""
        self.status = None
        self.headers = {}
        self.body_hash = hashlib.sha256()
        self.body_bytes = 0

    def feed(self, chunk):
        if self.status is None:
            self.header_buffer += chunk
            # gh prints a LF status line, CRLF header lines and a final CRLF.
            marker = self.header_buffer.find(b"\r\n\r\n")
            width = 4
            if marker < 0:
                marker = self.header_buffer.find(b"\n\n")
                width = 2
            if marker < 0:
                require(len(self.header_buffer) <= MAX_HEADERS, "header_limit_exceeded")
                return
            boundary = marker + width
            require(boundary <= MAX_HEADERS, "header_limit_exceeded")
            header, chunk = self.header_buffer[:boundary], self.header_buffer[boundary:]
            self.header_buffer = b""
            require(self.secret not in header, "credential_in_response_header")
            lines = header.replace(b"\r\n", b"\n").split(b"\n")
            match = re.fullmatch(rb"HTTP/[0-9]+(?:\.[0-9]+)? ([0-9]{3})(?: [\x20-\x7e]*)?", lines[0])
            require(match is not None, "invalid_http_status_line")
            self.status = int(match.group(1))
            for line in lines[1:]:
                if not line:
                    continue
                require(re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+: [\x20-\x7e]*", line),
                        "invalid_response_header")
                name, value = line.split(b":", 1)
                name = name.decode("ascii").lower()
                if name in SAFE_HEADERS:
                    require(name not in self.headers, "duplicate_safe_header")
                    self.headers[name] = value.strip().decode("ascii")
            # Discard all other headers, including Location and Set-Cookie.
        self.pending += chunk
        require(self.secret not in self.pending, "credential_in_response_body")
        require(self.body_bytes + len(self.pending) <= self.limit, "body_limit_exceeded")
        # Delay a token-length suffix so cross-chunk secrets cannot be written.
        count = max(0, len(self.pending) - len(self.secret) + 1)
        self._write(self.pending[:count])
        self.pending = self.pending[count:]

    def _write(self, raw):
        self.out.write(raw)
        self.body_hash.update(raw)
        self.body_bytes += len(raw)

    def finish(self):
        require(self.status is not None, "missing_http_response_headers")
        self._write(self.pending)
        self.pending = b""
        length = self.headers.get("content-length")
        if length is not None:
            require(re.fullmatch(r"[0-9]+", length) and int(length) == self.body_bytes,
                    "response_content_length_mismatch")
        return {"status": self.status, "sha256": self.body_hash.hexdigest(),
                "bytes": self.body_bytes, "headers": self.headers}


def _stop_direct_child(process):
    # Never signal a numeric group here. The outer CommandRunner owns it.
    # A child that has already been reaped is never signaled.
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def capture_request(key, url, output, environment, deadline, body_limit):
    argv = ["gh", "api", "--method", "GET", "--include", url]
    deadline = min(deadline, time.monotonic() + REQUEST_SECONDS)
    secret = environment["GH_TOKEN"].encode("ascii")
    stdout_hash, stderr_hash = hashlib.sha256(), hashlib.sha256()
    stdout_bytes = stderr_bytes = 0
    stderr_tail = b""
    process = None
    row = {"method": "GET", "url": url, "status": None, "sha256": None,
        "bytes": 0, "headers": {}, "stdout": {}, "stderr": {},
        "command": {"argv": argv, "cwd": output.path, "returncode": None,
                    "pid": None, "pgid": None, "leaderReaped": False, "pipesJoined": False}}
    require(signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL, "default_sigchld_required")
    with output.create(RECEIPT_FILES[key]) as body, selectors.DefaultSelector() as selector:
        capture = BodyCapture(body, body_limit, secret)
        try:
            require(time.monotonic() < deadline, "retrieval_timeout")
            process = subprocess.Popen(argv, cwd=output.path, env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=False, start_new_session=False, close_fds=True)
            pgid = os.getpgid(process.pid)
            row["command"].update(pid=process.pid, pgid=pgid)
            require(pgid == os.getpgrp(), "nested_group_changed")
            for pipe, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, "retrieval_timeout")
                for ready, _ in selector.select(min(remaining, 0.25)):
                    chunk = os.read(ready.fd, 64 * 1024)
                    if not chunk:
                        selector.unregister(ready.fileobj)
                        ready.fileobj.close()
                        continue
                    if ready.data == "stdout":
                        stdout_bytes += len(chunk)
                        stdout_hash.update(chunk)
                        require(stdout_bytes <= body_limit + MAX_HEADERS, "stdout_limit_exceeded")
                        capture.feed(chunk)
                    else:
                        stderr_bytes += len(chunk)
                        stderr_hash.update(chunk)
                        require(stderr_bytes <= MAX_STDERR, "stderr_limit_exceeded")
                        combined = stderr_tail + chunk
                        require(secret not in combined, "credential_in_diagnostic")
                        stderr_tail = combined[-max(1, len(secret) - 1):]
            remaining = deadline - time.monotonic()
            require(remaining > 0, "retrieval_timeout")
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                raise RetrievalError("retrieval_timeout") from error
            row.update(capture.finish())
            row.update(
                stdout={"sha256": stdout_hash.hexdigest(), "bytes": stdout_bytes},
                stderr={"sha256": stderr_hash.hexdigest(), "bytes": stderr_bytes},
                command={"argv": argv, "cwd": output.path, "returncode": process.returncode,
                    "pid": process.pid, "pgid": pgid, "leaderReaped": True, "pipesJoined": True})
            require(process.returncode == 0, "gh_command_failed")
            require(row["status"] == 200, "unexpected_http_status")
            require(stderr_bytes == 0, "unexpected_gh_diagnostic")
            require(row["bytes"] > 0, "empty_response_body")
            return row
        except Exception as error:
            failure = error if isinstance(error, RetrievalError) else RetrievalError(type(error).__name__)
            failure.request_receipt = row
            raise failure from (None if failure is error else error)
        finally:
            if process is not None:
                if process.returncode is None:
                    _stop_direct_child(process)
                for pipe in (process.stdout, process.stderr):
                    if pipe is not None and not pipe.closed:
                        pipe.close()
                row["command"].update(returncode=process.returncode,
                    leaderReaped=process.returncode is not None)
            row.update(status=capture.status, sha256=capture.body_hash.hexdigest(),
                bytes=capture.body_bytes, headers=capture.headers,
                stdout={"sha256": stdout_hash.hexdigest(), "bytes": stdout_bytes},
                stderr={"sha256": stderr_hash.hexdigest(), "bytes": stderr_bytes})
            freeze(body)


def validate_api_body(key, raw, expected):
    """Early identity checks; the independent complete verifier remains required."""
    value = parse(raw)
    require(isinstance(value, dict), "api_object_required")
    if key == "run_api":
        require(type(value.get("id")) is int and value["id"] == expected["run_id"]
                and type(value.get("run_attempt")) is int
                and value["run_attempt"] == expected["run_attempt"]
                and value.get("head_sha") == expected["host_commit"]
                and isinstance(value.get("repository"), dict)
                and value["repository"].get("full_name") == REPOSITORY
                and value.get("status") == "completed" and value.get("conclusion") == "success",
                "prior_run_identity_or_success_mismatch")
    elif key == "artifact_api":
        run = value.get("workflow_run")
        require(type(value.get("id")) is int and value["id"] == expected["artifact_id"]
                and type(value.get("size_in_bytes")) is int
                and value["size_in_bytes"] == expected["artifact_size"]
                and value.get("digest") == "sha256:" + expected["artifact_sha256"]
                and value.get("expired") is False
                and value.get("url") == endpoints(expected)["artifact_api"]
                and isinstance(run, dict) and type(run.get("id")) is int
                and run["id"] == expected["run_id"]
                and run.get("head_sha") == expected["host_commit"],
                "prior_artifact_identity_mismatch")
    elif key == "commit_api":
        require(value.get("sha") == expected["host_commit"]
                and isinstance(value.get("tree"), dict)
                and value["tree"].get("sha") == expected["host_tree"],
                "prior_commit_identity_mismatch")
    else:
        raise RetrievalError("unknown_api_body_kind")


def retrieve(inputs_path, output_dir, environment=None):
    environment = dict(os.environ if environment is None else environment)
    input_raw = read_ordinary(inputs_path, MAX_JSON)
    inputs = parse(input_raw)
    require(isinstance(inputs, dict) and isinstance(inputs.get("prior_phase_a"), dict),
            "phase_b_prior_inputs_required")
    from prior_phase_a import validate_prior_inputs
    validate_prior_inputs(inputs["prior_phase_a"], execution=True)
    expected = inputs["prior_phase_a"].get("expected")
    urls = endpoints(expected)
    current = current_identity(environment, expected)
    # Preflight before creating anything, including when the token is missing.
    gh_environment(environment, str(output_dir) + "/gh-config")
    helper_path = os.path.abspath(__file__)
    helper_raw = read_ordinary(helper_path, MAX_JSON)
    require(os.getpgrp() == os.getpid(), "owned_outer_process_group_required")
    output = FreshOutput(output_dir)
    secret = environment["GH_TOKEN"].encode("ascii")
    metadata = {"schema_version": 1, "status": "RETRIEVED_UNSETTLED",
        "execution_admitted": False, "current_run": current, "expected": expected,
        "inputs": {"path": str(inputs_path), "sha256": sha(input_raw), "bytes": len(input_raw)},
        "helper": {"path": helper_path, "sha256": sha(helper_raw), "bytes": len(helper_raw),
                   "pid": os.getpid(), "pgid": os.getpgrp()},
        "limits": {"total_seconds": TOTAL_SECONDS, "request_seconds": REQUEST_SECONDS,
            "json_bytes": MAX_JSON, "archive_bytes": MAX_ARCHIVE,
            "header_bytes": MAX_HEADERS, "stderr_bytes": MAX_STDERR},
        "request_order": [], "requests": {}}
    try:
        env = gh_environment(environment, output.config_path)
        deadline = time.monotonic() + TOTAL_SECONDS
        for key, url in urls.items():
            metadata["request_order"].append(key)
            limit = expected["artifact_size"] if key == "archive" else MAX_JSON
            row = capture_request(key, url, output, env, deadline, limit)
            metadata["requests"][key] = row
            if key == "archive":
                require(row["sha256"] == expected["artifact_sha256"]
                        and row["bytes"] == expected["artifact_size"], "prior_archive_digest_mismatch")
            else:
                validate_api_body(key, output.read(RECEIPT_FILES[key], MAX_JSON), expected)
        output.write_json("retrieval-helper.json", metadata, secret)
        return metadata
    except Exception as error:
        if hasattr(error, "request_receipt"):
            metadata["requests"][key] = error.request_receipt
        metadata["status"] = "FAILED_UNSETTLED"
        metadata["error"] = str(error) if isinstance(error, RetrievalError) else type(error).__name__
        output.write_json("retrieval-failure.json", metadata, secret)
        raise
    finally:
        output.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        retrieve(args.inputs, args.output_dir)
    except Exception as error:
        # Do not forward gh errors, paths, URLs, environment or exception text.
        print("PRIOR_RETRIEVAL_FAILED:" + type(error).__name__, file=sys.stderr)
        return 1
    print("PRIOR_RETRIEVED_PENDING_OUTER_SETTLEMENT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
