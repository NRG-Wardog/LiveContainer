"""Additional reconstruction regression; original recovered contracts stay unchanged."""
from pathlib import Path
import os,unittest,shutil,subprocess,tempfile
ROOT=Path(os.environ['SIDE_STORE_TEST_SOURCE'])
SOURCE=ROOT/'SideStore/Core/Certificates/CertificateManager.swift'
def method():
 s=SOURCE.read_text();return s[s.index('    public func v3CompletePendingCertificateIfStored('):s.index('    public func clearActiveCertificate()')].replace('public func','func',1)
HARNESS='''import Foundation
enum Purpose { case provisioning, importedCopy }
enum Phase { case created }
struct Record { var purpose = Purpose.importedCopy; let phase = Phase.created; let certificateDER: Data? = Data([1]); let privateKey = Data([2]) }
enum V3PendingCertificateCreationError: Error { case pending }
struct X509 { let data: Data? = Data([1]) }
struct ALTCertificate { let x509 = X509(); let serialNumber = "serial"; let privateKey = Data([2]) }
enum V3PendingCertificateKeyProof {
 static func matches(certificateDER: Data, privateKeyPEM: Data) -> Bool { true }
 static func matches(certificateDER: Data, privateKeyDER: Data) -> Bool { true }
}
final class AuthManager { static let shared = AuthManager(); var v3IdentityGeneration = 1; var v3IdentityIsStable = true }
final class Keychain {
 static let shared = Keychain(); var record: Record? = Record(); var clears=0
 func pendingCertificateCreation() throws -> Record? { record }
 func completePendingCertificateCreation(_ record: Record, certificateSerial: String, storedCopyIsVerified: (Data,String?) throws -> Bool) throws {
  guard try storedCopyIsVerified(Data([1]), nil) else { throw V3PendingCertificateCreationError.pending }
  self.record=nil;clears += 1
 }
}
final class Probe {
 var indexed=false
 static func parse(_ bytes: Data, password: String?) throws -> ALTCertificate { ALTCertificate() }
 func getImportedCertificateSerials() -> [String] { indexed ? ["serial"] : [] }
__METHOD__
}
@main struct Main {
 static func main() throws {
  let p=Probe()
  do { try p.v3CompletePendingCertificateIfStored(ALTCertificate());fatalError("missing index accepted") }
  catch V3PendingCertificateCreationError.pending {}
  precondition(Keychain.shared.record != nil && Keychain.shared.clears == 0)
  p.indexed=true;try p.v3CompletePendingCertificateIfStored(ALTCertificate())
  precondition(Keychain.shared.record == nil && Keychain.shared.clears == 1)
  Keychain.shared.record=Record(purpose: .provisioning);p.indexed=false
  try p.v3CompletePendingCertificateIfStored(ALTCertificate())
  precondition(Keychain.shared.record == nil && Keychain.shared.clears == 2)
  print("COMPLETION_INDEX_NEGATIVE_PASS")
 }
}
'''
class CompletionTests(unittest.TestCase):
 def test_index_proof_inside_locked_callback(self):
  body=method();callback=body.split('storedCopyIsVerified:',1)[1]
  self.assertIn('record.purpose == .importedCopy',callback)
  self.assertIn('!self.getImportedCertificateSerials().contains(certificate.serialNumber)',callback)
  self.assertNotIn('Keychain.shared.',callback)
 def test_native_index_missing_retains_journal(self):
  compiler=shutil.which('swiftc')
  if not compiler:self.skipTest('Swift unavailable; new exact-method runtime regression not executed')
  with tempfile.TemporaryDirectory() as d:
   src=Path(d)/'test.swift';out=Path(d)/'test';src.write_text(HARNESS.replace('__METHOD__',method()))
   r=subprocess.run([compiler,'-parse-as-library',str(src),'-o',str(out)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
   r=subprocess.run([str(out)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr);self.assertIn('COMPLETION_INDEX_NEGATIVE_PASS',r.stdout)
if __name__=='__main__':unittest.main()
