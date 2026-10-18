import copy,hashlib,json
from pathlib import Path
import unittest
import tempfile
import capture
from test_layout_capabilities import CapabilityFixture

gate=capture.video.layout_exports

def fixture():
    viewport=[0,0,400,800]
    root=dict(path=[],identifier='',label='App',elementType=2,frame=viewport,selected=False)
    bar=dict(path=[0],identifier='',label='Tab Bar',elementType=22,frame=[0,700,400,100],selected=False)
    livebar={k:v for k,v in bar.items() if k!='path'};livebar.update(exists=True,hittable=True)
    proof=dict(path=[0],ancestors=[root],snapshot=bar,observed=livebar)
    result=[]
    for i,title in enumerate(['Home','Apps','Sources','Settings']):
        snap=dict(path=[0,i],identifier='',label=title,elementType=9,frame=[i*100,710,100,50],selected=i==0)
        live={k:v for k,v in snap.items() if k!='path'};live.update(exists=True,hittable=True)
        result.append(dict(title=title,identifier='p1-tab-'+title,resolution='unique-native-tabbar-v1',barQueryCount=1,buttonQueryCount=4,queryCount=0,tabBar=copy.deepcopy(proof),viewport=viewport,snapshotComplete=True,snapshotNodeCount=10,selectedPath=[0,i],candidates=[dict(path=[0,i],ancestors=[root,bar],snapshot=snap,observed=live)]))
    return result

class StructuralTabs(unittest.TestCase):
    def test_valid_native_bar_preserves_empty_identifiers(self):
        rows=fixture();chosen=gate.validate_tab_inventory(rows)
        self.assertEqual([r['identifier'] for r in chosen],['']*4)
        self.assertEqual(gate.validate_tab_inventory(rows,chosen),chosen)
        with self.assertRaises(ValueError):gate.validate_tab_inventory(rows,require_nested=True)
    def test_rejects_ambiguity_and_changed_live_evidence(self):
        changes=[lambda r:r[0].update(barQueryCount=2),lambda r:r[0].update(buttonQueryCount=5),lambda r:r[0].update(queryCount=1),lambda r:r.reverse(),lambda r:r[0].update(selectedPath=[2]),lambda r:r[0]['candidates'][0]['observed'].update(identifier='invented'),lambda r:r[0]['candidates'][0]['observed'].update(hittable=False),lambda r:r[0]['candidates'][0]['observed'].update(frame=[0,0,10,10]),lambda r:r[0]['candidates'][0]['ancestors'][1].update(path=[4]),lambda r:r[0].update(snapshotComplete=False),lambda r:r[0].update(resolution='untrusted'),lambda r:r[0]['candidates'].append(copy.deepcopy(r[0]['candidates'][0]))]
        for change in changes:
            with self.subTest(change=change):
                rows=fixture();change(rows)
                with self.assertRaises(ValueError):gate.validate_tab_inventory(rows)
    def test_rejects_multiple_or_missing_selection(self):
        for selections in [[False]*4,[True]*4]:
            rows=fixture()
            for g,selected in zip(rows,selections):
                for name in ('snapshot','observed'):g['candidates'][0][name]['selected']=selected
            with self.assertRaises(ValueError):gate.validate_tab_inventory(rows)
    def test_focus_expects_original_failed_context(self):
        self.assertEqual(gate.CAPABILITY_METHODS['phone-default'],['testCapabilityNoBannerDefault'])
        self.assertEqual(gate.context('capability-default-tabs'),('none',False,False,'Home'))
        geometries,actions,screens=gate.capability_expected('phone-default')
        self.assertEqual(geometries,{'capability-default-tabs':('testCapabilityNoBannerDefault',False)})
        self.assertFalse(actions);self.assertEqual(set(screens),{'capability-default-tabs'})
    def test_end_to_end_focus_and_wrong_selection_rejected(self):
        class Focus(CapabilityFixture):
            def phone(self):
                self.geometry('capability-default-tabs')
                row=self.rows['capability-default-tabs'];row['tabCandidates']=fixture()
                row['tabs']=[g['candidates'][0]['observed'] for g in row['tabCandidates']]
        with tempfile.TemporaryDirectory() as tmp:
            f=Focus(Path(tmp),'phone-default');self.assertTrue(f.verify()['collection_complete'])
            for index,g in enumerate(f.rows['capability-default-tabs']['tabCandidates']):
                for name in ('snapshot','observed'):g['candidates'][0][name]['selected']=index==1
            with self.assertRaises(ValueError):f.verify()
    def test_no_partial_id_or_extra_nested_button_fallback(self):
        rows=fixture();rows[1]['candidates'][0]['snapshot']['identifier']='p1-tab-Apps';rows[1]['candidates'][0]['observed']['identifier']='p1-tab-Apps'
        with self.assertRaises(ValueError):gate.validate_tab_inventory(rows)
        rows=fixture();rows[2]['candidates'].append(copy.deepcopy(rows[2]['candidates'][0]))
        with self.assertRaises(ValueError):gate.validate_tab_inventory(rows)
    def test_swift_is_fail_closed_and_does_not_synthesize_ids(self):
        s=(Path(capture.HERE).parent/'video/recovery_ui_tests.swift').read_text()
        body=s[s.index('private func structuralTabSnapshot'):s.index('private func tabSnapshot')]
        for token in ['bars.count == 1','app.tabBars.count == 1','buttons.count == 4','actualBar.descendants(matching: .button).count == 4','buttons.map({ $0.snapshot.label }) == tabTitles','snapshot.identifier.isEmpty','buttons.filter({ $0.snapshot.isSelected }).count == 1','queryCount != 0','!agrees(node.snapshot, observed)']:self.assertIn(token,body)
        self.assertNotIn('observed["identifier"] =',body)
        self.assertIn('if nodes.isEmpty { return structuralTabSnapshot(app, root: root) }',s)

if __name__=='__main__':unittest.main()
