"""Synthetic binary fixtures only; never native linking or execution evidence."""
import hashlib,io,plistlib,struct,sys,tempfile,unittest,zipfile
from unittest import mock
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import macho_contract as m

def fixture(*,cpu=0x0100000c,subtype=0,platform=2,filetype=2,extra=b''):
    size=72+24+24+len(extra);entry=32+size;length=entry+16
    segment=struct.pack('<2I16s4Q4I',0x19,72,b'__TEXT',0x100000000,length,0,length,5,5,0,0)
    version=struct.pack('<6I',0x32,24,platform,15<<16,26<<16,0)
    main=struct.pack('<2I2Q',0x80000028,24,entry,0)
    return struct.pack('<8I',0xfeedfacf,cpu,subtype,filetype,3+bool(extra),size,0,0)+segment+version+main+extra+b'\0'*16
class MachOTests(unittest.TestCase):
    def test_exact_arm64_ios_unsigned_product_is_only_read(self):
        report=m.inspect_executable(fixture());self.assertEqual(report['architecture'],'arm64');self.assertEqual(report['platform'],'iOS');self.assertTrue(report['unsigned']);self.assertFalse(report['executed'])
    def test_wrong_platform_architecture_subtype_and_type_reject(self):
        for raw in (fixture(cpu=0x01000007),fixture(subtype=2),fixture(platform=1),fixture(platform=7),fixture(filetype=6)):
            with self.assertRaises(ValueError):m.inspect_executable(raw)
    def test_truncation_fat_endian_sizes_and_command_counts_reject(self):
        good=fixture()
        for raw in (good[:31],good[:-17],b'\xca\xfe\xba\xbe'+good[4:],b'\xfe\xed\xfa\xcf'+good[4:],good[:16]+struct.pack('<I',4000)+good[20:],good[:20]+struct.pack('<I',0xffffffff)+good[24:],good[:36]+struct.pack('<I',7)+good[40:]):
            with self.assertRaises(ValueError):m.inspect_executable(raw)
    def test_missing_duplicate_or_malformed_build_and_code_signature_reject(self):
        good=fixture()
        for raw in (good[:104]+struct.pack('<I',0x31)+good[108:],fixture(extra=struct.pack('<6I',0x32,24,2,15<<16,26<<16,0)),fixture(extra=struct.pack('<4I',0x1d,16,0,0)),good[:124]+struct.pack('<I',1)+good[128:]):
            with self.assertRaises(ValueError):m.inspect_executable(raw)
    def test_entrypoint_and_text_extent_reject(self):
        good=fixture()
        for raw in (good[:136]+struct.pack('<Q',1)+good[144:],good[:72]+struct.pack('<Q',0xffffffffffffffff)+good[80:],good[:40]+b'__OTHER\0'+good[48:]):
            with self.assertRaises(ValueError):m.inspect_executable(raw)
    def test_actual_info_plist_selects_safe_regular_executable(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve()/'Synthetic.app';root.mkdir();(root/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'Synthetic'}));(root/'Synthetic').write_bytes(fixture())
            self.assertEqual(m.inspect_app(root)['executable'],'Synthetic')
            for name in ('../outside','/absolute','..'):
                (root/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':name}))
                with self.assertRaises(ValueError):m.inspect_app(root)

    def test_embedded_framework_actual_plist_and_extra_macho_are_inspected(self):
        # A synthetic dylib has no LC_MAIN. It remains a static parser fixture.
        raw=fixture();raw=raw[:12]+struct.pack('<I',6)+raw[16:]
        raw=raw[:16]+struct.pack('<2I',2,96)+raw[24:128]+raw[152:]
        # Update __TEXT file length after removing LC_MAIN.
        raw=raw[:80]+struct.pack('<Q',len(raw))+raw[88:]
        files={'Info.plist':plistlib.dumps({'CFBundleExecutable':'Renamed'}),'Renamed':fixture(),
            'Frameworks/Good.framework/Info.plist':plistlib.dumps({'CFBundleExecutable':'Actual'}),'Frameworks/Good.framework/Actual':raw}
        result=m._inspect_files(files,root_bundle='')
        self.assertEqual(result['selected_bundle_executables'][''],'Renamed')
        self.assertEqual(result['binaries']['Frameworks/Good.framework/Actual']['filetype'],'MH_DYLIB')
        files['extra.dylib']=fixture(platform=7)
        with self.assertRaises(ValueError):m._inspect_files(files,root_bundle='')

    def test_preexisting_signature_is_not_a_general_signature_bypass(self):
        raw=fixture(extra=struct.pack('<4I',0x1d,16,168,16))
        with self.assertRaisesRegex(ValueError,'only exact reviewed prebuilt'):m.inspect_binary(raw,preexisting_signature=True)
        with self.assertRaises(ValueError):m.inspect_executable(raw)

    def test_product_symlink_and_unbound_signature_resource_reject(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve()/'A.app';root.mkdir();(root/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'A'}));(root/'A').write_bytes(fixture())
            (root/'link').symlink_to(root/'A')
            with self.assertRaises(ValueError):m.inspect_app(root)
            (root/'link').unlink();(root/'_CodeSignature').mkdir();(root/'_CodeSignature/CodeResources').write_bytes(b'synthetic')
            with self.assertRaises(ValueError):m.inspect_app(root)

    def test_internal_ipa_is_read_without_extracting_or_executing(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t).resolve()/'internal.ipa'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('Payload/A.app/Info.plist',plistlib.dumps({'CFBundleExecutable':'A'}));z.writestr('Payload/A.app/A',fixture())
            proof=m.inspect_internal_ipa(path);self.assertFalse(proof['executed']);self.assertFalse(proof['distributed']);self.assertFalse((path.parent/'Payload').exists())
            with zipfile.ZipFile(path,'w') as z:z.writestr('../escape',b'x')
            with self.assertRaises(ValueError):m.inspect_internal_ipa(path)
if __name__=='__main__':unittest.main(verbosity=2)
