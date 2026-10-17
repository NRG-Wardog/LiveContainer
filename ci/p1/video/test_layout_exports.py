import copy
import json
import struct
from pathlib import Path
import tempfile
import unittest
import layout_exports as layout
import capture

def metric(viewport,region=None,selected=0):
    x,y,w,h=viewport;offered=[x,y+20,w,h-40]
    out=dict(schema='p1-layout-metrics-v1',complete=True,applicationActive=True,viewCount=10,selectedTab=selected,
        startedUptime=1.0,finishedUptime=1.001,windowBounds=viewport,offeredFrame=offered,offeredSize=offered[2:],
        interfaceOrientation=3 if w>h else 1,screenScale=1,scrollViews=[],observationSequence=2,
        processSession='fixture-session',windowObservationID='fixture-window')
    if region:
        safe=[region[0],region[1]+20,region[2],region[3]-20]
        out['scrollViews']=[dict(path='window/0',view=dict(frame=region,bounds=region,localToWindow=[1,0,0,1,0,0],hidden=False,alpha=1.0),scrollEnabled=True,
            ancestors=[dict(frame=viewport,bounds=viewport,localToWindow=[1,0,0,1,0,0],hidden=False,alpha=1.0,clips=True)],clippedBounds=region,
            safeAreaFrame=safe,localSafeAreaFrame=safe,safeAreaInsets=[20,0,0,0],safeClippingViewport=safe)]
    previous=copy.deepcopy(out);previous['observationSequence']=1
    out.update(causalPrevious=previous,probeValueReadCount=2,runnerRequestBracket=[10,10.1])
    return out

def png(width,height):return b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\x0dIHDR'+struct.pack('>II',width,height)

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
            row.update(predicateFailures=[],screenshotSource='XCUIScreen.main',layoutMetrics=metric(row['viewport']['frame'],row['region'].get('frame')))
            for t in row['tabs']:t.update(identifier='p1-tab-'+t['label'],elementType=9,selected=t['label']=='Home')
            row['tabCandidates']=[dict(title=t['label'],identifier=t['identifier'],candidates=[copy.deepcopy(t)]) for t in row['tabs']]
            self.add(method,name+'-geometry',row);self.rows[name]=row
        for name,(method,callback) in actions.items():
            row=dict(schema='p1-layout-action-v1',case=name,driver='ordinary-XCTest-visible-coordinate-tap',scrollAttempts=1,
                button=observed([10,50,300,50]),visibleIntersection=[10,50,300,50],region=observed([0,0,400,200]),admissionEligible=False)
            row.update(layoutMetrics=metric([0,0,400,800],row['region']['frame']),clippingViewport=[0,20,400,180])
            self.add(method,name+'-input',row);self.rows[name+'-input']=row
            row=dict(schema='p1-layout-callback-v1',case=name,expected=callback,actual=observed([0,300,300,50],callback+':1'),admissionEligible=False)
            self.add(method,name+'-callback-value',row);self.rows[name+'-callback']=row
        for name,selected in [('transition-apps-tab',1),('transition-home-tab',0)]:
            row=dict(schema='p1-layout-tab-selection-v1',case=name,expectedTab=selected,driver='ordinary-XCTest-tap',
                actual=metric([0,0,400,800],selected=selected),control=dict(exists=True,hittable=True,identifier='p1-tab-'+('Apps' if selected else 'Home')),
                content=dict(exists=True),admissionEligible=False)
            self.add(layout.METHODS[3],name+'-selection',row);self.rows[name+'-selection']=row
        for name,method in screens.items():
            landscape='landscape' in name or layout.context(name) and layout.context(name)[2]
            viewport=[0,0,800,400] if landscape else [0,0,400,800]
            selected=1 if name=='transition-apps-tab' else 0
            self.add(method,name,png(viewport[2],viewport[3]))
            row=dict(schema='p1-layout-screen-v1',case=name,source='XCUIScreen.main',pixelWidth=viewport[2],pixelHeight=viewport[3],
                imageOrientation=0,viewport=observed(viewport),metrics=metric(viewport,selected=selected),admissionEligible=False)
            self.add(method,name+'-screen-receipt',row);self.rows[name+'-screen']=row
        receipt=metric([0,0,400,800],[0,0,400,200])
        drag=dict(schema='p1-layout-drag-v1',case='layout-interior-drag-1',viewport=[0,0,400,800],metrics=receipt,
            element=dict(frame=[0,0,400,200],identifier='v3.recovery.region'),visibleBounds=[0,20,400,180],interiorBounds=[12,32,376,156],
            start=[200,71],end=[200,149],admissionEligible=False)
        self.add(layout.METHODS[0],'drag-input',drag);self.rows['drag']=drag
        after=dict(schema='p1-layout-drag-after-v1',case='layout-interior-drag-1',foreground=True,metrics=receipt,
            viewport=dict(frame=[0,0,400,800]),admissionEligible=False)
        self.add(layout.METHODS[0],'drag-after',after);self.rows['drag-after']=after
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
        self.save();return layout.verify(self.root,self.summary,self.tests,self.device,capture.parse,capture.ordinary,lambda b:b.startswith(b'\x89PNG'))
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
        (self.root/'duplicate.png').write_bytes((self.root/row['exportedFileName']).read_bytes());self.manifest[0]['attachments'].append(duplicate)
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
        row=self.rows['layout-operation-AX5-portrait'];row['tabs'][0]['frame']=[0,100,90,40];row['tabCandidates'][0]['candidates'][0]['frame']=[0,100,90,40]
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
        with self.assertRaises(ValueError):self.verify()
    def test_wrong_actual_kind(self):
        self.rows['transition-kind-direct']['passiveCurrentKind']['label']='operation'
        with self.assertRaisesRegex(ValueError,'fixture kind'):self.verify()
    def test_wrong_actual_banner_title(self):
        self.rows['layout-direct-default-portrait']['productionIdentity']['label']='unrelated'
        with self.assertRaisesRegex(ValueError,'banner identity'):self.verify()
    def test_bad_callback_counter(self):
        row=self.rows['layout-direct-default-portrait-inspect-callback'];row['actual']['label']=row['expected']+':0'
        with self.assertRaises(ValueError):self.verify()
    def test_ambiguous_scroll_correspondence(self):
        metrics=self.rows['layout-operation-AX5-portrait']['layoutMetrics'];metrics['scrollViews'].append(copy.deepcopy(metrics['scrollViews'][0]))
        with self.assertRaisesRegex(ValueError,'ambiguous recovery'):self.verify()
    def test_tampered_clipping_ancestry(self):
        metrics=self.rows['layout-operation-AX5-portrait']['layoutMetrics'];metrics['scrollViews'][0]['ancestors'][0]['frame']=[0,0,300,800]
        with self.assertRaisesRegex(ValueError,'ancestor'):self.verify()
    def test_wrong_ancestry_depth(self):
        self.rows['layout-operation-AX5-portrait']['layoutMetrics']['scrollViews'][0]['path']='window/0/1'
        with self.assertRaisesRegex(ValueError,'ancestry depth'):self.verify()
    def test_hidden_scroll_ancestor(self):
        self.rows['layout-operation-AX5-portrait']['layoutMetrics']['scrollViews'][0]['ancestors'][0]['hidden']=True
        with self.assertRaisesRegex(ValueError,'hidden clipping'):self.verify()
    def test_tampered_safe_area_constant(self):
        metrics=self.rows['layout-operation-AX5-portrait']['layoutMetrics'];row=metrics['scrollViews'][0]
        row['safeAreaInsets']=[100,0,0,0]
        with self.assertRaisesRegex(ValueError,'guide/insets'):self.verify()
    def test_tampered_safe_area_conversion(self):
        self.rows['layout-operation-AX5-portrait']['layoutMetrics']['scrollViews'][0]['safeAreaFrame']=[0,20,400,100]
        with self.assertRaisesRegex(ValueError,'coordinate conversion'):self.verify()
    def test_nonrectilinear_transform(self):
        self.rows['layout-operation-AX5-portrait']['layoutMetrics']['scrollViews'][0]['view']['localToWindow']=[1,.5,0,1,0,0]
        with self.assertRaisesRegex(ValueError,'non-rectilinear'):self.verify()
    def test_measured_cap_remains_strict(self):
        m=metric([0,0,400,800],[0,0,400,400])
        with self.assertRaisesRegex(ValueError,'exceeds cap'):layout.clipping_viewport(m,[0,0,400,800],[0,0,400,400])
    def test_raw_AX_safe_area_is_not_counted_as_capped_content(self):
        # Full AX region 340 exceeds 320, but measured safe viewport is 280;
        # its actual offered parent is 760, giving a strict 304-point cap.
        m=metric([0,0,400,800],[0,0,400,340]);r=m['scrollViews'][0]
        r.update(safeAreaInsets=[60,0,0,0],localSafeAreaFrame=[0,60,400,280],safeAreaFrame=[0,60,400,280],safeClippingViewport=[0,60,400,280])
        self.assertEqual(layout.clipping_viewport(m,[0,0,400,800],[0,0,400,340]),[0,60,400,280])
    def test_offered_parent_cannot_be_inflated(self):
        m=self.rows['layout-operation-AX5-portrait']['layoutMetrics'];m['offeredSize']=[400,900]
        with self.assertRaises(ValueError):self.verify()
    def test_content_size_cannot_authorize_cap(self):
        m=metric([0,0,400,800],[0,0,400,400]);m['scrollViews'][0]['contentSize']=[400,1]
        with self.assertRaisesRegex(ValueError,'exceeds cap'):layout.clipping_viewport(m,[0,0,400,800],[0,0,400,400])
    def test_missing_tab_candidates(self):
        self.rows['layout-none-default-portrait'].pop('tabCandidates')
        with self.assertRaisesRegex(ValueError,'inventory'):self.verify()
    def test_ambiguous_tab_candidates(self):
        c=self.rows['layout-none-default-portrait']['tabCandidates'][0];c['candidates'].append(copy.deepcopy(c['candidates'][0]))
        with self.assertRaisesRegex(ValueError,'ambiguous actual tab'):self.verify()
    def test_tab_identity_is_not_sufficient_without_actual_selection(self):
        row=self.rows['transition-apps-tab-selection'];row['actual']['selectedTab']=0
        with self.assertRaisesRegex(ValueError,'selected tab'):self.verify()
    def test_tab_selection_requires_destination_content(self):
        self.rows['transition-home-tab-selection']['content']['exists']=False
        with self.assertRaisesRegex(ValueError,'tab content'):self.verify()
    def test_unsafe_drag_endpoint(self):
        self.rows['drag']['start']=[200,5]
        with self.assertRaisesRegex(ValueError,'unsafe area'):self.verify()
    def test_drag_margin_cannot_be_removed(self):
        self.rows['drag']['interiorBounds']=[0,20,400,180]
        with self.assertRaisesRegex(ValueError,'edge margin'):self.verify()
    def test_drag_must_stay_in_measured_region(self):
        self.rows['drag']['visibleBounds']=[0,0,400,200]
        with self.assertRaisesRegex(ValueError,'outside'):self.verify()
    def test_drag_foreground_contamination(self):
        self.rows['drag-after']['foreground']=False
        with self.assertRaisesRegex(ValueError,'foreground'):self.verify()
    def test_drag_viewport_contamination(self):
        self.rows['drag-after']['viewport']['frame']=[0,110,134,291]
        with self.assertRaises(ValueError):self.verify()
    def test_missing_drag_after_receipt(self):
        self.rows['drag-after']['case']='different'
        with self.assertRaisesRegex(ValueError,'foreground'):self.verify()
    def test_cached_getter_receipt(self):
        m=self.rows['layout-none-default-portrait']['layoutMetrics'];m['observationSequence']=m['causalPrevious']['observationSequence']
        with self.assertRaisesRegex(ValueError,'noncausal'):self.verify()
    def test_getter_session_changes(self):
        self.rows['layout-none-default-portrait']['layoutMetrics']['causalPrevious']['processSession']='other'
        with self.assertRaisesRegex(ValueError,'session/window'):self.verify()
    def test_getter_window_changes(self):
        self.rows['layout-none-default-portrait']['layoutMetrics']['causalPrevious']['windowObservationID']='other'
        with self.assertRaisesRegex(ValueError,'session/window'):self.verify()
    def test_getter_orientation_changes(self):
        self.rows['layout-none-default-portrait']['layoutMetrics']['causalPrevious']['interfaceOrientation']=3
        with self.assertRaisesRegex(ValueError,'orientation'):self.verify()
    def test_missing_request_duration(self):
        self.rows['layout-none-default-portrait']['layoutMetrics'].pop('runnerRequestBracket')
        with self.assertRaisesRegex(ValueError,'request-duration'):self.verify()
    def test_app_and_runner_clocks_need_not_match(self):
        m=self.rows['layout-none-default-portrait']['layoutMetrics'];m['runnerRequestBracket']=[900000,900000.4]
        self.assertTrue(self.verify()['collection_complete'])
    def test_missing_full_screen_receipt(self):
        self.rows['layout-none-default-portrait-screen']['source']='app.screenshot'
        with self.assertRaisesRegex(ValueError,'full screen'):self.verify()
    def test_cropped_screenshot_is_rejected(self):
        self.rows['layout-none-default-portrait-screen']['pixelHeight']=400
        with self.assertRaisesRegex(ValueError,'dimensions'):self.verify()
    def test_screenshot_orientation_required(self):
        self.rows['layout-none-default-portrait-screen'].pop('imageOrientation')
        with self.assertRaisesRegex(ValueError,'orientation'):self.verify()
    def test_input_uses_measured_clipping_not_raw_AX(self):
        row=self.rows['layout-operation-default-portrait-resume-input'];row['visibleIntersection']=[10,0,300,50];row['button']['frame']=[10,0,300,50]
        with self.assertRaisesRegex(ValueError,'clipping viewport'):self.verify()

if __name__=='__main__':unittest.main()
