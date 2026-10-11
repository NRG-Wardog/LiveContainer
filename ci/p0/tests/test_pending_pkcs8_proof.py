"""Additional reconstruction coverage, without replacing the original native suite."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

class PendingPKCS8Proof(unittest.TestCase):
    def test_native_exact_pkcs8_proof(self):
        if not shutil.which('swiftc') or not shutil.which('openssl'):
            self.skipTest('Native Swift/Security and OpenSSL required')
        root = Path(os.environ['SIDE_STORE_TEST_SOURCE'])
        text = (root/'AltStore/Core/Components/Keychain.swift').read_text()
        proof = text.split('// V3_PENDING_CERTIFICATE_NATIVE_PROOF_BEGIN', 1)[1].split('// V3_PENDING_CERTIFICATE_NATIVE_PROOF_END', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            def run(*args):
                r = subprocess.run(args, capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)
                return r
            run('openssl','genrsa','-out',str(d/'key.pem'),'2048')
            run('openssl','req','-new','-x509','-key',str(d/'key.pem'),'-out',str(d/'cert.pem'),'-days','1','-subj','/CN=Disposable-Reconstruction-Test')
            run('openssl','x509','-in',str(d/'cert.pem'),'-outform','DER','-out',str(d/'cert.der'))
            run('openssl','pkcs8','-topk8','-nocrypt','-in',str(d/'key.pem'),'-outform','DER','-out',str(d/'pkcs8.der'))
            run('openssl','genrsa','-out',str(d/'other.pem'),'2048')
            run('openssl','pkcs8','-topk8','-nocrypt','-in',str(d/'other.pem'),'-outform','DER','-out',str(d/'other.der'))
            original = (d/'pkcs8.der').read_bytes()
            oid = bytes.fromhex('06092a864886f70d010101')
            self.assertEqual(original.count(oid), 1)
            (d/'wrong-algorithm.der').write_bytes(original.replace(oid, bytes.fromhex('06092a864886f70d010102'), 1))
            (d/'main.swift').write_text('import Foundation\nimport Security\n'+proof+'''\nlet cert = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
let key = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2]))
precondition(V3PendingCertificateKeyProof.matches(certificateDER: cert, privateKeyDER: key))
let other = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[3]))
let wrongAlgorithm = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[4]))
precondition(!V3PendingCertificateKeyProof.matches(certificateDER: cert, privateKeyDER: other))
precondition(!V3PendingCertificateKeyProof.matches(certificateDER: cert, privateKeyDER: wrongAlgorithm))
precondition(!V3PendingCertificateKeyProof.matches(certificateDER: cert, privateKeyDER: key + Data([0])))
precondition(!V3PendingCertificateKeyProof.matches(certificateDER: cert, privateKeyDER: Data(key.dropLast())))
print("PENDING_CERTIFICATE_PKCS8_PROOF_PASS")\n''')
            run('swiftc',str(d/'main.swift'),'-o',str(d/'probe'))
            result = run(str(d/'probe'),str(d/'cert.der'),str(d/'pkcs8.der'),str(d/'other.der'),str(d/'wrong-algorithm.der'))
            self.assertIn('PENDING_CERTIFICATE_PKCS8_PROOF_PASS', result.stdout)

if __name__ == '__main__': unittest.main()
