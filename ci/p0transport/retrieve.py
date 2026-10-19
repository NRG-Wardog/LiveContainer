"""Retrieve one existing immutable artifact and split exact bytes; never open its ZIP."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import urllib.parse
import urllib.request

REPOSITORY = 'NRG-Wardog/LiveContainer'
RUN = 39300623354
ATTEMPT = 1
HOST = '1f1230372551c4aa0a4f39d93f58be76a8ee163d'
BRANCH = 'validation/p0-defensive-diagnostic-phase-a'
ARTIFACT = 12211213161
SIZE = 858439882
DIGEST = 'f8037e0d945c14b39c912a2cfbd9661205a278a4ef72aff8c426122db6912260'
PART_SIZE = 256 * 1024 * 1024
API = 'https://api.github.com/repos/' + REPOSITORY


def require(value, message):
    if not value:
        raise ValueError(message)


def validate_api(run, artifact):
    require(type(run['id']) is int and run['id'] == RUN and type(run['run_attempt']) is int and run['run_attempt'] == ATTEMPT, 'run identity')
    require(run['repository']['full_name'] == REPOSITORY and run['head_sha'] == HOST and run['head_branch'] == BRANCH, 'run source identity')
    require(run['path'] == '.github/workflows/p0-defensive-diagnostic-phase-a.yml' and run['event'] == 'push' and run['status'] == 'completed' and run['conclusion'] == 'failure', 'exact completed failed diagnostic capture required')
    require(type(artifact['id']) is int and artifact['id'] == ARTIFACT and type(artifact['size_in_bytes']) is int and artifact['size_in_bytes'] == SIZE, 'artifact identity')
    require(artifact['digest'] == 'sha256:' + DIGEST and artifact['expired'] is False, 'artifact hash/expiry')
    require(artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == HOST and artifact['workflow_run']['head_branch'] == BRANCH, 'artifact run binding')
    require(artifact['name'] == 'p0-defensive-diagnostic-phase-a-' + HOST + '-' + str(RUN) + '-1', 'artifact name')


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        require(target.scheme == 'https' and target.hostname and not target.username and not target.password and target.port in (None, 443), 'HTTPS artifact redirect required')
        require(target.hostname == 'api.github.com' or target.hostname.endswith('.blob.core.windows.net'), 'unapproved artifact redirect host')
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if target.hostname != 'api.github.com':
            result.remove_header('Authorization')
        return result


def download(stream, destination, expected_size=SIZE, expected_digest=DIGEST):
    digest = hashlib.sha256(); count = 0
    with destination.open('xb') as output:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            require(count <= expected_size, 'original archive exceeded exact size')
            output.write(chunk); digest.update(chunk)
    require(count == expected_size and digest.hexdigest() == expected_digest, 'original archive byte identity differs')


def split(source, output, expected_size=SIZE, expected_digest=DIGEST, part_size=PART_SIZE):
    require(not output.exists() and not output.is_symlink() and output.parent.resolve() == output.parent, 'fresh canonical part directory required')
    before = source.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == expected_size, 'ordinary exact archive required')
    output.mkdir(); rows = []; whole = hashlib.sha256(); count = 0
    with source.open('rb') as original:
        while True:
            raw = original.read(part_size)
            if not raw:
                break
            name = 'part-' + str(len(rows)).zfill(2) + '.bin'
            (output / name).write_bytes(raw)
            rows.append({'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            whole.update(raw); count += len(raw)
            require(count <= expected_size and len(rows) <= 4, 'part bounds')
    after = source.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'archive changed while splitting')
    require(count == expected_size and whole.hexdigest() == expected_digest, 'reassembled original bytes differ')
    return rows


def main():
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and os.environ.get('GITHUB_REF') == 'refs/heads/validation/p0-defensive-diagnostic-artifact-transport', 'exact retrieval-only branch required')
    token = os.environ.pop('GH_TOKEN', '')
    require(bool(token) and '\n' not in token and '\r' not in token, 'ephemeral GitHub token required')
    opener = urllib.request.build_opener(SafeRedirect())
    def get(path):
        require(path in ('/actions/runs/' + str(RUN), '/actions/artifacts/' + str(ARTIFACT), '/actions/artifacts/' + str(ARTIFACT) + '/zip'), 'fixed read-only endpoint required')
        request = urllib.request.Request(API + path, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        return opener.open(request, timeout=60)
    def api(path):
        with get(path) as response:
            raw = response.read(1024 * 1024 + 1)
        require(len(raw) <= 1024 * 1024, 'API size bound')
        return raw, json.loads(raw)
    run_raw, run = api('/actions/runs/' + str(RUN))
    artifact_raw, artifact = api('/actions/artifacts/' + str(ARTIFACT))
    validate_api(run, artifact)
    source = Path.cwd() / 'original-artifact.zip'
    with get('/actions/artifacts/' + str(ARTIFACT) + '/zip') as response:
        download(response, source)
    output = Path.cwd() / 'parts'
    rows = split(source, output)
    require(len(rows) == 4, 'exact four original byte parts required')
    receipt = {'schema': 'original-artifact-byte-transport-v1', 'original_repository': REPOSITORY, 'original_run': RUN, 'original_attempt': ATTEMPT, 'original_conclusion': 'failure', 'original_workflow': '.github/workflows/p0-defensive-diagnostic-phase-a.yml', 'original_host': HOST, 'original_artifact': ARTIFACT, 'original_bytes': SIZE, 'original_sha256': DIGEST, 'parts': rows, 'archive_opened': False, 'artifact_code_executed': False, 'tests_or_builds_repeated': False}
    (output / 'transport-manifest.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    (output / 'original-run-api.json').write_bytes(run_raw)
    (output / 'original-artifact-api.json').write_bytes(artifact_raw)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
