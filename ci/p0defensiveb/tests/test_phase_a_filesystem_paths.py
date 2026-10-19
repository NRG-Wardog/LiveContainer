"""Exact SDK path forms in synthetic raw trees; no artifact extraction or execution."""
import hashlib,sys,tempfile,unittest,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import phase_a_raw_replay as r
from phase_a_host_replay import BOUNDS

SDK='/Applications/Xcode_26.4.1.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk'
OBSERVED=('usr/share/man/man3/APR::Base64.3pm','usr/share/man/man3/Algorithm::Annotate5.34.3pm','usr/share/man/man3/Parse::Yapp.3','usr/share/man/mann/ttk::button.ntcl')

def raw_record(content,**extra):
    digest=r.sha(content);git=b'blob '+str(len(content)).encode()+b'\0'+content
    return dict(kind='file',label='synthetic-only',sha256=digest,length=len(content),blob_path='blobs/sha256/'+digest[:2]+'/'+digest,git_blob_sha1=hashlib.sha1(git).hexdigest(),git_blob_sha256=hashlib.sha256(git).hexdigest(),**extra)


class FilesystemMetadataPathTests(unittest.TestCase):
    def fixture(self):
        rows=[{'path':name,'kind':'directory','mode':'0755'} for name in ('','usr','usr/share','usr/share/man','usr/share/man/man3','usr/share/man/mann')];files={}
        for name in OBSERVED:
            content=('synthetic-only:'+name).encode();row=raw_record(content,path=name,source_path=SDK+'/'+name,mode='0444');rows.append(row);files[row['blob_path']]=content
        return files,{'kind':'filesystem-tree','label':'macos-sdk','source_path':SDK,'entries':rows}
    def test_exact_observed_sdk_names_remain_literal_metadata(self):
        files,tree=self.fixture();result=r.RawReplay(files,BOUNDS).tree(tree)
        for name in OBSERVED:self.assertEqual(result[name]['path'],name);self.assertEqual(r.filesystem_metadata_path(name),name)
        self.assertEqual(r.filesystem_metadata_path(''),'')
    def test_traversal_absolute_control_backslash_and_drive_forms_reject(self):
        invalid=('/usr/foo','../foo','usr/../foo','usr/./foo','usr//foo','usr/foo/','C:/foo','C:foo','usr\\foo','usr/x\0y','usr/x\ny','usr/x\ty','usr/x\x7fy','usr/x\x85y',None,True)
        for name in invalid:
            with self.subTest(name=name),self.assertRaises(ValueError):r.filesystem_metadata_path(name)
    def test_length_and_depth_limits_are_unchanged(self):
        for name in ('x'*4097,'/'.join(['a']*129)):
            with self.subTest(name=name[:80]),self.assertRaises(ValueError):r.filesystem_metadata_path(name)
        self.assertEqual(r.filesystem_metadata_path('x'*4096),'x'*4096)
    def test_colons_still_reject_in_archive_git_and_blob_contexts(self):
        name=OBSERVED[0]
        with self.assertRaises(ValueError):r.safe_path(name)
        with self.assertRaises(ValueError):r.tree_object({name:('100644','blob','a'*40)})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp).resolve()/'evidence.zip'
            with zipfile.ZipFile(path,'w') as archive:archive.writestr('evidence-index.json',b'{}');archive.writestr(name,b'synthetic')
            with self.assertRaises(ValueError):r.ArchiveFiles(path)
        files,tree=self.fixture();row=next(v for v in tree['entries'] if v['kind']=='file');row=dict(row,blob_path='blobs/sha256/aa/a::b')
        with self.assertRaises(ValueError):r.RawReplay(files,BOUNDS).raw_record(row)
    def test_duplicate_and_missing_ancestor_rows_remain_rejected(self):
        files,tree=self.fixture();tree['entries'].append(dict(tree['entries'][-1]))
        with self.assertRaisesRegex(ValueError,'duplicate'):r.RawReplay(files,BOUNDS).tree(tree)
        files,tree=self.fixture();tree['entries']=[v for v in tree['entries'] if v['path']!='usr/share/man']
        with self.assertRaisesRegex(ValueError,'ancestor'):r.RawReplay(files,BOUNDS).tree(tree)
    def test_colon_links_keep_containment_and_cycle_checks(self):
        files,tree=self.fixture();target='APR::Base64.3pm';name='usr/share/man/man3/alias::entry';content=target.encode()
        link=raw_record(content,path=name,source_path=SDK+'/'+name,mode='0777',target=target);link['kind']='symlink';tree['entries'].append(link);files[link['blob_path']]=content
        result=r.RawReplay(files,BOUNDS).tree(tree);self.assertEqual(result[name]['target'],target)
        for target in ('../../../../../escape','alias::entry'):
            content=target.encode();changed=raw_record(content,path=name,source_path=SDK+'/'+name,mode='0777',target=target);changed['kind']='symlink';tree['entries'][-1]=changed;files[changed['blob_path']]=content
            with self.subTest(target=target),self.assertRaises(ValueError):r.RawReplay(files,BOUNDS).tree(tree)

if __name__=='__main__':unittest.main()
