#!/usr/bin/env python3
"""Source-only checks plus owned synthetic wire fixtures. Never imports/runs repository code."""
from pathlib import Path
import argparse, base64, hashlib, json, os, re, subprocess, sys, uuid
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, default=Path(os.environ.get('PR1835_SOURCE_ROOT', Path(__file__).resolve().parents[1])))
parser.add_argument('--baseline-root', type=Path, default=Path(os.environ.get('PR1835_BASELINE_ROOT', '/workspace/shared/upstream-sync/exact-error-consumer-sources')))
for name in ['sidestore', 'sidesign', 'anisettekit']:
    parser.add_argument('--'+name+'-root', type=Path)
args = parser.parse_args()
ROOT, BASE = args.source_root, args.baseline_root
BASE_REFS = {'SideStore': '28dd1f873cad2e12e1c07cacb80ac9685560e02c',
             'SideSign': '9757970d656135f0b21dc00700507d099f170320',
             'AnisetteKit': '3e670c2e1b72ff328d3a64353d8de2418df87e73'}
def locate(root, repo):
    candidates = [root/repo]
    if repo == 'SideSign': candidates += [root/'SideStore/Dependencies/SideSign']
    if repo == 'AnisetteKit': candidates += [root/'SideStore/Dependencies/SideSign/.build/checkouts/AnisetteKit']
    return next((path for path in candidates if path.is_dir()), candidates[0])
def read(repo, path):
    selected = getattr(args, repo.lower()+'_root') or locate(ROOT, repo)
    return (selected/path).read_text()
def exact(repo, path):
    return subprocess.check_output(['git','-C',str(locate(BASE, repo)),'show',BASE_REFS[repo]+':'+path]).decode()
def require(condition, message):
    if not condition: raise AssertionError(message)

core = read('SideSign','Sources/Anisette/WindowsRemoteAnisette.swift')
provider = read('SideStore','SideStore/Core/Anisette/AnisetteProvider.swift')
operation = read('SideStore','SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift')
keychain = read('SideStore','AltStore/Core/Components/Keychain.swift')
ak = read('AnisetteKit','Sources/AnisetteClient.swift')
require('case jkcoxson = "https://ani.jkcoxson.com"' in core and 'case stikstore = "https://ani2.stikstore.app"' in core, 'exact provider allowlist')
require('case .remote' not in core and 'URLSession.shared' not in core, 'no legacy remote route or shared transport')
require('completionHandler(nil)' in core, 'redirects refused')
require('configuration.httpCookieStorage = nil' in core and 'configuration.httpShouldSetCookies = false' in core, 'no provider cookies')
require('response.client_info.contains("<Windows;")' in core, 'Windows metadata guard')
require('response.client_info.utf8.count <= 4096' in core and 'response.user_agent.utf8.count <= 4096' in core, 'metadata bounds')
require('!response.client_info.contains("\\r")' in core and '!response.user_agent.contains("\\n")' in core, 'no CRLF metadata')
require('identity.base64EncodedString()' in core and 'String(format: "%02X", $0)' in core, 'exact identity encodings')
require('"adi_pb": adiPB' in core and 'return Data(blob.utf8)' in core, 'opaque blob no extra base64')
require('body["sim"] = sim; body["device_id"] = deviceID.uuidString; body["md_lu"] = localUserID' in core, 'resync same identity')
require('guard !invalidated, !didResynchronize' in core and core.index('didResynchronize = true') < core.index('let data = try await fetcher(sim)'), 'one resync reservation before await')
require('public func invalidate()' in core and 'try requireActive()' in core, 'revocable context')
require('defer { windowsAnisetteContext?.invalidate() }' in operation and 'override func cancel()' in operation, 'operation revokes on exit and cancel')
require('WindowsAnisetteAuthentication.$current.withValue(windowsAnisetteContext)' in operation, 'operation-installed task-local')
require('windowsAnisetteEndpoint: String? = nil' in operation and 'windowsAnisetteConsentAttemptID: UUID? = nil' in operation, 'default-off initializer')
require('if endpoint == nil && consentAttemptID == nil { return nil }' in provider, 'default-off factory')
require('guard !fetching' in provider, 'actor reentrancy admission')
require('candidate.adiPB == nil { throw WindowsAnisetteError.invalidState }' in provider, 'no silent repair of stored incomplete record')
require('guard try client.getData(key) == previous' in keychain and 'guard try client.getData(key) == data' in keychain, 'atomic compare and read-back')
# Existing local/legacy resolver and commit function stay byte-for-byte unchanged.
old = exact('SideStore','AltStore/Core/Components/Keychain.swift')
for a,b in [('    static func resolveAnisetteSnapshot(', '    private static func legacyAnisetteItems()')]:
    require(old[old.index(a):old.index(b)] == keychain[keychain.index(a):keychain.index(b)], 'baseline pair resolver/commit changed')
old_provider = exact('SideStore','SideStore/Core/Anisette/AnisetteProvider.swift')
a='    private static func fetchRemote('
require(provider[provider.index(a):provider.index('\n}\n',provider.index(a))+3] == old_provider[old_provider.index(a):], 'baseline remote fetch changed')
require('requestSession: URLSession = .shared' in ak and 'provisioningURLValidator: (@Sendable (URL, String) -> Bool)? = nil' in ak and 'provisioningHeaderPolicy: AnisetteProvisioningHeaderPolicy = .standard' in ak, 'baseline AK default values')
require('!validate(req.url ?? lookupURL, step)' in ak and ak.index('!validate(req.url ?? lookupURL, step)') < ak.index('requestSession.data(for: req)'), 'recipient validation before network')
require('destinations[step] == url.absoluteString' in core and 'hasSuffix(".apple.com")' not in core, 'exact role-specific Apple recipient')
# Synthetic data alone, no real keys, ADI, credentials or device pairing data.
identity=bytes(range(16))
fixture={'identifier':base64.b64encode(identity).decode(),'adi_pb':'ZmFrZS1ibG9i=='}
require(fixture['identifier']=='AAECAwQFBgcICQoLDA0ODw==','Base64 identity fixture')
require(str(uuid.UUID(bytes=identity)).upper()=='00010203-0405-0607-0809-0A0B0C0D0E0F','UUID identity fixture')
require(hashlib.sha256(identity).hexdigest().upper()=='BE45CB2605BF36BEBDE684841A28F0FD43C69850A3DCE5FEDBA69928EE3A8991','LU fixture')
require(json.loads(json.dumps(fixture))['adi_pb']==fixture['adi_pb'],'opaque blob fixture')
print('PASS: 27 source invariants and synthetic wire-identity fixtures. Swift compilation/runtime tests NOT run locally.')
