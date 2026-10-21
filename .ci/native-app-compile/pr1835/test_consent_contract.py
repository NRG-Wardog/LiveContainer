"""Source contracts and an explicitly fake request/admission model.

No Swift/native/app execution, credentials, provider contact, or network.
The fake model is not an iOS runtime test; the source anchors bind it to the
reviewed guards, and CI/device checks remain necessary for actual behavior.
Set PR1835_CONSENT_SOURCE_ROOT to validate a combined candidate tree.
"""
import os
from pathlib import Path
import re
import unittest
import uuid

ROOT = Path(os.environ.get('PR1835_CONSENT_SOURCE_ROOT', Path(__file__).resolve().parents[1]))
HOST = (ROOT/'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift').read_text()
BRIDGE = (ROOT/'LiveContainer/SideStoreSupport/SideStore.swift').read_text()
SERVICE = (ROOT/'SideStore/AltStore/AppDelegate.swift').read_text()

def block(text, marker):
    start = text.index(marker)
    opening = text.index('{', start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == '{': depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth == 0: return text[start:index + 1]
    raise AssertionError('unclosed source block: ' + marker)

POLICY = block(SERVICE, 'static func acceptsWindowsAnisetteConsent(')
ENDPOINTS = set(re.findall(r'"(https://[^\"]+)"', POLICY))
EKEY='windowsAnisetteEndpoint'
CKEY='windowsAnisetteConsentAttemptID'
SID='AC155D8C-2A04-4411-8052-84672C92A457'
OTHER='24F07D13-D0A8-4FDC-B906-65977B8F8424'

# This fake mirrors the source guards; it never substitutes for Swift execution.
def canonical(value):
    if not isinstance(value, str): return False
    try: return str(uuid.UUID(value)).upper() == value
    except (ValueError, AttributeError): return False

def accepts(operation, payload, target=SID, now=1000):
    base={'session', 'sessionDeadline'}
    allowed=base | ({'provisioningLogin', 'finishPendingCertificateActivation', EKEY, CKEY} if operation=='authBegin' else set())
    if operation not in {'authBegin','authRetryProvisioning'}: return False
    if not base <= payload.keys() or not payload.keys() <= allowed: return False
    for key in ['provisioningLogin','finishPendingCertificateActivation']:
        if key in payload and type(payload[key]) is not bool: return False
    if payload.get('finishPendingCertificateActivation') and not payload.get('provisioningLogin'): return False
    if not canonical(payload['session']) or payload['session'] != target: return False
    if type(payload['sessionDeadline']) not in {int,float} or not now < payload['sessionDeadline'] <= now+610: return False
    if EKEY not in payload and CKEY not in payload: return True
    return (type(payload.get(EKEY)) is str and payload[EKEY] in ENDPOINTS and
            canonical(payload.get(CKEY)) and payload[CKEY] == payload['session'] and
            not payload.get('provisioningLogin') and not payload.get('finishPendingCertificateActivation'))

def payload(**extra):
    return {'session':SID, 'sessionDeadline':1100, **extra}

def remote(**extra):
    return payload(**{EKEY:'https://ani.jkcoxson.com', CKEY:SID, **extra})

class FakeAttemptAdmission:
    def __init__(self):
        self.consumed=set(); self.cancelled=set(); self.requests=[]
    def begin(self, value, operation='authBegin'):
        if not accepts(operation,value): return False
        if EKEY not in value: return 'local'
        consent=value[CKEY]
        if consent in self.consumed or len(self.consumed)>=1024: return False
        self.consumed.add(consent)
        if consent in self.cancelled: return False
        self.requests.append(value[EKEY]); return True
    def finish(self): pass  # Must not unconsume permission.

class ConsentContracts(unittest.TestCase):
    def test_wire_validator_copies_are_exact(self):
        self.assertEqual(POLICY,block(BRIDGE,'static func acceptsWindowsAnisetteConsent('))
    def test_allowlist_exact(self):
        self.assertEqual(ENDPOINTS,{'https://ani.jkcoxson.com','https://ani2.stikstore.app'})
    def test_default_local_and_existing_modes_unchanged(self):
        self.assertTrue(accepts('authBegin',payload()))
        self.assertTrue(accepts('authRetryProvisioning',payload()))
        self.assertTrue(accepts('authBegin',payload(provisioningLogin=True)))
        self.assertTrue(accepts('authBegin',payload(provisioningLogin=True,finishPendingCertificateActivation=True)))
    def test_each_exact_provider_requires_bound_consent(self):
        for endpoint in ENDPOINTS:
            self.assertTrue(accepts('authBegin',remote(**{EKEY:endpoint})))
    def test_partial_and_wrong_types_fail_closed(self):
        for data in [payload(**{EKEY:next(iter(ENDPOINTS))}),payload(**{CKEY:SID}),remote(**{EKEY:True}),remote(**{EKEY:{'url':next(iter(ENDPOINTS))}}),remote(**{CKEY:False}),remote(**{CKEY:[SID]}),remote(**{CKEY:None})]:
            with self.subTest(data=data): self.assertFalse(accepts('authBegin',data))
    def test_uuid_is_canonical_and_bound_to_target(self):
        for consent in [OTHER,SID.lower(),'bad','',SID+'x']:
            self.assertFalse(accepts('authBegin',remote(**{CKEY:consent})))
        self.assertFalse(accepts('authBegin',remote(),target=OTHER))
    def test_endpoint_variants_are_not_authorized(self):
        for endpoint in ['http://ani.jkcoxson.com','https://ani.jkcoxson.com/','https://ani.jkcoxson.com:443','https://ani.jkcoxson.com/path','https://ani.jkcoxson.com?x=y','https://ani.jkcoxson.com#f','https://user@ani.jkcoxson.com','https://ANI.JKCOXSON.COM','https://evil.example','https://ani.jkcoxson.com.evil.example']:
            self.assertFalse(accepts('authBegin',remote(**{EKEY:endpoint})))
    def test_remote_not_accepted_on_retry_or_other_operations(self):
        for operation in ['authRetryProvisioning','refresh','opStart','settingsSet','authRespond']:
            self.assertFalse(accepts(operation,remote()))
        for extra in [dict(provisioningLogin=True),dict(provisioningLogin=True,finishPendingCertificateActivation=True)]:
            self.assertFalse(accepts('authBegin',remote(**extra)))
    def test_extra_keys_and_expired_attempt_rejected(self):
        self.assertFalse(accepts('authBegin',remote(password='never-send')))
        for deadline in [999,1000,1611,None,'1100']:
            self.assertFalse(accepts('authBegin',remote(sessionDeadline=deadline)))
    def test_wire_source_preserves_secret_sweep_and_operation_allowlist(self):
        for source in [BRIDGE,SERVICE]:
            policy=block(source,'private static func acceptsPayload(')
            self.assertIn('guard !containsRawSecretField(payload, skipping: skipping)',policy)
            self.assertIn('operation == "authBegin" ? baseKeys.union(["provisioningLogin", "finishPendingCertificateActivation", "windowsAnisetteEndpoint", "windowsAnisetteConsentAttemptID"]) : baseKeys',policy)
            self.assertIn('acceptsWindowsAnisetteConsent(payload, sessionID: session)',policy)
    def test_off_cancel_and_decline_never_request_provider_in_fake(self):
        admission=FakeAttemptAdmission()
        self.assertEqual(admission.begin(payload()),'local')
        admission.cancelled.add(SID)
        self.assertFalse(admission.begin(remote()))
        self.assertEqual(admission.requests,[])
        self.assertFalse(admission.begin(remote()))
    def test_same_consent_cannot_replay_or_switch_provider_in_fake(self):
        admission=FakeAttemptAdmission()
        self.assertTrue(admission.begin(remote()))
        admission.finish()
        self.assertFalse(admission.begin(remote()))
        self.assertFalse(admission.begin(remote(**{EKEY:'https://ani2.stikstore.app'})))
        self.assertEqual(admission.requests,['https://ani.jkcoxson.com'])
    def test_source_consumes_atomically_before_cancellation_and_task(self):
        begin=block(SERVICE,'func begin(deadline: Date, mode: BeginMode')
        self.assertIn('consent == parsedID',begin)
        self.assertIn('sessions[id] == nil',begin)
        self.assertIn('mode == .interactive',begin)
        consume=begin.index('consumedWindowsAnisetteConsentIDs.insert(consent).inserted')
        self.assertLess(consume,begin.index('cancelledBeforeBegin.consume(id)'))
        self.assertLess(consume,begin.index('sessions[id]?.task = Task'))
        self.assertIn('consumedWindowsAnisetteConsentIDs.count < 1024',begin)
        self.assertNotIn('consumedWindowsAnisetteConsentIDs.remove',SERVICE)
    def test_routes_cleared_on_all_service_end_paths(self):
        for marker in ['func expire(id: String)','func cancel(id: String) -> Bool','private func finish(id: String, response:']:
            body=block(SERVICE,marker)
            self.assertIn('session.windowsAnisetteEndpoint = nil',body)
            self.assertIn('session.windowsAnisetteConsentAttemptID = nil',body)
        body=block(SERVICE,'private func runLoginPipeline(id:')
        self.assertIn('sessions[id]?.windowsAnisetteEndpoint = nil',body)
        self.assertIn('sessions[id]?.windowsAnisetteConsentAttemptID = nil',body)
        self.assertLess(body.index('try Task.checkCancellation()'),body.index('let operation = try SignInOperation'))
        self.assertLess(body.index('sessions[id]?.cancellationRequested == false'),body.index('let operation = try SignInOperation'))
    def test_route_not_persisted_or_returned_by_service(self):
        poll=block(SERVICE,'func poll(id: String)')
        self.assertNotIn('windowsAnisette',poll)
        for line in SERVICE.splitlines():
            if 'windowsAnisette' in line or 'WindowsAnisetteConsentIDs' in line:
                self.assertNotIn('defaults.',line)
                self.assertNotIn('Keychain.',line)
                self.assertNotIn('debugLog(',line)
    def test_host_only_confirmation_calls_remote_begin(self):
        self.assertEqual(HOST.count('auth.beginWithWindowsAnisette(choice)'),1)
        view=block(HOST,'struct V3SignInView: View')
        self.assertIn('presenting: pendingWindowsAnisetteChoice) { choice in',view)
        confirm=view.index('Button("Use for This Sign-In Attempt"')
        self.assertGreater(view.index('auth.beginWithWindowsAnisette(choice)'),confirm)
        self.assertIn('Button("Cancel", role: .cancel) { pendingWindowsAnisetteChoice = nil }',view)
        begin=block(HOST,'fileprivate func beginWithWindowsAnisette(')
        self.assertIn('guard canBegin, !hasSession, !isSignedIn else { return }',begin)
    def test_host_new_uuid_passed_as_consent_no_default_route(self):
        begin=block(HOST,'private func startAuthentication(')
        self.assertIn('windowsAnisetteChoice: V3WindowsAnisetteChoice? = nil',begin)
        self.assertIn('let requestedSession = UUID().uuidString',begin)
        run=block(HOST,'private func run(sessionID requestedSession:')
        self.assertIn('if let windowsAnisetteChoice',run)
        self.assertIn('payload["windowsAnisetteConsentAttemptID"] = requestedSession',run)
        self.assertIn('guard session == requestedSession, !isCancelling else { return }',run)
        prepare=block(HOST,'@MainActor private func prepareSignIn() async')
        self.assertIn('auth.begin()',prepare)
        self.assertNotIn('windowsAnisette',prepare)
        retry=block(HOST,'private func runProvisioningRetry(')
        self.assertNotIn('windowsAnisette',retry)
    def test_disclosure_covers_recipient_data_risk_and_storage(self):
        choice=block(HOST,'fileprivate enum V3WindowsAnisetteChoice:')
        for required in ['rawValue','SPIM','PTM/TK','ADI','SIM','device ID/local user ID (LU)','error-434','impersonate','Apple ID, password, verification codes and SRP proof','Keychain','another attempt','existing local anisette identity','background refresh','default provider','switch providers automatically']:
            self.assertIn(required,choice)
    def test_end_current_attempt_uses_existing_cancellation_without_reset(self):
        section=block(HOST,'@ViewBuilder private var experimentalWindowsAnisetteSection:')
        self.assertIn('auth.canBegin && !auth.hasSession',section)
        self.assertIn('auth.cancel()',section)
        self.assertIn('auth.reloadAuthoritativeAccountStatus()',section)
        for forbidden in ['anisetteReset','signOut','UserDefaults','Keychain','URLSession','auth.beginWithWindowsAnisette']:
            self.assertNotIn(forbidden,section)
        self.assertIn('pendingWindowsAnisetteChoice = nil',section)
        self.assertIn('choosingWindowsAnisette = false',section)
    def test_absent_selection_and_dismissal_clear_permission(self):
        view=block(HOST,'struct V3SignInView: View')
        self.assertIn('@State private var pendingWindowsAnisetteChoice: V3WindowsAnisetteChoice?',view)
        self.assertNotIn('@AppStorage',view)
        disappear=view[view.index('.onDisappear {'):view.index('@ViewBuilder private var experimentalWindowsAnisetteSection:')]
        self.assertIn('pendingWindowsAnisetteChoice = nil',disappear)
        self.assertIn('choosingWindowsAnisette = false',disappear)
        self.assertIn('auth.cancel()',disappear)

class DiagnosticContracts(unittest.TestCase):
    def test_typed_windows_error_maps_to_existing_anisette_kind(self):
        mapper=block(SERVICE,'func v3AccountOperationFailure(')
        start=mapper.index('else if let windows = error as? WindowsAnisetteError')
        end=mapper.index('else if let anisette = error as? SideSign.AnisetteError',start)
        projection=mapper[start:end]
        self.assertIn('kind = .anisetteFailure',projection)
        self.assertNotIn('.anisetteKit',projection)
        self.assertIn('windows.reasonCode',projection)
        self.assertIn('windows.httpStatusCode, (100...599).contains(status)',projection)
        self.assertIn('case .some(.jkcoxson)',projection)
        self.assertIn('case .some(.stikstore)',projection)
        self.assertIn('case .none: windowsAnisetteProvider = "unselected"',projection)
        for unsafe in ['localizedDescription','userInfo','rawValue','clientInfo','userAgent']:
            self.assertNotIn(unsafe,projection)
    def test_only_finite_windows_context_is_accepted(self):
        for source in [SERVICE,BRIDGE]:
            validator=block(source,'public static func validatedSigningContext(')
            start=validator.index('case "windows_provider":')
            end=validator.index('case "http_status":',start)
            projection=validator[start:end]
            self.assertEqual(projection.count('fields["typed_error"] == "anisetteFailure"'),2)
            self.assertIn('["jkcoxson", "stikstore", "unselected"].contains(text)',projection)
            for reason in ['consentRequired','invalidProvider','invalidState','stateChanged','invalidResponse','resyncUnavailable','httpStatus']:
                self.assertIn('"'+reason+'"',projection)
            self.assertIn('fields["windows_reason"] != nil',projection)
            self.assertIn('fields["windows_provider"] != nil',projection)
    def test_owned_error_retains_projection_after_scope(self):
        for source in [SERVICE,BRIDGE]:
            error=block(source,'struct V3AccountOperationError:')
            self.assertIn('var windowsAnisetteProvider: String? = nil',error)
            self.assertIn('var windowsAnisetteReason: String? = nil',error)
            self.assertIn('signingContext["windows_provider"] = windowsAnisetteProvider',error)
            self.assertIn('signingContext["windows_reason"] = windowsAnisetteReason',error)
            self.assertNotIn('WindowsAnisetteAuthentication.current',error)
    def test_actual_copy_renderer_is_mirrored_and_includes_fields(self):
        renderers=[block(source,'static func render(_ failure:') for source in [SERVICE,BRIDGE,HOST]]
        self.assertEqual(renderers[0],renderers[1])
        self.assertEqual(renderers[1],renderers[2])
        render=renderers[0]
        self.assertIn('CombinedFailure.validatedSigningContext',render)
        self.assertIn('fields["windows_provider"]',render)
        self.assertIn('fields["windows_reason"]',render)
        self.assertIn('+ accountDetails + authResponseDetails + windowsDetails + nativeDetails',render)
        self.assertIn('http_status=',render)
        self.assertIn('V3AuthFailureDiagnosticsPolicy.render(failure,',block(HOST,'static func failureDetails(from failure:'))
    def test_projection_has_no_new_error_kind(self):
        classifier=block(SERVICE,'func v3ClassifyAuthError(')
        self.assertIn('error is WindowsAnisetteError { return .anisette }',classifier)
        for source in [SERVICE,BRIDGE]:
            kind=block(block(source,'struct V3AccountOperationError:'),'enum Kind:')
            self.assertNotIn('windows',kind.lower())

if __name__ == '__main__': unittest.main(verbosity=2)
