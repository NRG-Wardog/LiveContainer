"""Synthetic gate orchestration checks only; no network, Xcode or native execution."""
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest import mock
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'tests'))
import native_build as n
import openssl_artifact_contract as o
import macho_contract as m
from test_macho_contract import fixture

class ProductCaptureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.gate=n.NativeBuildMixin()
        self.gate.work=self.base/'work';self.gate.work.mkdir()
        self.gate.evidence=self.base/'evidence';(self.gate.evidence/'provenance').mkdir(parents=True)
        self.packages=self.gate.work/'sidestore-packages';self.packages.mkdir()
        self.state=self.packages/'workspace-state.json';self.state.write_bytes(b'{"synthetic":true}\n')
        self.record={'synthetic':'resolved source record'}
        self.archive=self.gate.evidence/'provenance/SideStore.OpenSSL.source.zip'
        self.gate.run=mock.Mock()
    def test_owned_fixed_public_archive_retrieval_and_same_workspace_snapshot_retention(self):
        raw=self.state.read_bytes();proof={'synthetic':'source proof'}
        def mutate_after_capture(*args,**kwargs):
            self.state.write_bytes(b'changed after snapshot')
            self.archive.write_bytes(b'synthetic archive bytes')
        self.gate.run.side_effect=mutate_after_capture
        with mock.patch.object(o,'verify_sidestore_openssl',return_value=proof) as verify:
            actual=self.gate.capture_sidestore_openssl('before',{'remotepairingkit':self.record},download=True)
        self.assertEqual(actual,proof)
        self.assertEqual((self.gate.evidence/'provenance/SideStore.workspace-state.before.json').read_bytes(),raw)
        verify.assert_called_once_with(self.packages/'checkouts/RemotePairingKit',self.record,raw,self.packages,self.archive)
        self.gate.run.assert_called_once_with('sidestore-openssl-archive',[
            '/usr/bin/curl','--fail','--location','--silent','--show-error','--proto','=https','--proto-redir','=https',
            '--max-time','300','--max-filesize',str(o.ARCHIVE_BYTES),'--output',self.archive,o.ARCHIVE_URL],cwd=self.gate.work,timeout=330)
        self.assertNotIn('#',o.ARCHIVE_URL)
    def test_after_checkpoint_reuses_retained_archive_without_a_second_retrieval(self):
        self.archive.write_bytes(b'synthetic prior archive')
        with mock.patch.object(o,'verify_sidestore_openssl',return_value={'synthetic':True}) as verify:
            self.gate.capture_sidestore_openssl('after',{'remotepairingkit':self.record})
        self.gate.run.assert_not_called();self.assertEqual(verify.call_args.args[-1],self.archive)
    def test_workspace_bound_is_applied_before_any_retention_or_network(self):
        self.state.write_bytes(b'x'*(o.MAX_STATE_BYTES+1))
        with mock.patch.object(o,'verify_sidestore_openssl') as verify,self.assertRaises(o.OpenSSLArtifactError):
            self.gate.capture_sidestore_openssl('before',{'remotepairingkit':self.record},download=True)
        self.gate.run.assert_not_called();verify.assert_not_called()
        self.assertFalse((self.gate.evidence/'provenance/SideStore.workspace-state.before.json').exists())
        self.assertFalse(self.archive.exists())
        self.assertIn('reason',json.loads((self.gate.evidence/'provenance/SideStore.OpenSSL.failure-before.json').read_bytes()))
    def test_workspace_alias_fails_before_retention_or_network(self):
        other=self.base/'external-state';other.write_bytes(b'{}');self.state.unlink();self.state.symlink_to(other)
        with self.assertRaises(o.OpenSSLArtifactError):
            self.gate.capture_sidestore_openssl('before',{'remotepairingkit':self.record},download=True)
        self.gate.run.assert_not_called();self.assertFalse(self.archive.exists())
        self.assertFalse((self.gate.evidence/'provenance/SideStore.workspace-state.before.json').exists())
    def test_source_rejection_is_persisted_and_rethrown(self):
        error=o.OpenSSLArtifactError('synthetic exact source rejection')
        with mock.patch.object(o,'verify_sidestore_openssl',side_effect=error),self.assertRaises(o.OpenSSLArtifactError) as caught:
            self.gate.capture_sidestore_openssl('after',{'remotepairingkit':self.record})
        self.assertIs(caught.exception,error)
        self.assertEqual(json.loads((self.gate.evidence/'provenance/SideStore.OpenSSL.failure-after.json').read_bytes()),error.diagnostic)
        self.assertFalse((self.gate.evidence/'provenance/SideStore.OpenSSL.source-after.json').exists())
    def test_duplicate_states_or_reused_archive_reject_before_command(self):
        self.archive.write_bytes(b'existing')
        with self.assertRaises(ValueError):self.gate.capture_sidestore_openssl('before',{'remotepairingkit':self.record},download=True)
        self.archive.unlink();nested=self.packages/'other';nested.mkdir();(nested/'workspace-state.json').write_bytes(b'{}')
        with self.assertRaises(ValueError):self.gate.capture_sidestore_openssl('before',{'remotepairingkit':self.record},download=True)
        self.gate.run.assert_not_called()
    def test_both_owner_inventories_survive_first_static_product_rejection(self):
        roots={owner:self.base/owner for owner in ('SideStore','LiveContainer')}
        for path in roots.values():path.mkdir()
        lock=roots['SideStore']/n.LOCK;lock.parent.mkdir(parents=True);lock.write_bytes(b'synthetic lock')
        self.gate.roots=roots;self.gate.data={'graph':{'owners':{'AnisetteKit':{'commit':'1'*40}}}}
        self.gate.resolved_app_graph=mock.Mock(return_value={})
        # Explicitly mocked source seam; no genuine binary-artifact proof claimed.
        self.gate.capture_sidestore_openssl=mock.Mock(return_value=None)
        self.gate.verify_working_sources=mock.Mock();self.gate.state={}
        for owner,folder in [('SideStore','sidestore-derived'),('LiveContainer','livecontainer-derived')]:
            app=self.gate.work/folder/'Build/Products/Release-iphoneos'/(owner+'.app');app.mkdir(parents=True)
            (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':owner}));(app/owner).write_bytes(fixture())
            if owner=='SideStore':(app/'_CodeSignature').mkdir();(app/'_CodeSignature/CodeResources').write_bytes(b'synthetic forbidden signature')
        source=self.base/'transport-source';staged=self.base/'transport-staged'
        for root in (source,staged):root.mkdir();(root/'synthetic.a').write_bytes(b'not executed')
        self.gate.transport_source=source;self.gate.transport_staged=staged;self.gate.transport_expected=n.file_inventory(source)
        with mock.patch.object(n,'check_lock',return_value={'synthetic':True}),self.assertRaises(m.ProductValidationError):self.gate.app_build()
        for owner in roots:
            report=json.loads((self.gate.evidence/('provenance/product-inventory-'+owner+'.json')).read_bytes())
            self.assertEqual(report['owner'],owner);self.assertTrue(report['complete']);self.assertIn(owner,report['inventory'])
        failure=json.loads((self.gate.evidence/'provenance/product-static-failure.json').read_bytes())
        self.assertEqual(failure['owner'],'SideStore');self.assertEqual(failure['context']['bundle'],'')
        self.assertFalse(getattr(self.gate,'app_product_checks_complete',False))
        self.assertNotIn('app_typechecked',self.gate.state)
        self.assertFalse((self.gate.evidence/'provenance/unsigned-products.json').exists())
        self.assertEqual([call.args[0] for call in self.gate.run.call_args_list],['sidestore-resolve','sidestore-frozen-resolve','sidestore-build','livecontainer-build'])

if __name__=='__main__':unittest.main(verbosity=2)
