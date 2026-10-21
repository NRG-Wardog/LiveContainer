#!/usr/bin/env python3
"""Extract actual Swift production fragments into a no-network CI fixture.

Run this Python locally, but compile/run the generated Swift only in the approved
fake-only CI stage. The URLSession type is replaced by an in-memory transport;
SRPClient is a deterministic fake. No native library, real endpoint, identity,
credential, ADI state, or provisioning implementation enters the executable.
"""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
arguments = argparse.ArgumentParser(description=__doc__)
arguments.add_argument('--baseline', type=Path, default=ROOT / 'auth-tests/Authentication.baseline.swift')
arguments.add_argument('--auth', type=Path, default=ROOT / 'implementation/SideSign/Sources/DeveloperPortal/Authentication.swift')
arguments.add_argument('--core', type=Path, default=ROOT / 'implementation/SideSign/Sources/Anisette/WindowsRemoteAnisette.swift')
arguments.add_argument('--output', type=Path, default=ROOT / 'auth-tests/AuthenticationFixture.swift')
arguments.add_argument('--manifest', type=Path, default=ROOT / 'auth-tests/fixture-manifest.json')
ARGS = arguments.parse_args()
BASELINE_SHA256 = 'ce5bc5c16552a3f5fda370a7f301ec973be3f3f81b0221c6c3257befe60a2849'
assert hashlib.sha256(ARGS.baseline.read_bytes()).hexdigest() == BASELINE_SHA256, 'Exact reviewed SideSign base required'
OLD = ARGS.baseline.read_text()
NEW_PATH = ARGS.auth
NEW = NEW_PATH.read_text()
CORE_PATH = ARGS.core
CORE = CORE_PATH.read_text()


def between(source, begin, end):
    assert source.count(begin) == 1, begin
    return begin + source.split(begin, 1)[1].split(end, 1)[0]


def portal(source, name, experimental):
    init = between(source, '            let sanitizedAppleID =', '            guard let c = initResponse')
    request = between(source, '    func sendAuthenticationRequest(',
                      '    private func parseWindowsAuthenticationResponse' if experimental else '    private struct FetchedAuthToken')
    twofa = between(source, '    private func makeTwoFactorAuthRequest(', '    private func parsePlistOrJSON')
    parser = between(source, '    private func parsePlistOrJSON(', '\n}')
    auth_type = between(source, '            let statusDictionary = completeResponseDictionary', '            let twoFactorAuthContext =')
    additions = ''
    if experimental:
        additions = between(source, '    private func makeWindowsClientDictionary(', '    func sendAuthenticationRequest(')
        additions += between(source, '    private func parseWindowsAuthenticationResponse(', '    private struct FetchedAuthToken')
    return f'''
final class {name}: @unchecked Sendable {{
    let session: URLSession
    let customHeaders = FixtureHeaders()
    init(session: URLSession = URLSession()) {{ self.session = session }}
    func begin(appleID unsanitizedAppleID: String, anisetteData: AnisetteData) async throws -> AnisetteData {{
{init}
        return anisetteData
    }}
    func authType(_ completeResponseDictionary: [String: any Sendable]) -> String? {{
        let windowsContext = WindowsAnisetteAuthentication.current
{auth_type}
        return authType
    }}
    func twoFactor(_ data: AnisetteData) -> URLRequest {{
        makeTwoFactorAuthRequest(url: Constants.URLs.grandSlamAuth,
            context: TwoFactorAuthContext(dsid: "synthetic-dsid", idmsToken: "synthetic-token", anisetteData: data, xcodeVersion: "fixture-xcode"))
    }}
{additions}
{request}
{twofa}
{parser}
}}
'''


PREAMBLE = r'''
// GENERATED from exact source fragments. Do not edit this generated file.
// CI only: swiftc -swift-version 6 -parse-as-library AuthenticationFixture.swift -o authentication-fixture
// Every transport is in-memory. URLSession below is NOT Foundation.URLSession.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public typealias URLSession = FixtureTransport
public struct AnisetteData: Sendable, Equatable {
    var machineID = "synthetic-machine"
    var oneTimePassword = "synthetic-otp-initial"
    var localUserID = "synthetic-lu"
    var routingInfo = "17106176"
    var deviceID = "00000000-0000-0000-0000-000000000000"
    var serialNumber = "synthetic-serial"
    var clientInfo = "<Windows;synthetic-fixture>"
    var userAgent = "synthetic-provider-agent"
    var clientTime = "2026-01-01T00:00:00Z"
    var locale = "en_US"
    var timeZone = "UTC"
}
struct FixtureHeaders {
    struct GrandSlam { var service = "fixture-service"; var headerVersion = "fixture-version"; var userAgent = "fixture-gsa-agent"; var authApp = "fixture-app" }
    struct DeveloperServices { var userAgent = "fixture-developer-agent" }
    var grandSlam = GrandSlam()
    var developerServices = DeveloperServices()
}
enum Constants { enum URLs { static let grandSlamAuth = URL(string: "https://fixture.invalid/auth")! } }
enum GrandSlamAuthErrorCodes {
    static let incorrectCredentials = -20101
    static let appSpecificPasswordRequired = -22938
    static let appSpecificPasswordRequiredFallback = -22939
    static let incorrectVerificationCode = -21669
}
enum DeveloperPortalError: Error {
    case authenticationHandshakeFailed(cause: String)
    case incorrectCredentials(cause: String?)
    case appSpecificPasswordRequired(cause: String?)
    case incorrectVerificationCode(cause: String?)
}
enum ServerError: Error {
    case badServerResponse(reason: String, jsonPayload: String)
    case invalidResponseFormat(rawPayload: String, responseContext: AuthenticationResponseContext? = nil)
    case missingKey(key: String, jsonPayload: String)
    case underlyingError(code: Int, message: String)
}
struct AuthenticationResponseContext: Sendable {
    init(data: Data, httpStatus: Int, mimeType: String?) {}
}
enum WindowsAnisetteError: Error { case consentRequired, resyncUnavailable, httpStatus(Int) }
public enum WindowsAnisetteEndpoint: String, Sendable { case jkcoxson = "synthetic-provider-one", stikstore = "synthetic-provider-two" }
enum WindowsAnisetteAuthentication { @TaskLocal static var current: WindowsAnisetteAuthenticationContext? }
enum WindowsAnisetteTransport { static func makeSession() -> URLSession { URLSession() } }
func prettyJSONString(from value: Any) -> String { "[synthetic-fixture]" }
struct TwoFactorAuthContext {
    let dsid: String; let idmsToken: String; let anisetteData: AnisetteData; let xcodeVersion: String
}
final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var value = 0
    private var strings: [String] = []
    var count: Int { lock.withLock { value } }
    var values: [String] { lock.withLock { strings } }
    func record(_ string: String = "") { lock.withLock { value += 1; strings.append(string) } }
}
final class SRPClient {
    static let starts = Counter()
    init?() {}
    func startAuthentication() -> Data? { Self.starts.record(); return Data([0x01, 0x02, 0x03, 0x04]) }
}
struct FixtureReply: Sendable { let status: Int; let body: Data }
enum FixtureFailure: Error { case assertion(String), unscriptedRequest }
public final class FixtureTransport: @unchecked Sendable {
    private let lock = NSLock()
    private var replies: [FixtureReply] = []
    private var captured: [URLRequest] = []
    private var cancelled = false
    var requests: [URLRequest] { lock.withLock { captured } }
    func enqueue(_ new: [FixtureReply]) { lock.withLock { replies += new } }
    func invalidateAndCancel() { lock.withLock { cancelled = true } }
    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        try Task.checkCancellation()
        return try lock.withLock {
            guard !cancelled else { throw CancellationError() }
            guard !replies.isEmpty else { throw FixtureFailure.unscriptedRequest }
            captured.append(request)
            let reply = replies.removeFirst()
            let response = HTTPURLResponse(url: Constants.URLs.grandSlamAuth, statusCode: reply.status,
                httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "text/x-xml-plist"])!
            return (reply.body, response)
        }
    }
}
func expect(_ condition: @autoclosure () -> Bool, _ description: String) throws {
    guard condition() else { throw FixtureFailure.assertion(description) }
}
func plist(_ value: [String: any Sendable]) throws -> Data {
    try PropertyListSerialization.data(fromPropertyList: value, format: .xml, options: 0)
}
func reply(_ status: [String: any Sendable]) throws -> FixtureReply {
    FixtureReply(status: 200, body: try plist(["Response": ["Status": status]]))
}
func body(_ request: URLRequest) throws -> [String: Any] {
    guard let data = request.httpBody,
          let envelope = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
          let result = envelope["Request"] as? [String: Any] else { throw FixtureFailure.assertion("request body") }
    return result
}
'''

TESTS = r'''
@main struct AuthenticationFixture {
    static func main() async throws {
        let initial = AnisetteData()
        var changed = initial
        changed.oneTimePassword = "synthetic-otp-resynchronized"
        changed.machineID = "synthetic-machine-resynchronized"
        let fresh = changed

        // Actual baseline and modified init/request fragments, identical fake SRP A.
        let baseline = BaselinePortal()
        let modified = AdaptedPortal()
        baseline.session.enqueue([try reply(["ec": 0])])
        modified.session.enqueue([try reply(["ec": 0])])
        _ = try await baseline.begin(appleID: " FIXTURE@INVALID.EXAMPLE ", anisetteData: initial)
        _ = try await modified.begin(appleID: " FIXTURE@INVALID.EXAMPLE ", anisetteData: initial)
        let oldRequest = baseline.session.requests[0]
        let newRequest = modified.session.requests[0]
        try expect(oldRequest.httpBody == newRequest.httpBody, "nil-context init XML bytes changed")
        try expect(oldRequest.allHTTPHeaderFields == newRequest.allHTTPHeaderFields, "nil-context headers changed")
        let legacyBody = try body(newRequest)
        let legacyCPD = legacyBody["cpd"] as! [String: Any]
        try expect(legacyCPD["bootstrap"] as? Bool == true && !(legacyCPD["bootstrap"] is String), "legacy flags must remain boolean")
        try expect(baseline.twoFactor(initial).allHTTPHeaderFields == modified.twoFactor(initial).allHTTPHeaderFields,
                   "nil-context 2FA headers changed")
        for operation in ["complete", "apptokens"] {
            let parameters: [String: any Sendable] = ["o": operation, "cpd": ["bootstrap": true], "c": Data([1,2]), "u": "synthetic-user"]
            baseline.session.enqueue([try reply(["ec": 0])])
            modified.session.enqueue([try reply(["ec": 0])])
            _ = try await baseline.sendAuthenticationRequest(parameters: parameters, anisetteData: initial)
            _ = try await modified.sendAuthenticationRequest(parameters: parameters, anisetteData: initial)
            try expect(baseline.session.requests.last!.httpBody == modified.session.requests.last!.httpBody, "nil-context \(operation) bytes changed")
            try expect(baseline.session.requests.last!.allHTTPHeaderFields == modified.session.requests.last!.allHTTPHeaderFields, "nil-context \(operation) headers changed")
        }

        // Exact production init resync flow + production context budget, fake transport only.
        let called = Counter()
        let context = WindowsAnisetteAuthenticationContext { sim in
            called.record(sim ?? "nil")
            return fresh
        }
        let remote = AdaptedPortal()
        context.session.enqueue([try reply(["hsc": 434, "ec": -80045, "X-Apple-I-MD-DATA": Data([0x11, 0x22])]), try reply(["ec": 0])])
        let before = SRPClient.starts.count
        try await WindowsAnisetteAuthentication.$current.withValue(context) {
            let result = try await remote.begin(appleID: "fixture@invalid.example", anisetteData: initial)
            try expect(result == fresh, "resynchronized data was not propagated")
            try expect(remote.session.requests.isEmpty, "remote path used baseline session")
            let requests = context.session.requests
            try expect(requests.count == 2, "resync request count")
            let first = try body(requests[0]); let second = try body(requests[1])
            try expect(first["A2k"] as? Data == second["A2k"] as? Data, "A2k changed on resync")
            try expect(SRPClient.starts.count == before + 1, "SRP restarted during resync")
            let cpd = second["cpd"] as! [String: Any]
            let expectedKeys: Set<String> = ["bootstrap", "icscrec", "pbe", "prkgen", "svct", "loc", "X-Apple-I-MD", "X-Apple-I-MD-M", "X-Mme-Device-Id"]
            try expect(Set(cpd.keys) == expectedKeys, "Windows CPD is not exactly nine fields")
            for (key, value) in ["bootstrap":"true", "icscrec":"true", "pbe":"false", "prkgen":"true", "svct":"iCloud", "loc":"en_US"] {
                try expect(cpd[key] as? String == value, "Windows CPD field/type \(key)")
            }
            try expect(cpd["X-Apple-I-MD"] as? String == fresh.oneTimePassword, "resync OTP missing from CPD")
            try expect(cpd["X-Apple-I-MD-M"] as? String == fresh.machineID, "resync machine missing from CPD")
            let request = requests[1]
            try expect(request.value(forHTTPHeaderField: "User-Agent") == fresh.userAgent, "provider UA")
            try expect(request.value(forHTTPHeaderField: "X-MMe-Client-Info") == fresh.clientInfo, "provider client info")
            try expect(request.value(forHTTPHeaderField: "Accept") == "text/x-xml-plist", "GSA Accept")
            try expect(request.value(forHTTPHeaderField: "X-Xcode-Version") == "27.0 (27A5218g)", "GSA Xcode")
            try expect(request.value(forHTTPHeaderField: "X-Apple-App-Info") == "com.apple.gs.xcode.auth", "GSA app info")
            let twofa = remote.twoFactor(fresh)
            try expect(twofa.value(forHTTPHeaderField: "User-Agent") == fresh.userAgent, "2FA UA")
            try expect(twofa.value(forHTTPHeaderField: "X-Apple-I-MD") == fresh.oneTimePassword, "2FA latest OTP")
            try expect(twofa.value(forHTTPHeaderField: "X-Apple-I-SRL-NO") == nil, "2FA serial removed")
            try expect(remote.authType(["Status": ["hsc": 409]]) == "pushedCode", "missing au 409")
            try expect(remote.authType(["Status": ["hsc": 409, "au": ""]]) == "pushedCode", "empty au 409")
            try expect(remote.authType(["Status": ["hsc": 409, "au": "sms"]]) == "sms", "nonempty au precedence")
            // A recursive auth attempt inherits the same context and cannot resync again.
            context.session.enqueue([try reply(["hsc": 434, "X-Apple-I-MD-DATA": "synthetic-sim-second")])
            do {
                _ = try await remote.begin(appleID: "fixture@invalid.example", anisetteData: fresh)
                throw FixtureFailure.assertion("second operation resync accepted")
            } catch WindowsAnisetteError.resyncUnavailable {}
        }
        try expect(called.count == 1 && called.values == ["ESI="], "SIM Data base64 / one-budget")

        let malformedStatuses: [[String: any Sendable]] = [["hsc": 434], ["hsc": 434, "X-Apple-I-MD-DATA": ""], ["hsc": 434, "X-Apple-I-MD-DATA": 123]]
        for malformed in malformedStatuses {
            let counter = Counter()
            let context = WindowsAnisetteAuthenticationContext { _ in counter.record(); return fresh }
            context.session.enqueue([try reply(malformed)])
            do {
                _ = try await WindowsAnisetteAuthentication.$current.withValue(context) {
                    try await AdaptedPortal().begin(appleID: "fixture@invalid.example", anisetteData: initial)
                }
                throw FixtureFailure.assertion("malformed SIM accepted")
            } catch WindowsAnisetteError.resyncUnavailable {}
            try expect(counter.count == 0 && context.session.requests.count == 1, "malformed SIM caused retry")
        }

        let repeatedCalls = Counter()
        let repeated = WindowsAnisetteAuthenticationContext { sim in repeatedCalls.record(sim ?? "nil"); return fresh }
        repeated.session.enqueue([try reply(["hsc": 434, "X-Apple-I-MD-DATA": "synthetic-sim"]), try reply(["hsc": 434, "X-Apple-I-MD-DATA": "synthetic-repeat"])])
        do {
            _ = try await WindowsAnisetteAuthentication.$current.withValue(repeated) {
                try await AdaptedPortal().begin(appleID: "fixture@invalid.example", anisetteData: initial)
            }
            throw FixtureFailure.assertion("repeated 434 accepted")
        } catch WindowsAnisetteError.resyncUnavailable {}
        try expect(repeatedCalls.values == ["synthetic-sim"] && repeated.session.requests.count == 2, "repeated 434 was retried")

        let cancelled = WindowsAnisetteAuthenticationContext { _ in throw CancellationError() }
        cancelled.session.enqueue([try reply(["hsc": 434, "X-Apple-I-MD-DATA": "synthetic-sim"])])
        do {
            _ = try await WindowsAnisetteAuthentication.$current.withValue(cancelled) {
                try await AdaptedPortal().begin(appleID: "fixture@invalid.example", anisetteData: initial)
            }
            throw FixtureFailure.assertion("cancelled resync accepted")
        } catch is CancellationError {}
        try expect(cancelled.session.requests.count == 1, "cancellation caused retry")

        let invalid = WindowsAnisetteAuthenticationContext { _ in fresh }
        invalid.session.enqueue([
            FixtureReply(status: 503, body: Data("<html>synthetic error</html>".utf8)),
            FixtureReply(status: 200, body: Data("{\"Response\":{\"Status\":{\"ec\":0}}}".utf8)),
            FixtureReply(status: 200, body: try plist(["Status": ["ec": 0]])),
            try reply(["hsc": 434, "X-Apple-I-MD-DATA": "synthetic-late"]),
            try reply(["ec": -80045, "em": "synthetic rejection"]),
        ])
        try await WindowsAnisetteAuthentication.$current.withValue(invalid) {
            let portal = AdaptedPortal()
            do { _ = try await portal.sendAuthenticationRequest(parameters: ["o":"init"], anisetteData: initial); throw FixtureFailure.assertion("HTTP error parsed") }
            catch WindowsAnisetteError.httpStatus(let status) { try expect(status == 503, "wrong HTTP status") }
            for _ in 0..<2 {
                do { _ = try await portal.sendAuthenticationRequest(parameters: ["o":"init"], anisetteData: initial); throw FixtureFailure.assertion("invalid envelope accepted") }
                catch ServerError.invalidResponseFormat(let raw, _) { try expect(raw == "[redacted]", "unredacted parser error") }
            }
            do { _ = try await portal.sendAuthenticationRequest(parameters: ["o":"complete"], anisetteData: initial); throw FixtureFailure.assertion("late resync accepted") }
            catch WindowsAnisetteError.resyncUnavailable {}
            do { _ = try await portal.sendAuthenticationRequest(parameters: ["o":"init"], anisetteData: initial); throw FixtureFailure.assertion("80045 was retried") }
            catch ServerError.underlyingError(let code, _) { try expect(code == -80045, "wrong server error") }
            try expect(invalid.session.requests.count == 5, "unexpected generic retry")
        }
        // Nil-context behavior of empty au is intentionally unchanged.
        try expect(modified.authType(["Status": ["hsc":409, "au":""]]) == baseline.authType(["Status": ["hsc":409, "au":""]]), "nil-context au behavior changed")
        print("PASS: actual-source fake request bytes, CPD field types, headers, resync budget/A2k, cancellation, strict parsing, and 409 semantics")
    }
}
'''

context = between(CORE, 'public final class WindowsAnisetteAuthenticationContext:', '\nprivate final class WindowsAnisetteTransport:')
output = PREAMBLE + '\n' + context + portal(OLD, 'BaselinePortal', False) + portal(NEW, 'AdaptedPortal', True) + TESTS
# Hard boundaries: all endpoint literals are synthetic; real transport is absent.
assert 'Foundation.URLSession(' not in output
assert '.apple.com' not in output
assert 'URLSessionConfiguration' not in output
assert output.count('func data(for request: URLRequest)') == 1
assert 'let publicKey = srpClient.startAuthentication()' in output
destination = ARGS.output
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(output)
manifest = {
    'baseline_sha256': BASELINE_SHA256,
    'source_sha256': hashlib.sha256(NEW_PATH.read_bytes()).hexdigest(),
    'core_sha256': hashlib.sha256(CORE_PATH.read_bytes()).hexdigest(),
    'fixture_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
    'fixture': str(destination),
    'execution': 'Generated only. Not compiled or executed locally. Root must run fake-only CI.',
    'transport': 'URLSession is a fixture typealias to in-memory FixtureTransport; no network implementation.',
}
ARGS.manifest.parent.mkdir(parents=True, exist_ok=True)
ARGS.manifest.write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
