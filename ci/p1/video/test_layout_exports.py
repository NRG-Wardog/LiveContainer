import copy
import json
from pathlib import Path
import tempfile
import unittest
import capture
import layout_exports as layout

class LayoutExports(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.device='fixture'
        self.summary=dict(result='Passed',passedTests=4,failedTests=0,skippedTests=0,totalTestCount=4,expectedFailures=0,devicesAndConfigurations=[{'device':{'deviceId':self.device}}])
        self.tests={'testNodes':[dict(nodeType='Test Case',nodeIdentifier='P1RecoveryLayoutUITests/'+m+'()',result='Passed') for m in layout.METHODS]}
        self.manifest=[dict(testIdentifier='P1RecoveryLayoutUITests/'+m+'()',testIdentifierURL='test://com.apple.xcode/P0SignIn/P0SignInUITests/P1RecoveryLayoutUITests/'+m,attachments=[]) for m in layout.METHODS]
        self.rows={};self.count=0
        geometries,actions,screens=layout.expected()
        def observed(frame,label=''):return dict(exists=True,hittable=True,frame=frame,label=label)
        for name,(method,banner) in geometries.items():
            row=dict(schema='p1-layout-observation-v1',case=name,geometryPassed=True,bannerExpected=banner,navigationTitle='Home',
                viewport=observed([0,0,400,800]),navigationBar=observed([0,210,400,50]),
                tabs=[observed([i*100,750,90,40],label) for i,label in enumerate(['Home','Apps','Sources','Settings'])],
                region=observed([0,0,400,200]) if banner else dict(exists=False),content=observed([20,300,300,60]),admissionEligible=False)
            ctx=layout.context(name)
            row['navigationAction']=observed([330,215,60,40])
            if ctx:
                kind,largest,landscape,title=ctx
                row.update(expectedKind=kind,expectedLargest=largest,expectedLandscape=landscape,navigationTitle=title,
                    inheritedSizeCategory=dict(exists=True,accessibilityValue='sizeCategory=AX5' if largest else 'sizeCategory=default'),
                    expectedProductionIdentity=layout.IDENTITIES.get(kind),productionIdentity=observed([10,0,300,40],layout.IDENTITIES.get(kind,'')),
                    passiveCurrentKind=observed([20,300,300,50],kind))
                if landscape:
                    row.update(viewport=observed([0,0,800,400]),navigationBar=observed([0,130,800,50]),navigationAction=observed([730,135,60,40]),
                        tabs=[observed([i*100,350,90,40],label) for i,label in enumerate(['Home','Apps','Sources','Settings'])],
                        region=observed([0,0,800,120]) if banner else dict(exists=False),content=observed([20,200,300,60]))
            self.add(method,name+'-geometry',row);self.rows[name]=row
        for name,(method,callback) in actions.items():
            row=dict(schema='p1-layout-action-v1',case=name,driver='ordinary-XCTest-visible-coordinate-tap',scrollAttempts=1,
                button=observed([10,50,300,50]),visibleIntersection=[10,50,300,50],region=observed([0,0,400,200]),admissionEligible=False)
            self.add(method,name+'-input',row);self.rows[name+'-input']=row
            row=dict(schema='p1-layout-callback-v1',case=name,expected=callback,actual=observed([0,300,300,50],callback+':1'),admissionEligible=False)
            self.add(method,name+'-callback-value',row);self.rows[name+'-callback']=row
        for name,method in screens.items():self.add(method,name,b'PNG')
        self.save()
    def add(self,method,name,value):
        self.count+=1;filename=f'{self.count:03d}'+('.png' if isinstance(value,bytes) else '.json')
        if isinstance(value,bytes):(self.root/filename).write_bytes(value)
        else:value['_test_file']=filename
        self.manifest[layout.METHODS.index(method)]['attachments'].append(dict(deviceId=self.device,exportedFileName=filename,suggestedHumanReadableName=name+'_0'+Path(filename).suffix))
        if not isinstance(value,bytes):
            # Additional bookkeeping is outside the diagnostic data file.
            self.rows[filename]=value
    def save(self):
        for k,row in self.rows.items():
            if '_test_file' in row:
                value={key:value for key,value in row.items() if key!='_test_file'}
                (self.root/row['_test_file']).write_text(json.dumps(value))
        (self.root/'manifest.json').write_text(json.dumps(self.manifest))
    def verify(self):
        self.save();return layout.verify(self.root,self.summary,self.tests,self.device,capture.parse,capture.ordinary,lambda b:b==b'PNG')
    def test_full_matrix(self):
        r=self.verify();self.assertEqual(r['action_count'],21);self.assertEqual(r['geometry_count'],48);self.assertFalse(r['admissionEligible'])
    def test_retained_portrait_and_standard_banner_matches_swift(self):
        # Independent fixture semantics, not values derived from expected().
        swift=(Path(__file__).parent/'recovery_ui_tests.swift').read_text()
        for name,largest in [('transition-portrait',True),('transition-standard-with-banner',False)]:
            self.assertRegex(swift,r'checkGeometry\(app, banner: true, title: "Details", expectedKind: "operation", expectedLargest: '+str(largest).lower()+r', expectedLandscape: false, name: "'+name+r'"\)')
            row=self.rows[name]
            row.update(bannerExpected=True,region=dict(exists=True,hittable=True,frame=[0,0,400,200]))
        self.assertTrue(self.verify()['collection_complete'])
    def test_retained_transitions_reject_missing_banner(self):
        for name in ['transition-portrait','transition-standard-with-banner']:
            with self.subTest(name=name):
                row=self.rows[name];original=copy.deepcopy(row)
                row.update(bannerExpected=False,region={'exists':False})
                with self.assertRaisesRegex(ValueError,'layout geometry'):self.verify()
                row.clear();row.update(original)
    def test_duplicate_screenshot_name(self):
        row=next(x for x in self.manifest[0]['attachments'] if x['exportedFileName'].endswith('.png'))
        duplicate=copy.deepcopy(row);duplicate['exportedFileName']='duplicate.png'
        (self.root/'duplicate.png').write_bytes(b'PNG');self.manifest[0]['attachments'].append(duplicate)
        with self.assertRaisesRegex(ValueError,'duplicate layout screenshot name'):self.verify()
    def test_missing_method(self):
        self.tests['testNodes'].pop()
        with self.assertRaises(ValueError):self.verify()
    def test_boolean_count(self):
        self.summary['failedTests']=False
        with self.assertRaises(ValueError):self.verify()
    def test_missing_branch_geometry(self):
        self.rows['layout-direct-AX5-landscape']['geometryPassed']=False
        with self.assertRaises(ValueError):self.verify()
    def test_top_tab_overlap(self):
        self.rows['layout-operation-AX5-portrait']['tabs'][0]['frame']=[0,100,90,40]
        with self.assertRaisesRegex(ValueError,'covers navigation'):self.verify()
    def test_banner_navigation_overlap(self):
        self.rows['layout-operation-default-portrait']['region']['frame']=[0,0,400,240]
        with self.assertRaises(ValueError):self.verify()
    def test_clipped_control(self):
        self.rows['layout-operation-AX5-landscape-resume-input']['visibleIntersection']=[10,50,300,10]
        with self.assertRaisesRegex(ValueError,'clipped'):self.verify()
    def test_wrong_callback(self):
        self.rows['layout-unreadable-default-portrait-copy-callback']['actual']['label']='none'
        with self.assertRaises(ValueError):self.verify()
    def test_missing_no_banner(self):
        self.rows['layout-none-default-portrait']['region']={'exists':True,'frame':[0,0,400,200]}
        with self.assertRaises(ValueError):self.verify()
    def test_wrong_attachment_method(self):
        row=self.manifest[0]['attachments'].pop();self.manifest[1]['attachments'].append(row)
        with self.assertRaises(ValueError):self.verify()
    def test_reused_attachment(self):
        self.manifest[0]['attachments'].append(copy.deepcopy(self.manifest[0]['attachments'][0]))
        with self.assertRaises(ValueError):self.verify()
    def test_hidden_tab(self):
        self.rows['transition-shown']['tabs'][0]['hittable']=False
        with self.assertRaises(ValueError):self.verify()
    def test_wrong_actual_size(self):
        self.rows['transition-standard-with-banner']['inheritedSizeCategory']['accessibilityValue']='sizeCategory=AX5'
        with self.assertRaisesRegex(ValueError,'text size'):self.verify()
    def test_ignored_rotation(self):
        self.rows['transition-rotated']['viewport']['frame']=[0,0,900,1000]
        with self.assertRaisesRegex(ValueError,'orientation'):self.verify()
    def test_wrong_actual_kind(self):
        self.rows['transition-kind-direct']['passiveCurrentKind']['label']='operation'
        with self.assertRaisesRegex(ValueError,'fixture kind'):self.verify()
    def test_wrong_actual_banner_title(self):
        self.rows['layout-direct-default-portrait']['productionIdentity']['label']='unrelated'
        with self.assertRaisesRegex(ValueError,'banner identity'):self.verify()
    def test_bad_callback_counter(self):
        row=self.rows['layout-direct-default-portrait-inspect-callback'];row['actual']['label']=row['expected']+':0'
        with self.assertRaises(ValueError):self.verify()

if __name__=='__main__':unittest.main()
