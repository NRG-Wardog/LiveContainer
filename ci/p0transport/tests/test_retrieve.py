import copy
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
  h=r.SafeRedirect();req=urllib.request.Request(r.API+'/actions/artifacts/12207555953/zip',headers={'Authorization':'Bearer synthetic-test'})
  out=h.redirect_request(req,None,302,'Found',{},'https://productionresultssa9.blob.core.windows.net/fixed?sig=synthetic')
  self.assertFalse(out.has_header('Authorization'))
  for url in ('http://productionresultssa9.blob.core.windows.net/x','https://evil.example/x','https://api.github.com.evil.example/x','https://name:secret@api.github.com/x'):
   with self.assertRaises(ValueError):h.redirect_request(req,None,302,'Found',{},url)
 def test_exact_api_and_mutations(self):
  run={'id':r.RUN,'run_attempt':1,'repository':{'full_name':r.REPOSITORY},'head_sha':r.HOST,'head_branch':r.BRANCH,'path':'.github/workflows/p0-defensive-ab-phase-a.yml','event':'push','status':'completed','conclusion':'success'}
  a={'id':r.ARTIFACT,'size_in_bytes':r.SIZE,'digest':'sha256:'+r.DIGEST,'expired':False,'workflow_run':{'id':r.RUN,'head_sha':r.HOST,'head_branch':r.BRANCH},'name':'p0-defensive-ab-phase-a-'+r.HOST+'-'+str(r.RUN)+'-1'}
  r.validate_api(run,a)
  for key,value in [('id',True),('conclusion','failure'),('head_sha','0'*40)]:
   b=copy.deepcopy(run);b[key]=value
   with self.assertRaises(ValueError):r.validate_api(b,a)
  for key,value in [('id',False),('size_in_bytes',1),('digest','sha256:'+'0'*64),('expired',True)]:
   b=copy.deepcopy(a);b[key]=value
   with self.assertRaises(ValueError):r.validate_api(run,b)
if __name__=='__main__':unittest.main()
