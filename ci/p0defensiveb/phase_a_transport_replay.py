"""Current-run owned authenticated GET receipt verification."""
import os,sys,json
from pathlib import Path
from phase_a_raw_replay import require,sha,parse
REPOSITORY="NRG-Wardog/LiveContainer"
PHASE_B_REF="refs/heads/validation/p0-defensive-diagnostic-phase-b"
def _positive(value):
    require(type(value) is int and value>0,"positive integer required");return value
def _git_sha(value):
    from prior_phase_a import _git_sha
    return _git_sha(value)
def _digest(value):
    from prior_phase_a import _digest
    return _digest(value)
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
            type(receipts["schema_version"]) is int and receipts["schema_version"]==1 and json.dumps(receipts["current_run"],sort_keys=True)==json.dumps(current,sort_keys=True),
            "unexpected outer retrieval receipt schema")
    require(sha(helper_raw)==receipts["helper_report_sha256"],"helper report bytes changed")
    report=parse(helper_raw)
    require(set(report)=={"schema_version","status","execution_admitted","current_run","expected","inputs","helper","limits","request_order","requests"},"unexpected helper report schema")
    require(type(report["schema_version"]) is int and report["schema_version"]==1 and report["status"]=="RETRIEVED_UNSETTLED" and report["execution_admitted"] is False and
            json.dumps(report["current_run"],sort_keys=True)==json.dumps(current,sort_keys=True) and json.dumps(report["expected"],sort_keys=True)==json.dumps(expected,sort_keys=True),"wrong helper capture identity")
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
    expected_env={"PATH":"/opt/homebrew/bin:/Users/runner/.cargo/bin:/usr/bin:/bin:/usr/sbin:/sbin","HOME":str(work_root/"home"),"TMPDIR":str(work_root/"tmp"),"DEVELOPER_DIR":"/Applications/Xcode_26.4.1.app/Contents/Developer","PYTHONDONTWRITEBYTECODE":"1","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null","GIT_ALLOW_PROTOCOL":"https","GIT_NO_REPLACE_OBJECTS":"1","GIT_GRAFT_FILE":"/dev/null","GIT_NO_LAZY_FETCH":"1","GIT_TERMINAL_PROMPT":"0"}
    expected_env.update(LANG="en_US.UTF-8",LC_ALL="en_US.UTF-8",GITHUB_REPOSITORY=current["repository"],GITHUB_SHA=current["host_commit"],GITHUB_RUN_ID=str(current["run_id"]),GITHUB_RUN_ATTEMPT=str(current["run_attempt"]),GITHUB_REF=PHASE_B_REF)
    require(command["environment"]==expected_env,"outer retrieval finite environment differs")
    settled=receipts["outer_settlement"];owned=settled.get("ownedProcessGroup",{})
    require(set(settled)=={"returncode","timeout_seconds","ownedProcessGroup","terminationReturncode"} and type(settled["timeout_seconds"]) in (int,float) and 0<settled["timeout_seconds"]<=1800,"outer retrieval settlement shape/timeout differs")
    require(set(owned)=={"pgid","quiescent","pipesJoined","signals","identityRetainedForSignals","reapedBeforeSignals","postReapPolicy","errors","leaderReaped"} and owned["identityRetainedForSignals"] is False and owned["reapedBeforeSignals"] is True,"outer retrieval process ownership differs")
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
        require(row["sha256"]==raw_inputs[key]["sha256"] and type(row["bytes"]) is int and row["bytes"]==raw_inputs[key]["bytes"],"retrieval response bytes changed")
        nested=row["command"]
        require(set(nested)=={"argv","cwd","returncode","pid","pgid","leaderReaped","pipesJoined"} and
            nested["argv"]==["gh","api","--method","GET","--include",url] and nested["cwd"]==str(receipts_dir) and
            type(nested["returncode"]) is int and nested["returncode"]==0 and nested["pgid"]==identity["pgid"] and
            nested["leaderReaped"] is True and nested["pipesJoined"] is True,"nested GET command/lifecycle differs")
        _positive(nested["pid"]);require(nested["pid"]!=identity["pid"],"nested command identity aliases helper")
        require(set(row["headers"])<=helper.SAFE_HEADERS,"unsafe retained HTTP header")
        require(row["stderr"]=={"sha256":sha(b""),"bytes":0} and type(row["stderr"]["bytes"]) is int,"successful retrieval stderr must be empty")
        require(type(row["stdout"].get("bytes")) is int and raw_inputs[key]["bytes"]<row["stdout"]["bytes"],"HTTP header bytes absent from stdout receipt")
        for stream,limit in (("stdout",raw_inputs[key]["bytes"]+helper.MAX_HEADERS),("stderr",helper.MAX_STDERR)):
            record=row[stream];require(set(record)=={"sha256","bytes"} and type(record["bytes"]) is int and 0<=record["bytes"]<=limit,"invalid raw stream digest record");_digest(record["sha256"])
    return sha(json.dumps(receipts,sort_keys=True,separators=(",",":")).encode())

