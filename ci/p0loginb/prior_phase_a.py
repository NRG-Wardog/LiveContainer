"""Fail-closed, read-only Phase A prerequisite for the separate Phase B draft.

No downloads, extraction, archive imports, Git writes, native commands or lock
materialization occur here. A local receipt is not by itself authentication:
the reviewed current-run transport must obtain it using authenticated GETs.
The transport/schema precheck is supplemented by an independently authored,
digest-bound command/source replay receipt. Unresolved bindings fail closed.
"""
import builtins
import hashlib
import json
import os
import re
import sys
import types
from pathlib import Path

REPOSITORY = "NRG-Wardog/LiveContainer"
PHASE_B_REF = "refs/heads/validation/p0-login-trace-phase-b"
INPUT_SHA256 = "4b765084e34ee1a88d35af4553327f131983d7002c0c6b6ae54acf976a171cfa"
OVERLAY_SHA256 = "8e02dca274fdd0d0d3ce8457bcf25160252021423154ed4f486bc1e622c5685d"
# Exact successful retry2 adapter closure, separately reviewed.
REFERENCE_VERIFIER_SHA256 = "c554e5ea9ecb297f004ab5b03d5c60662269cf8c3ba200d15e08e6ff1cac21b4"
# The local verifier is a precheck; the original independent receipt is also mandatory.
REVIEWED_VERIFIER_SHA256 = "c554e5ea9ecb297f004ab5b03d5c60662269cf8c3ba200d15e08e6ff1cac21b4"

EXPECTED_KEYS = frozenset(("repository", "run_id", "run_attempt", "host_commit",
    "host_tree", "artifact_id", "artifact_sha256", "artifact_size",
    "lock_sha256", "evidence_index_sha256"))
RECEIPT_FILES = {"run_api": "run-api.json", "artifact_api": "artifact-api.json",
    "commit_api": "commit-api.json", "archive": "artifact.zip"}
MAX_JSON = 16 * 1024 * 1024
REPLAY_CHECKS = frozenset(("commands_argv_cwd_order", "source_inventory_origin_tree",
    "resolved_package_sources", "finite_test_execution", "writers_quiescent",
    "terminal_lock_bytes", "artifact_full_index"))
REPLAY_SCOPE = "ACTUAL_COMMAND_ORDER_CWD_SOURCE_AND_TEST_REPLAY"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=_pairs)


def _digest(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
            and value != "0" * 64, "full nonzero SHA256 required")
    return value


def _git_sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value)
            and value != "0" * 40, "full nonzero Git SHA required")
    return value


def _positive(value):
    require(type(value) is int and value > 0, "actual positive API integer required")
    return value


def _ordinary(root, relative):
    root = Path(root)
    require(not root.is_symlink() and root.is_dir(), "ordinary existing input root required")
    require(isinstance(relative, str) and relative and "\\" not in relative
            and ":" not in relative and "\0" not in relative
            and all(p not in ("", ".", "..") for p in relative.split("/")),
            "unsafe local input path")
    # Check ancestors too; resolving first would hide substituted directories.
    require(all(not p.is_symlink() for p in (root, *root.parents)), "linked input ancestor")
    path = root
    for part in relative.split("/"):
        path = path / part
        require(not path.is_symlink(), "linked local input")
    require(path.is_file(), "missing ordinary input: " + relative)
    return path


def _json_bytes(root, relative):
    path = _ordinary(root, relative)
    require(path.stat().st_size <= MAX_JSON, "JSON input too large")
    raw = path.read_bytes()
    require(len(raw) <= MAX_JSON, "JSON input grew beyond limit")
    return raw


def make_draft_prior(approved_adapter=None):
    """Known reviewed source anchors, never a guessed successful capture tuple."""
    prior = {"schema_version": 1, "source_basis": "p0-login-trace-phase-a-v1",
        "phase": "phase-a", "approved_inputs_sha256": None,
        "approved_overlay_sha256": None,
        "approved_verifier_sha256": None,
        "upload_identity_sha256": None,
        "independent_review": None,
        "expected": {key: None for key in sorted(EXPECTED_KEYS)}}
    if approved_adapter is not None:
        require(isinstance(approved_adapter, dict) and set(approved_adapter) ==
                {"approved_inputs_sha256", "approved_overlay_sha256", "approved_verifier_sha256"},
                "exact explicit approved adapter digest metadata required")
        for value in approved_adapter.values():
            _digest(value)
        prior.update(approved_adapter)
    return prior


def _validate_expected(expected):
    require(isinstance(expected, dict) and set(expected) == EXPECTED_KEYS,
            "exact independently reviewed prior tuple required")
    require(all(value is not None for value in expected.values()),
            "successful Phase A run/artifact/lock tuple remains unresolved")
    require(expected["repository"] == REPOSITORY, "wrong prior repository")
    for key in ("run_id", "run_attempt", "artifact_id", "artifact_size"):
        _positive(expected[key])
    for key in ("host_commit", "host_tree"):
        _git_sha(expected[key])
    for key in ("artifact_sha256", "lock_sha256", "evidence_index_sha256"):
        _digest(expected[key])


def validate_prior_inputs(prior, execution=False):
    require(isinstance(prior, dict) and set(prior) == set(make_draft_prior()),
            "unexpected prior Phase A schema")
    require(type(prior["schema_version"]) is int and prior["schema_version"] == 1
            and prior["source_basis"] == "p0-login-trace-phase-a-v1"
            and prior["phase"] == "phase-a", "wrong prior phase/source basis")
    for key in ("approved_inputs_sha256", "approved_overlay_sha256", "approved_verifier_sha256", "upload_identity_sha256"):
        if prior[key] is not None:
            _digest(prior[key])
    require(isinstance(prior["expected"], dict)
            and set(prior["expected"]) == EXPECTED_KEYS, "wrong prior tuple fields")
    unresolved = all(value is None for value in prior["expected"].values())
    if not unresolved:
        _validate_expected(prior["expected"])
    verifier = prior["approved_verifier_sha256"]
    review = prior["independent_review"]
    if review is not None:
        require(isinstance(review, dict) and set(review) == {"receipt_sha256", "reviewer"},
                "independent review must bind an exact receipt digest and reviewer")
        _digest(review["receipt_sha256"])
        require(isinstance(review["reviewer"], str) and review["reviewer"].strip() == review["reviewer"]
                and 0 < len(review["reviewer"]) <= 200, "independent reviewer identity required")
    if execution:
        _validate_expected(prior["expected"])
        require(prior["approved_inputs_sha256"] is not None
                and prior["approved_overlay_sha256"] is not None,
                "final successful Phase A input/overlay approval is unresolved")
        require(review is not None, "independent actual execution replay review is unresolved")
        require(verifier == REVIEWED_VERIFIER_SHA256,
                "approved prior verifier is unresolved")
        require(prior["upload_identity_sha256"] is not None, "original reviewed upload identity is unresolved")
    return {"status": "DRAFT_PRIOR_UNRESOLVED" if unresolved else "PRIOR_TUPLE_STRUCTURALLY_VALID",
            "execution_admitted": False, "independent_replay_receipt_bound": review is not None}


def _validate_independent_review(raw, prior):
    """Bind the existing original review receipt; never synthesize an attestation."""
    binding=prior["independent_review"]
    require(isinstance(binding,dict) and set(binding)=={"receipt_sha256","reviewer"},
            "independent actual execution replay review is unresolved")
    require(sha(raw)==_digest(binding["receipt_sha256"]),"independent review receipt bytes changed")
    review=parse(raw);expected=prior["expected"]
    require(isinstance(review,dict) and set(review)=={
        "schema","status","run_id","run_attempt","host_commit","host_tree","artifact_id","artifact_sha256",
        "input_sha256","evidence_index_sha256","authenticated_receipt_sha256","exact_ordered_top_level_commands",
        "nested_host_commands","indexed_files","metadata_checks","python_suite_tests","source_tracked_entries",
        "swift_tests","sidesign_lock","sidesign_lock_git_blob","independently_bound_remote_dependency_trees",
        "device_login_proven","guest_execution","production_ready","scope_notes"},"unexpected original independent receipt schema")
    require(type(review["schema"]) is int and review["schema"]==1 and
            review["status"]=="INDEPENDENT_PHASE_A_EVIDENCE_REVIEW_PASSED","independent evidence review did not pass")
    for key in ("run_id","run_attempt","host_commit","host_tree","artifact_id","artifact_sha256","evidence_index_sha256"):
        require(review[key]==expected[key] and type(review[key]) is type(expected[key]),"independent review covers another capture")
    require(review["input_sha256"]==prior["approved_inputs_sha256"],"reviewed adapter input differs")
    require(review["sidesign_lock"]["sha256"]==expected["lock_sha256"],"reviewed lock differs")
    require(all(review[key] is False for key in ("device_login_proven","guest_execution","production_ready")),"review scope expanded")
    require(review["exact_ordered_top_level_commands"]==67 and review["nested_host_commands"]==208 and
            review["indexed_files"]==799 and review["metadata_checks"]==2139 and review["python_suite_tests"]==57,
            "successful exact-capture review counts differ")
    require(review["source_tracked_entries"]=={"AnisetteKit":52,"SideSign":72,"SideStore":658,"LiveContainer":311},"review source inventory differs")
    for owner,count in (("AnisetteKit",6),("SideSign",5)):
        test=review["swift_tests"][owner]
        require(test["executed"]==count and test["failed"]==test["skipped"]==0 and len(test["test_ids"])==len(set(test["test_ids"]))==count,"review finite tests differ")
    for value in review["authenticated_receipt_sha256"].values():_digest(value)
    for value in review["independently_bound_remote_dependency_trees"].values():_git_sha(value)
    _git_sha(review["sidesign_lock_git_blob"])
    return review


def _load_trusted_adapter(prior_adapter, approved_inputs, verifier_path, approved_verifier):
    """Hash the complete frozen closure before compiling any of its code.

    Absolute Phase A imports resolve through a private import function, never
    sys.modules or sys.path. Existing Phase B native_gate/inventory modules are
    neither consulted nor replaced. Code comes only from authenticated bytes.
    """
    host = Path(prior_adapter)
    input_raw = _json_bytes(host, "ci/p0login/inputs-phase-a.json")
    require(sha(input_raw) == _digest(approved_inputs),
            "approved Phase A input bytes differ")
    data = parse(input_raw)
    expected = data["adapter_files"]
    require(isinstance(expected, dict) and expected, "missing frozen adapter inventory")
    closure = {}
    for name, digest in expected.items():
        require(name.startswith("ci/p0login/"), "adapter namespace escaped")
        raw = _ordinary(host, name).read_bytes()
        require(sha(raw) == _digest(digest), "frozen adapter bytes changed: " + name)
        closure[name] = raw
    actual = set()
    for path in (host / "ci/p0login").rglob("*"):
        require(not path.is_symlink(), "linked adapter member")
        if path.is_file():
            actual.add(path.relative_to(host).as_posix())
    require(actual == set(expected) | {"ci/p0login/inputs-phase-a.json"},
            "frozen adapter contains an extra or missing file")
    # Inventory validation later checks both workflows against the approved input.
    for name in (".github/workflows/build.yml", ".github/workflows/p0-login-trace-phase-a.yml"):
        _ordinary(host, name)
    verifier_path = Path(verifier_path)
    verifier_raw = _json_bytes(verifier_path.parent, verifier_path.name)
    require(sha(verifier_raw) == _digest(approved_verifier), "frozen verifier bytes changed")
    modules = {}
    sys_copy = types.ModuleType("sys")
    sys_copy.__dict__.update(vars(sys))
    sys_copy.path = list(sys.path)
    sys_copy.dont_write_bytecode = True
    builtin_import = builtins.__import__

    def private_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name == "sys":
            return sys_copy
        if level == 0 and name in ("source_primitives", "inventory", "lifecycle", "native_gate"):
            return load(name)
        return builtin_import(name, globals, locals, fromlist, level)

    def load(name):
        if name in modules:
            return modules[name]
        module = types.ModuleType("_p0login_prior_private_" + name)
        path = host / "ci/p0login" / (name + ".py")
        raw = closure["ci/p0login/" + name + ".py"]
        module.__file__ = str(path)
        module.__builtins__ = dict(vars(builtins), __import__=private_import)
        modules[name] = module
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
        return module

    gate = load("native_gate")
    gate.validate_inputs(input_raw, approved_inputs, host)
    verifier = types.ModuleType("_p0login_prior_private_artifact_verifier")
    verifier.__file__ = str(verifier_path)
    verifier.__builtins__ = dict(vars(builtins), __import__=private_import)
    exec(compile(verifier_raw, str(verifier_path), "exec", dont_inherit=True), verifier.__dict__)
    return verifier, gate, data, input_raw


def _validate_current_transport(current, receipts, raw_inputs, expected, *,
                                helper_raw, inputs_path, inputs_raw, work_root, receipts_dir):
    """Bind fixed helper text, actual owned outer command and nested GET receipts."""
    import retrieve_prior as helper
    require(isinstance(current,dict) and set(current)=={"repository","run_id","run_attempt","host_commit"},"exact current run identity required")
    require(current["repository"]==REPOSITORY,"wrong current repository")
    for key in ("run_id","run_attempt"):_positive(current[key])
    _git_sha(current["host_commit"])
    actual={"repository":os.environ.get("GITHUB_REPOSITORY"),"run_id":os.environ.get("GITHUB_RUN_ID"),
        "run_attempt":os.environ.get("GITHUB_RUN_ATTEMPT"),"host_commit":os.environ.get("GITHUB_SHA")}
    require(actual=={k:str(v) for k,v in current.items()} and os.environ.get("GITHUB_REF")==PHASE_B_REF,"retrieval does not bind current environment")
    require(current["run_id"]!=expected["run_id"],"prior capture cannot be current run")
    require(set(receipts)=={"schema_version","current_run","helper_report_sha256","outer_command","outer_settlement"} and
            type(receipts["schema_version"]) is int and receipts["schema_version"]==1 and receipts["current_run"]==current,
            "unexpected outer retrieval receipt schema")
    require(sha(helper_raw)==receipts["helper_report_sha256"],"helper report bytes changed")
    report=parse(helper_raw)
    require(set(report)=={"schema_version","status","execution_admitted","current_run","expected","inputs","helper","limits","request_order","requests"},"unexpected helper report schema")
    require(report["schema_version"]==1 and report["status"]=="RETRIEVED_UNSETTLED" and report["execution_admitted"] is False and
            report["current_run"]==current and report["expected"]==expected,"wrong helper capture identity")
    fixed=Path(__file__).resolve().parent/"retrieve_prior.py"
    inputs_path=Path(inputs_path);work_root=Path(work_root);receipts_dir=Path(receipts_dir)
    for path in (fixed,inputs_path,work_root,receipts_dir):
        require(path.is_absolute() and all(not x.is_symlink() for x in (path,*path.parents)),"linked retrieval boundary")
    require(report["inputs"]=={"path":str(inputs_path),"sha256":sha(inputs_raw),"bytes":len(inputs_raw)},"helper input bytes/path differ")
    identity=report["helper"]
    require(set(identity)=={"path","sha256","bytes","pid","pgid"} and identity["path"]==str(fixed) and
            identity["sha256"]==sha(fixed.read_bytes()) and identity["bytes"]==fixed.stat().st_size,"fixed helper bytes/path differ")
    _positive(identity["pid"]);require(identity["pid"]==identity["pgid"],"helper was not outer process-group leader")
    command=receipts["outer_command"]
    require(set(command)=={"argv","cwd","environment"} and command["argv"]==[sys.executable,"-B",str(fixed),"--inputs",str(inputs_path),"--output-dir",str(receipts_dir)] and command["cwd"]==str(work_root),"actual outer command differs")
    require(not any("TOKEN" in key for key in command["environment"]),"secret persisted in environment receipt")
    settled=receipts["outer_settlement"];owned=settled.get("ownedProcessGroup",{})
    require(type(settled.get("returncode")) is int and settled["returncode"]==0 and type(settled.get("terminationReturncode")) is int and settled["terminationReturncode"]==0 and not settled.get("error") and not settled.get("quiescenceError"),"outer retrieval failed")
    require(owned.get("pgid")==identity["pid"] and all(owned.get(key) is True for key in ("quiescent","pipesJoined","leaderReaped")) and
            not owned.get("errors") and owned.get("signals")==[] and owned.get("postReapPolicy")=="read-only-group-disappearance" and
            not (owned.get("reapedBeforeSignals") and owned.get("signals")),"outer retrieval group did not settle")
    require(report["limits"]=={"total_seconds":helper.TOTAL_SECONDS,"request_seconds":helper.REQUEST_SECONDS,"json_bytes":helper.MAX_JSON,
            "archive_bytes":helper.MAX_ARCHIVE,"header_bytes":helper.MAX_HEADERS,"stderr_bytes":helper.MAX_STDERR},"retrieval limits changed")
    urls=helper.endpoints(expected)
    require(report["request_order"]==list(urls) and set(report["requests"])==set(urls)==set(raw_inputs),"missing/extra/reordered retrieval request")
    for key,url in urls.items():
        row=report["requests"][key]
        require(set(row)=={"method","url","status","sha256","bytes","headers","stdout","stderr","command"},"unexpected request schema")
        require(row["method"]=="GET" and row["url"]==url and type(row["status"]) is int and row["status"]==200,"wrong retrieval operation/status")
        require(row["sha256"]==sha(raw_inputs[key]) and type(row["bytes"]) is int and row["bytes"]==len(raw_inputs[key]),"retrieval response bytes changed")
        nested=row["command"]
        require(set(nested)=={"argv","cwd","returncode","pid","pgid","leaderReaped","pipesJoined"} and
            nested["argv"]==["gh","api","--method","GET","--include",url] and nested["cwd"]==str(receipts_dir) and
            type(nested["returncode"]) is int and nested["returncode"]==0 and nested["pgid"]==identity["pgid"] and
            nested["leaderReaped"] is True and nested["pipesJoined"] is True,"nested GET command/lifecycle differs")
        _positive(nested["pid"]);require(nested["pid"]!=identity["pid"],"nested command identity aliases helper")
        require(set(row["headers"])<=helper.SAFE_HEADERS,"unsafe retained HTTP header")
        require(row["stderr"]=={"sha256":sha(b""),"bytes":0} and type(row["stderr"]["bytes"]) is int,"successful retrieval stderr must be empty")
        require(type(row["stdout"].get("bytes")) is int and len(raw_inputs[key])<row["stdout"]["bytes"],"HTTP header bytes absent from stdout receipt")
        for stream,limit in (("stdout",len(raw_inputs[key])+helper.MAX_HEADERS),("stderr",helper.MAX_STDERR)):
            record=row[stream];require(set(record)=={"sha256","bytes"} and type(record["bytes"]) is int and 0<=record["bytes"]<=limit,"invalid raw stream digest record");_digest(record["sha256"])
    return sha(json.dumps(receipts,sort_keys=True,separators=(",",":")).encode())


def _validate_api(verifier, run, artifact, commit, upload, overlay, archive, expected):
    _validate_expected(expected)
    identity = verifier.verify_api(run, artifact, commit, upload, overlay, archive)
    require(run["conclusion"] == "success" and run["status"] == "completed",
            "successful completed Phase A workflow required")
    for key in ("repository", "run_id", "run_attempt", "host_commit", "host_tree",
                "artifact_id", "artifact_sha256"):
        require(identity[key] == expected[key] and type(identity[key]) is type(expected[key]),
                "actual API differs from independently approved prior " + key)
    require(archive["bytes"] == expected["artifact_size"], "approved artifact size differs")
    return identity


class _SourceRoots:
    def __init__(self,roots):self.roots=roots
    def __truediv__(self,owner):
        require(owner in ("AnisetteKit","SideSign","SideStore","LiveContainer"),"unknown source object owner")
        return Path(self.roots[owner]) if isinstance(self.roots,dict) else Path(self.roots)/owner

def _validate_source_receipts(files, gate, data, source_objects):
    """Recompute source tree/delta/count/gitlinks and test/metadata input hashes."""
    source_objects = _SourceRoots(source_objects)
    proofs = {phase: parse(files["provenance/source-" + phase + ".json"])
              for phase in ("before", "after")}
    for phase in proofs:
        require(set(proofs[phase]) == set(data["owners"]), "source owner closure differs")
    for owner, row in data["owners"].items():
        root = source_objects / owner
        require(not root.is_symlink() and root.is_dir(), "ordinary immutable source object root required")
        require(gate.snapshot(root, row["base"], row["commit"]) ==
                {"tree": row["tree"], "changes": row["changes"]}, "actual prior source objects differ")
        records = gate.entries(root, row["commit"])
        children = {path: entry[2] for path, entry in records.items() if entry[1] == "commit"}
        for phase in proofs:
            proof = proofs[phase][owner]
            require(set(proof) == {"commit", "tree", "tracked_entries", "gitlinks_unpopulated", "status", "origin"},
                    "unexpected prior source proof fields")
            require(proof["commit"] == row["commit"] and proof["tree"] == row["tree"]
                    and type(proof["tracked_entries"]) is int
                    and proof["tracked_entries"] == len(records)
                    and proof["gitlinks_unpopulated"] == children,
                    "source inventory/count/gitlinks differ from exact objects")
            require(proof["origin"] == {"kind": "direct", "repository": row["repository"]},
                    "prior source origin differs")
            statuses = {""}
            if phase == "after" and owner == "SideSign":
                statuses = {" M Package.resolved\n"}
            if phase == "after" and owner == "AnisetteKit" and \
                    "provenance/AnisetteKit.Package.resolved.observed" in files:
                statuses.add("?? Package.resolved\n")
            require(proof["status"] in statuses, "unexpected source working-tree change")
        if owner in data["test_source_audit"]:
            actual = {name: sha(gate.git(root, "cat-file", "blob", entry[2]))
                      for name, entry in records.items()
                      if name.startswith("Tests/") and name.endswith(".swift") and entry[1] == "blob"}
            require(actual == data["test_source_audit"][owner], "actual test source bytes differ")
    metadata = parse(files["metadata-units/result.json"])
    ak = data["owners"]["AnisetteKit"]
    for name, digest in metadata["source_sha256"].items():
        require(sha(gate.git(source_objects / "AnisetteKit", "show", ak["commit"] + ":" + name)) == digest,
                "metadata test source bytes differ from sealed source")
    observed = files.get("provenance/AnisetteKit.Package.resolved.observed")
    final = files.get("provenance/AnisetteKit.Package.resolved.final-observed")
    require(observed == final, "AnisetteKit final lock differs from observed resolver bytes")


def _validate_lock(files, gate, data, source_objects, expected):
    names = ["provenance/SideSign.Package.resolved." + stage
             for stage in ("before", "after", "final-observed")]
    require(all(name in files for name in names), "complete genuine SideSign lock receipts required")
    before, after, final = (files[name] for name in names)
    source = data["owners"]["SideSign"]
    original = gate.git(_SourceRoots(source_objects) / "SideSign", "show", source["commit"] + ":Package.resolved")
    require(before == original, "prior original lock differs from sealed source bytes")
    require(after == final and sha(after) == expected["lock_sha256"],
            "exact independently approved terminal SideSign lock bytes required")
    checked = gate.check_lock(before, after, data["owners"]["AnisetteKit"]["commit"])
    require(parse(files["provenance/result.json"])["resolved_lock"] == checked,
            "captured SideSign lock summary differs")
    return after


def _verify_bound_capture(prior, receipts_dir, prior_adapter, source_objects, current_transport, *, inputs_path, inputs_raw, work_root):
    """Internal precheck seam; not an execution admission or independent replay."""
    expected = prior["expected"]
    _validate_expected(expected)
    verifier, gate, data, input_raw = _load_trusted_adapter(prior_adapter,
        prior["approved_inputs_sha256"], Path(prior_adapter) / "verify_phase_a_artifact.py",
        prior["approved_verifier_sha256"])
    overlay_raw = _json_bytes(prior_adapter, "phase-a-overlay-manifest.json")
    require(sha(overlay_raw) == prior["approved_overlay_sha256"],
            "independently approved overlay bytes differ")
    overlay = parse(overlay_raw)
    require(overlay["input_sha256"] == sha(input_raw)
            and overlay["required_single_parent"] == data["owners"]["LiveContainer"]["commit"]
            and overlay["parent_tree"] == data["owners"]["LiveContainer"]["tree"],
            "overlay input/source parent differs")
    raw = {key: _json_bytes(receipts_dir, path) for key, path in RECEIPT_FILES.items() if key != "archive"}
    archive_path = _ordinary(receipts_dir, "artifact.zip")
    files, archive = verifier.read_archive(archive_path)
    # The verifier must parse the same in-memory ZIP bytes it hashes. Bind its
    # digest/size again to the current-run downloaded body without extracting it.
    require(archive_path.stat().st_size <= verifier.MAX_ARCHIVE, "archive too large")
    raw["archive"] = archive_path.read_bytes()
    require(len(raw["archive"]) <= verifier.MAX_ARCHIVE
            and sha(raw["archive"]) == archive["sha256"]
            and len(raw["archive"]) == archive["bytes"], "archive changed during verification")
    retrieval = parse(_json_bytes(receipts_dir, "retrieval-receipts.json"))
    retrieval_hash = _validate_current_transport(current_transport, retrieval, raw, expected,
        helper_raw=_json_bytes(receipts_dir,"retrieval-helper.json"),inputs_path=inputs_path,inputs_raw=inputs_raw,work_root=work_root,receipts_dir=receipts_dir)
    upload_raw = _json_bytes(receipts_dir, "upload-identity.json")
    require(sha(upload_raw)==prior["upload_identity_sha256"],"original upload identity bytes differ from reviewed binding")
    identity = _validate_api(verifier, parse(raw["run_api"]), parse(raw["artifact_api"]),
        parse(raw["commit_api"]), parse(upload_raw), overlay, archive, expected)
    report = verifier.evidence(files, gate, data, input_raw, identity, _SourceRoots(source_objects))
    require(report["complete_capture"] is True and report["successful_workflow"] is True
            and report["capture_status"] == "CAPTURED_FOR_REVIEW",
            "failed or partial Phase A capture cannot supply Phase B")
    require(report["evidence_index_sha256"] == expected["evidence_index_sha256"],
            "approved complete evidence index differs")
    _validate_source_receipts(files, gate, data, source_objects)
    lock = _validate_lock(files, gate, data, source_objects, expected)
    report.update(verification_status="LOCAL_TRANSPORT_SCHEMA_PRECHECK_ONLY",
        execution_replay_reviewed=False, current_run_retrieval_reviewed=False,
        execution_admitted=False,
        current_transport=dict(current_transport), retrieval_receipts_sha256=retrieval_hash,
        input_sha256=sha(input_raw), overlay_manifest_sha256=sha(overlay_raw),
        verifier_sha256=prior["approved_verifier_sha256"], prior_transport=identity,
        api_receipt_sha256={key: sha(value) for key, value in raw.items()},
        upload_identity_sha256=sha(upload_raw))
    return {"lock_bytes": lock, "report": report}


def verify_prior_capture(prior, receipts_dir, prior_adapter, source_objects, current_transport, *, inputs_path=None, inputs_raw=None, work_root=None):
    """Return no lock until both exact success bindings and replay review exist."""
    validate_prior_inputs(prior, execution=True)
    review = _validate_independent_review(_json_bytes(receipts_dir, "independent-review.json"), prior)
    result = _verify_bound_capture(prior, receipts_dir, prior_adapter, source_objects, current_transport, inputs_path=inputs_path, inputs_raw=inputs_raw, work_root=work_root)
    result["report"]["independent_review"] = review
    result["report"]["independent_review_sha256"] = prior["independent_review"]["receipt_sha256"]
    result["report"].update(execution_replay_reviewed=True,current_run_retrieval_reviewed=True,execution_admitted=False,prerequisite_scope="EXACT_PHASE_B_LOCK_INPUT_ONLY")
    return result
