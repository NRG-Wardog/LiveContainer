"""Tiny inert failure-log export fixtures; no native code or external requests."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import failure_summary as f
from inventory import sha
class FailureSummaryTests(unittest.TestCase):
 def fixture(self,root):
  root.mkdir();rows={'provenance/result.json':json.dumps(dict(status='FAILED_OR_INCOMPLETE',writers_quiescent=True,run={'run_id':1},approved_inputs_sha256='1'*64,source_seal_sha256='2'*64)).encode(),'provenance/owned-command-groups.json':b'[{"quiescent":true,"pipesJoined":true,"leaderReaped":true,"errors":[]}]','provenance/reviewed-inputs.json':b'{}','logs/host-run-diagnostic-checks.exit-code.txt':b'1\n','logs/host-run-diagnostic-checks.stderr.log':b'compiler diagnostic','host-tests/run-diagnostic-checks/0013.stderr':b'sandbox_apply: Operation not permitted','host-tests/run-diagnostic-checks/0013.command.json':b'{"argv":["swiftc"]}','host-tests/run-diagnostic-checks/0013.result.json':b'{"returncode":1}','raw/secret-binary':b'not in diagnostic view','host-tests/run-diagnostic-checks/0013.before.json':b'not a raw stream'}
  for name,raw in rows.items():p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
  self.index(root)
 def index(self,root):
  index={str(p.relative_to(root)):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file() and p.name!='evidence-index.json'}
  (root/'evidence-index.json').write_text(json.dumps(index));return index
 def test_only_bounded_complete_original_logs_are_copied(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();self.fixture(root/'evidence');value=f.export(root/'evidence',root/'summary');self.assertTrue(value['created'])
   manifest=json.loads((root/'summary/failure-summary-manifest.json').read_text());self.assertTrue(manifest['full_immutable_evidence_required']);self.assertEqual(manifest['purpose'],'DIAGNOSTIC_VIEW_ONLY_NOT_FINAL_REPLAY_EVIDENCE')
   for row in manifest['files']:self.assertEqual((root/'summary'/row['path']).read_bytes(),(root/'evidence'/row['path']).read_bytes())
   self.assertFalse((root/'summary/raw').exists());self.assertFalse((root/'summary/host-tests/run-diagnostic-checks/0013.before.json').exists())
 def test_oversized_stream_is_explicitly_omitted_never_truncated(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();self.fixture(root/'evidence');(root/'evidence/host-tests/run-diagnostic-checks/0013.stderr').write_bytes(b'x'*(f.MAX_FILE_BYTES+1));self.index(root/'evidence');value=f.export(root/'evidence',root/'summary');self.assertEqual(value['omitted'],1)
   manifest=json.loads((root/'summary/failure-summary-manifest.json').read_text());self.assertEqual(manifest['omitted'][0]['observed_bytes'],f.MAX_FILE_BYTES+1);self.assertFalse((root/'summary/host-tests/run-diagnostic-checks/0013.stderr').exists())
 def test_unsettled_mutated_or_symlinked_evidence_rejects(self):
  for mode in ('unsettled','mutated','symlink'):
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp).resolve();self.fixture(root/'evidence');p=root/'evidence/host-tests/run-diagnostic-checks/0013.stderr'
    if mode=='mutated':p.write_bytes(b'changed')
    elif mode=='symlink':p.unlink();p.symlink_to(root/'evidence/logs/host-run-diagnostic-checks.stderr.log')
    else:
     p=root/'evidence/provenance/result.json';x=json.loads(p.read_text());x['writers_quiescent']=False;p.write_text(json.dumps(x));self.index(root/'evidence')
    with self.assertRaises(ValueError):f.export(root/'evidence',root/'summary')
    self.assertFalse((root/'summary').exists())
 def test_success_creates_no_failure_view(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();self.fixture(root/'evidence');p=root/'evidence/provenance/result.json';x=json.loads(p.read_text());x['status']='CAPTURED_FOR_INDEPENDENT_REVIEW';p.write_text(json.dumps(x));self.index(root/'evidence')
   self.assertFalse(f.export(root/'evidence',root/'summary')['created']);self.assertFalse((root/'summary').exists())
 def test_count_total_index_bounds_and_existing_output_fail_closed(self):
  for bound in ('MAX_FILES','MAX_TOTAL_BYTES','MAX_INDEX_BYTES'):
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp).resolve();self.fixture(root/'evidence')
    with patch.object(f,bound,1),self.assertRaises(ValueError):f.export(root/'evidence',root/'summary')
    self.assertFalse((root/'summary').exists())
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();self.fixture(root/'evidence');(root/'summary').mkdir()
   with self.assertRaises(ValueError):f.export(root/'evidence',root/'summary')
if __name__=='__main__':unittest.main()
