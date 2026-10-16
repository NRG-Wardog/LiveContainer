"""Pending certificate recovery is independently visible and owner-gated."""
import os
import json
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOST_ROOT = Path(os.environ.get("MAINTAINED_LIVE_CONTAINER_TEST_SOURCE", ROOT))
HOST = Path(os.environ.get("V3_PENDING_HOST_SOURCE", HOST_ROOT / "LiveContainerSwiftUI/Views/V3UnifiedShell.swift"))
SOURCE = HOST.read_text()
WIRE = (HOST.parents[2] / "SideStoreSupport/SideStore.swift").read_text()


def region(start, end):
    return SOURCE[SOURCE.index(start):SOURCE.index(end, SOURCE.index(start))]


class PendingCertificateHostRecoveryTests(unittest.TestCase):
    def test_distinct_capability_is_decoded_in_account_and_auth_snapshots(self):
        self.assertEqual(SOURCE.count('protocolVersion: V3ServiceBridge.strictInt(snapshot["pendingCertificateRecoveryProtocol"])'), 2)
        self.assertEqual(SOURCE.count('rawState: snapshot["pendingCertificateRecoveryState"] as? String)'), 2)
        admission = region('    var canBegin: Bool {', '    private func clearProvisioningOutcome()')
        self.assertNotIn('pendingCertificateRecovery', admission)
        self.assertIn('guard !provisioningRecoveryRequiresReconciliation', admission)
        helper = HOST.parents[2] / "LiveContainerSwiftUI/Utilities/V3Localization.swift"
        if not helper.exists():
            for adapter in ('V3LocalizedText', 'V3LocalizedLabel', 'V3AppLanguage', 'V3LanguageSettingsSection'):
                self.assertNotIn(adapter, SOURCE, "P0 must not reference unavailable P2 adapters")

    def test_recovery_route_survives_signout_and_has_an_explicit_owner_bound_action(self):
        account = region('struct V3AccountSettings:', 'struct V3OperationSheet:')
        pending = account[account.index('if status.pendingCertificateRecoveryState.requiresAttention'):]
        self.assertIn('V3SignInView().environmentObject(status)', pending)
        self.assertLess(account.index('account.pending-certificate-recovery'), account.index('if !status.needsSignIn'))
        self.assertIn('status.signOut()', account)
        prompt = region('struct V3SignInView:', 'struct V3CertificateRow')
        pending = prompt[prompt.index('if auth.pendingCertificateRecoveryState.requiresAttention'):prompt.index('if auth.provisioningRecoveryRequiresReconciliation')]
        self.assertIn('auth.pendingCertificateRecoveryState == .ready', pending)
        self.assertIn('.disabled(!auth.canCheckPendingCertificateRecovery)', pending)
        self.assertIn('auth.checkProvisioningStorage()', pending)
        self.assertIn('auth.finishPendingCertificateActivation()', pending)
        self.assertNotIn('auth.begin()', pending)
        self.assertNotIn('retryProvisioning()', pending)

    def test_reconciliation_never_dispatches_create_revoke_or_auth_begin(self):
        action = region('    func checkProvisioningStorage()', '    func reauthenticateProvisioning()')
        self.assertIn('guard canCheckProvisioningStorage || canCheckPendingCertificateRecovery', action)
        self.assertIn('request(operation: "authReconcileStorage")', action)
        for operation in ('"certCreate"', '"certRevoke"', '"authBegin"', '"authRetryProvisioning"'):
            self.assertNotIn(operation, action)
        self.assertIn('pendingCertificateRecoveryState.requiresAttention', action)
        self.assertIn('let confirmed = await reconcile(force: true)', action)
        self.assertIn('pendingCertificateRecoveryState == .activationRequired', action)
        self.assertIn('message = pendingCertificateRecoveryState.guidance', action)
        self.assertIn('If Retry Provisioning is available below', action)
        policy = region('enum V3PendingCertificateRecoveryState:', 'enum V3SetupSnapshotOutcome:')
        for secret in ('ownerDSID', 'teamID', 'privateKey', 'certificateDER', 'csrPEM'):
            self.assertNotIn(secret, policy)
        self.assertRegex(SOURCE, r'(?:V3LocalizedText|Text)\(auth\.pendingCertificateRecoveryState\.guidance\)')
        activation = region('    func finishPendingCertificateActivation()', '    func checkProvisioningStorage()')
        self.assertIn('guard canFinishPendingCertificateActivation', activation)
        self.assertIn('finishingPendingCertificate: true', activation)
        self.assertEqual(SOURCE.count('finishingPendingCertificate: true'), 1)
        self.assertIn('finishingPendingCertificate: Bool = false', SOURCE)
        self.assertIn('if pendingCertificateActivationSessionID == requestedSession', SOURCE)
        self.assertIn('payload["finishPendingCertificateActivation"] = true', SOURCE)
        self.assertIn('The recovered certificate will become active and replace the current active certificate.', SOURCE)
        self.assertIn('.confirmationDialog("Activate Recovered Certificate?"', SOURCE)
        self.assertIn('payload["finishPendingCertificateActivation"] == nil || strictBool(payload["provisioningLogin"]) == true', WIRE)

    def test_pending_recovery_policy_executes_owner_and_capability_matrix(self):
        compiler = shutil.which('swiftc')
        if not compiler:
            self.skipTest('Swift compiler unavailable; native recovery policy execution required')
        policy = region('enum V3PendingCertificateRecoveryState:', 'enum V3SetupSnapshotOutcome:')
        wire = WIRE[WIRE.index('public struct V3AuthServiceSnapshot:'):WIRE.index('enum V3RequestReplayPolicy {')]
        harness = r'''
func require(_ value: Bool) { if !value { fatalError("pending recovery policy") } }
require(V3PendingCertificateRecoveryState.decode(protocolVersion: nil, rawState: nil) == .unavailable)
require(V3PendingCertificateRecoveryState.decode(protocolVersion: 1, rawState: "none") == .none)
for raw in ["signInRequired", "ownerMismatch", "ready", "activationRequired", "storageUnverified"] {
    require(V3PendingCertificateRecoveryState.decode(protocolVersion: 1, rawState: raw).requiresAttention)
}
for version in [nil, 0, 2] as [Int?] {
    require(V3PendingCertificateRecoveryState.decode(protocolVersion: version, rawState: "ready") == .storageUnverified)
}
for raw in [nil, "", "unavailable", "future"] as [String?] {
    require(V3PendingCertificateRecoveryState.decode(protocolVersion: 1, rawState: raw) == .storageUnverified)
}
let states: [V3PendingCertificateRecoveryState] = [.unavailable, .none, .signInRequired, .ownerMismatch, .ready, .activationRequired, .storageUnverified]
for state in states {
    for flags in 0..<32 {
        let authenticated = flags & 1 != 0
        let hasSession = flags & 2 != 0
        let cancelling = flags & 4 != 0
        let active = flags & 8 != 0
        let checking = flags & 16 != 0
        let allowed = state.mayReconcile(authenticated: authenticated, hasSession: hasSession,
            isCancelling: cancelling, authenticationActive: active, checkingStorage: checking)
        require(allowed == (state == .ready && flags == 1))
        let activate = state.mayFinishActivation(authenticated: authenticated, hasSession: hasSession,
            isCancelling: cancelling, authenticationActive: active, checkingStorage: checking)
        require(activate == (state == .activationRequired && flags == 1))
    }
}
// Same owner returning after sign-out must regain only explicit reconciliation.
let signedOut = V3PendingCertificateRecoveryState.decode(protocolVersion: 1, rawState: "signInRequired")
let wrongOwner = V3PendingCertificateRecoveryState.decode(protocolVersion: 1, rawState: "ownerMismatch")
let returningOwner = V3PendingCertificateRecoveryState.decode(protocolVersion: 1, rawState: "ready")
require(signedOut.requiresAttention && wrongOwner.requiresAttention && returningOwner.requiresAttention)
require(returningOwner.mayReconcile(authenticated: true, hasSession: false, isCancelling: false,
    authenticationActive: false, checkingStorage: false))
let now = Date(timeIntervalSince1970: 1000)
let session = "00000000-0000-0000-0000-000000000025"
func accepts(_ additions: [String: Any], operation: String = "authBegin") -> Bool {
    var payload: [String: Any] = ["session": session, "sessionDeadline": now.addingTimeInterval(300)]
    for (key, value) in additions { payload[key] = value }
    let request: [String: Any] = ["version": 1, "id": session, "operation": operation,
        "target": session, "deadline": now.addingTimeInterval(100), "payload": payload]
    return V3WireContract.encodeRequest(request, now: now) != nil
}
require(accepts([:]))
require(accepts(["provisioningLogin": true]))
require(accepts(["provisioningLogin": true, "finishPendingCertificateActivation": true]))
require(!accepts(["finishPendingCertificateActivation": true]))
require(!accepts(["finishPendingCertificateActivation": false]))
require(!accepts(["provisioningLogin": false, "finishPendingCertificateActivation": false]))
require(accepts(["provisioningLogin": true, "finishPendingCertificateActivation": false]))
require(!accepts(["provisioningLogin": false, "finishPendingCertificateActivation": true]))
for malformed in ["true", 1, 0] as [Any] {
    require(!accepts(["provisioningLogin": true, "finishPendingCertificateActivation": malformed]))
}
require(!accepts(["provisioningLogin": true, "finishPendingCertificateActivation": true], operation: "authRetryProvisioning"))
require(!accepts(["provisioningLogin": true, "finishPendingCertificateActivation": true, "unexpected": true]))
print("pending-host-recovery-pass")
'''
        with tempfile.TemporaryDirectory() as directory:
            main = Path(directory) / 'main.swift'
            main.write_text('import Foundation\nimport CoreFoundation\n' + policy + wire + harness)
            binary = Path(directory) / 'policy'
            result = subprocess.run([compiler, str(main), '-o', str(binary)], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('pending-host-recovery-pass', result.stdout)


if __name__ == '__main__':
    unittest.main()
