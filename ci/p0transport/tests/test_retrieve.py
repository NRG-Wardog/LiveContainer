import copy
import inspect
import os
from unittest.mock import patch
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import retrieve as r

class Tests(unittest.TestCase):
 def test_exact_download_and_split_reassembly(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();raw=b'exact original artifact bytes';digest=hashlib.sha256(raw).hexdigest();p=root/'archive'
   r.download(io.BytesIO(raw),p,len(raw),digest);rows=r.split(p,root/'parts',len(raw),digest,8)
   self.assertEqual(b''.join((root/'parts'/v['name']).read_bytes() for v in rows),raw)
   self.assertTrue(all(v['bytes']<=8 for v in rows))
 def test_short_long_and_corrupt_archive_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve()
   for i,data in enumerate((b'a',b'abc',b'zz')):
    with self.assertRaises(ValueError):r.download(io.BytesIO(data),root/str(i),2,hashlib.sha256(b'ab').hexdigest())
 def test_existing_output_and_archive_alias_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();p=root/'a';p.write_bytes(b'abc');d=hashlib.sha256(b'abc').hexdigest();out=root/'out';out.mkdir()
   with self.assertRaises(ValueError):r.split(p,out,3,d)
   alias=root/'alias';alias.symlink_to(p)
   with self.assertRaises(ValueError):r.split(alias,root/'fresh',3,d)
 def test_redirect_removes_authorization_and_rejects_other_hosts(self):
  h=r.SafeRedirect();req=urllib.request.Request(r.API+'/actions/artifacts/12219284081/zip',headers={'Authorization':'Bearer synthetic-test'})
  out=h.redirect_request(req,None,302,'Found',{},'https://productionresultssa9.blob.core.windows.net/fixed?sig=synthetic')
  self.assertFalse(out.has_header('Authorization'))
  for url in ('http://productionresultssa9.blob.core.windows.net/x','https://evil.example/x','https://api.github.com.evil.example/x','https://name:secret@api.github.com/x'):
   with self.assertRaises(ValueError):h.redirect_request(req,None,302,'Found',{},url)
 def api_fixture(self):
  # Observed fields copied from the original final APIs; raw API replay is recorded in checks.
  run={'id': 39317695511, 'run_attempt': 1, 'repository': {'full_name': 'NRG-Wardog/LiveContainer'}, 'head_sha': '2437b2abb7bb950efcec254441b4b917ac3982ce', 'head_branch': 'validation/p0-defensive-diagnostic-phase-b', 'path': '.github/workflows/p0-defensive-diagnostic-phase-b.yml', 'event': 'push', 'status': 'completed', 'conclusion': 'failure'}
  a={'id': 12219284081, 'node_id': 'MDg6QXJ0aWZhY3QxMjIxOTI4NDA4MQ==', 'name': 'p0-defensive-diagnostic-phase-b-2437b2abb7bb950efcec254441b4b917ac3982ce-39317695511-1', 'size_in_bytes': 1391820297, 'url': 'https://api.github.com/repos/NRG-Wardog/LiveContainer/actions/artifacts/12219284081', 'archive_download_url': 'https://api.github.com/repos/NRG-Wardog/LiveContainer/actions/artifacts/12219284081/zip', 'expired': False, 'digest': 'sha256:94eeea8a110aea442e67564a1b41906e803490e04611ff58b485be80ddd7c553', 'created_at': '2026-10-19T20:30:17Z', 'updated_at': '2026-10-19T20:30:17Z', 'expires_at': '2026-11-02T20:28:33Z', 'workflow_run': {'id': 39317695511, 'repository_id': 1366314274, 'head_repository_id': 1366314274, 'head_branch': 'validation/p0-defensive-diagnostic-phase-b', 'head_sha': '2437b2abb7bb950efcec254441b4b917ac3982ce'}}
  return run,a
 def test_exact_api_and_mutations(self):
  run,a=self.api_fixture()
  r.validate_api(run,a)
  for key,value in [('id',True),('conclusion','success'),('head_sha','0'*40)]:
   b=copy.deepcopy(run);b[key]=value
   with self.assertRaises(ValueError):r.validate_api(b,a)
  for key,value in [('id',False),('size_in_bytes',1),('digest','sha256:'+'0'*64),('expired',True)]:
   b=copy.deepcopy(a);b[key]=value
   with self.assertRaises(ValueError):r.validate_api(run,b)
 def test_only_this_exact_failed_capture_is_accepted(self):
  run,a=self.api_fixture()
  for key,values in [('id',[True,str(r.RUN),r.RUN+1,39293060769]),('run_attempt',[True,0,2,'1']),('head_sha',['0'*40,'d057b2bd1cedc2ac234f8b7397052ed9554b6c0d']),('head_branch',['validation/p0-defensive-ab-phase-a-toolchain','main']),('path',['.github/workflows/p0-defensive-ab-phase-a.yml','.github/workflows/p0-defensive-diagnostic-phase-a-swift-split.yml','.github/workflows/build.yml']),('event',['workflow_dispatch','pull_request']),('status',['queued','in_progress']),('conclusion',['success','cancelled','timed_out','neutral','skipped','action_required',None])]:
   for value in values:
    b=copy.deepcopy(run);b[key]=value
    with self.subTest(key=key,value=value),self.assertRaises(ValueError):r.validate_api(b,a)
  b=copy.deepcopy(run);b['repository']['full_name']='Other/LiveContainer'
  with self.assertRaises(ValueError):r.validate_api(b,a)
 def test_artifact_identity_and_workflow_binding_reject_all_drift(self):
  run,a=self.api_fixture()
  for key,values in [('id',[False,str(r.ARTIFACT),12207555953]),('size_in_bytes',[r.SIZE-1,r.SIZE+1,str(r.SIZE)]),('digest',['sha256:'+'0'*64,r.DIGEST]),('expired',[True,0]),('name',['p0-defensive-diagnostic-phase-b-'+r.HOST+'-'+str(r.RUN)+'-2','p0-defensive-ab-phase-a-'+r.HOST+'-'+str(r.RUN)+'-1'])]:
   for value in values:
    b=copy.deepcopy(a);b[key]=value
    with self.subTest(key=key,value=value),self.assertRaises(ValueError):r.validate_api(run,b)
  for key,value in [('id',r.RUN+1),('head_sha','0'*40),('head_branch','main')]:
   b=copy.deepcopy(a);b['workflow_run'][key]=value
   with self.assertRaises(ValueError):r.validate_api(run,b)
 def test_fixed_run_artifact_and_exact_six_part_lengths(self):
  self.assertEqual((r.RUN,r.ATTEMPT,r.HOST,r.BRANCH,r.ARTIFACT,r.SIZE,r.DIGEST),(39317695511,1,'2437b2abb7bb950efcec254441b4b917ac3982ce','validation/p0-defensive-diagnostic-phase-b',12219284081,1391820297,'94eeea8a110aea442e67564a1b41906e803490e04611ff58b485be80ddd7c553'))
  self.assertEqual(r.PART_SIZE,268435456)
  self.assertEqual(divmod(r.SIZE,r.PART_SIZE),(5,49643017))
 def test_original_transport_algorithms_remain_byte_identical(self):
  expected={'SafeRedirect': 'b6cc4d952cf0a4bacac509658cd068ee52ba4927cceb9f5a0db64d7be9da0721', 'download': '2d5c46136380dc94ea1472f5a4761d7019a232e9272059c7ad0d6300f040a182', 'split': '2a2d7a3aaac90264a5805d81a861b3952e77522ae448de38cbd35887ac4ed987'}
  for name,digest in expected.items():
   source=inspect.getsource(getattr(r,name))
   if name=='split':source=source.replace('len(rows) <= 6','len(rows) <= 4')
   self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),digest)
 def test_wrong_transport_branch_refuses_before_any_network_request(self):
  for branch in ('validation/p0-defensive-ab-artifact-transport','main','validation/p0-defensive-diagnostic-phase-b'):
   with patch.dict(os.environ,{'GITHUB_REPOSITORY':r.REPOSITORY,'GITHUB_REF':'refs/heads/'+branch},clear=True),patch.object(r.urllib.request,'build_opener') as opener:
    with self.assertRaisesRegex(ValueError,'exact retrieval-only branch'):r.main()
    opener.assert_not_called()
 def test_workflow_is_isolated_readonly_six_part_transport(self):
  root=Path(__file__).resolve().parents[3]
  source=(root/'.github/workflows/p0-defensive-diagnostic-phase-b-transport.yml').read_text()
  self.assertIn('branches: [validation/p0-defensive-diagnostic-phase-b-transport]',source)
  self.assertIn('contents: read',source);self.assertIn('actions: read',source);self.assertIn('persist-credentials: false',source)
  self.assertEqual(source.count('compression-level: 0'),7)
  for n in range(6):self.assertIn('name: original-12219284081-part-'+str(n).zfill(2),source)
  self.assertIn('name: original-12219284081-transport-manifest',source)
  self.assertNotIn('workflow_dispatch',source);self.assertNotIn('swift',source);self.assertNotIn('xcodebuild',source)
  build=(root/'.github/workflows/build.yml').read_text()
  self.assertEqual(build.count("    if: github.ref != 'refs/heads/validation/p0-defensive-diagnostic-phase-b-transport'"),1)
if __name__=='__main__':unittest.main()
