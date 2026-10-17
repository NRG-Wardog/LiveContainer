import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import evidence_transport as transport

class Response(io.BytesIO):
    status=200
    def __init__(self,data):super().__init__(data);self.headers={'Content-Length':str(len(data))}

class Transport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.artifact={'id':transport.ARTIFACT,'name':transport.NAME,'size_in_bytes':transport.SIZE,'digest':'sha256:'+transport.SHA256,'expired':False,
            'workflow_run':{'id':transport.RUN,'head_sha':transport.COMMIT,'head_branch':transport.BRANCH}}
        self.run={'id':transport.RUN,'run_attempt':1,'head_sha':transport.COMMIT,'head_branch':transport.BRANCH,'repository':{'full_name':transport.REPOSITORY},'status':'completed','conclusion':'failure'}
    def test_exact_metadata(self):transport.verify_metadata(self.artifact,self.run)
    def test_wrong_metadata(self):
        for key,value in [('id',1),('name','wrong'),('size_in_bytes',False),('digest','sha256:'+'0'*64),('expired',True)]:
            with self.subTest(key=key):
                row=copy.deepcopy(self.artifact);row[key]=value
                with self.assertRaises(ValueError):transport.verify_metadata(row,self.run)
    def test_wrong_run(self):
        for key,value in [('id',1),('run_attempt',True),('head_sha','0'*40),('status','in_progress'),('conclusion','success')]:
            with self.subTest(key=key):
                row=copy.deepcopy(self.run);row[key]=value
                with self.assertRaises(ValueError):transport.verify_metadata(self.artifact,row)
    def test_split_reconstructs_exact_bytes(self):
        data=bytes(range(256))*257;p=self.root/'original';p.write_bytes(data);digest=hashlib.sha256(data).hexdigest()
        rows=transport.split_verified(p,self.root/'parts',len(data),digest,8192)
        self.assertEqual(b''.join((self.root/'parts'/r['path']).read_bytes() for r in rows),data)
        offset=0
        for ordinal,row in enumerate(rows):
            self.assertEqual(row['ordinal'],ordinal);self.assertEqual(row['offset'],offset)
            self.assertEqual(transport.digest(self.root/'parts'/row['path']),row['sha256']);offset+=row['size']
        self.assertEqual(offset,len(data))
    def test_reordered_chunks_rejected(self):
        p=self.root/'original';p.write_bytes(b'abcdefgh');h=transport.digest(p)
        rows=transport.split_verified(p,self.root/'parts',8,h,4)
        with self.assertRaisesRegex(ValueError,'order'):transport.verify_chunks(self.root/'parts',list(reversed(rows)),8,h,4)
    def test_changed_chunk_rejected(self):
        p=self.root/'original';p.write_bytes(b'abcdefgh');h=transport.digest(p)
        rows=transport.split_verified(p,self.root/'parts',8,h,4);(self.root/'parts/part-000.bin').write_bytes(b'xxxx')
        with self.assertRaisesRegex(ValueError,'digest'):transport.verify_chunks(self.root/'parts',rows,8,h,4)
    def test_wrong_chunk_boundary_rejected(self):
        p=self.root/'original';p.write_bytes(b'abcdefgh');h=transport.digest(p)
        rows=transport.split_verified(p,self.root/'parts',8,h,4);rows[1]['offset']=3
        with self.assertRaisesRegex(ValueError,'boundaries'):transport.verify_chunks(self.root/'parts',rows,8,h,4)
    def test_bad_original_rejected_before_chunks(self):
        p=self.root/'original';p.write_bytes(b'bad')
        with self.assertRaises(ValueError):transport.split_verified(p,self.root/'parts',3,'0'*64,2)
        self.assertFalse((self.root/'parts').exists())
    def test_stale_output_rejected(self):
        p=self.root/'original';p.write_bytes(b'abc');(self.root/'parts').mkdir()
        with self.assertRaises(ValueError):transport.split_verified(p,self.root/'parts',3,transport.digest(p),2)
    def test_linked_original_rejected(self):
        p=self.root/'original';p.write_bytes(b'abc');link=self.root/'link';link.symlink_to(p)
        with self.assertRaises(ValueError):transport.split_verified(link,self.root/'parts',3,transport.digest(p),2)
    def test_chunk_size_bounded(self):
        p=self.root/'original';p.write_bytes(b'abc')
        with self.assertRaises(ValueError):transport.split_verified(p,self.root/'parts',3,transport.digest(p),transport.CHUNK_SIZE+1)
    def test_unreviewed_api_request_rejected(self):
        with self.assertRaises(ValueError):transport.api_request('/user','dummy-token')
    def test_redirect_handler_never_follows(self):
        self.assertIsNone(transport.NoRedirect().redirect_request(None,None,302,None,None,None))
    def test_authorization_not_forwarded(self):
        data=b'archive';requests=[]
        class Opener:
            def open(self,request,timeout):
                requests.append(request)
                if len(requests)==1:raise urllib.error.HTTPError(request.full_url,302,'Found',{'Location':'https://fixture.blob.core.windows.net/archive?signature=sensitive'},None)
                return Response(data)
        with patch.object(transport,'opener',return_value=Opener()),patch.object(transport,'SIZE',len(data)),patch.object(transport,'SHA256',hashlib.sha256(data).hexdigest()):
            transport.download('dummy-token',self.root/'zip')
        self.assertEqual(requests[0].get_header('Authorization'),'Bearer dummy-token')
        self.assertIsNone(requests[1].get_header('Authorization'));self.assertNotIn('dummy-token',requests[1].full_url)
    def test_untrusted_redirect_rejected(self):
        for location in ['http://fixture.blob.core.windows.net/a','https://evil.example/a','https://u:p@fixture.blob.core.windows.net/a','https://fixture.blob.core.windows.net/a#x']:
            with self.subTest(location=location):
                class Opener:
                    def open(self,request,timeout):raise urllib.error.HTTPError(request.full_url,302,'Found',{'Location':location},None)
                with patch.object(transport,'opener',return_value=Opener()):
                    with self.assertRaises(ValueError):transport.download_location('dummy-token')
    def test_storage_redirect_is_not_followed(self):
        with patch.object(transport,'download_location',return_value='https://fixture.blob.core.windows.net/a'):
            class Opener:
                def open(self,request,timeout):raise urllib.error.HTTPError(request.full_url,302,'Found',{'Location':'https://evil.example'},None)
            with patch.object(transport,'opener',return_value=Opener()):
                with self.assertRaises(urllib.error.HTTPError):transport.download('dummy-token',self.root/'zip')
    def test_short_storage_body_rejected(self):
        with patch.object(transport,'download_location',return_value='https://fixture.blob.core.windows.net/a'):
            class Opener:
                def open(self,request,timeout):return Response(b'bad')
            with patch.object(transport,'opener',return_value=Opener()):
                with self.assertRaises(ValueError):transport.download('dummy-token',self.root/'zip')
    def test_network_exception_does_not_expose_url_or_token(self):
        error=urllib.error.URLError('https://fixture.blob.core.windows.net/a?secret=sensitive')
        self.assertEqual(transport.safe_failure(error),'URLError')
        self.assertEqual(transport.safe_failure(transport.TransportError('original ZIP identity differs')),'original ZIP identity differs')
    def test_real_execute_preserves_source_identity_and_does_not_admit(self):
        data=b'original zip byte stream';expected=hashlib.sha256(data).hexdigest();artifact=copy.deepcopy(self.artifact)
        artifact.update(size_in_bytes=len(data),digest='sha256:'+expected)
        original_split=transport.split_verified
        def split(source,output):return original_split(source,output,len(data),expected,8)
        def download(token,target):self.assertEqual(token,'dummy-token');target.write_bytes(data)
        env={'GITHUB_REPOSITORY':transport.REPOSITORY,'GITHUB_REF':'refs/heads/'+transport.BRANCH,'GITHUB_SHA':'transport-commit','GITHUB_RUN_ID':'transport-run','GITHUB_RUN_ATTEMPT':'1'}
        with patch.dict(os.environ,env),patch.object(transport,'SIZE',len(data)),patch.object(transport,'SHA256',expected),patch.object(transport,'api_json',side_effect=[artifact,self.run]),patch.object(transport,'download',side_effect=download),patch.object(transport,'split_verified',side_effect=split):
            result=transport.execute(self.root/'work',self.root/'parts','dummy-token')
        self.assertEqual(result['source']['sha256'],expected);self.assertEqual(result['source']['run_id'],transport.RUN)
        for key in ['zip_rewritten','build_executed','ui_executed','admission_eligible']:self.assertFalse(result[key])
        retained=(self.root/'parts/manifest.json').read_text();self.assertNotIn('dummy-token',retained);self.assertNotIn('Authorization',retained)
    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError):json.loads('{"a":1,"a":2}',object_pairs_hook=transport.unique)

if __name__=='__main__':unittest.main()
