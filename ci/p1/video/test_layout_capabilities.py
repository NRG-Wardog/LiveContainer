"""Synthetic verifier and source contracts. Never native capability evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import capture
import layout_exports as gate
from test_layout_exports import metric, inventory, png


def observed(frame,label='',identifier='',selected=False):
    return dict(exists=True,hittable=True,frame=frame,label=label,identifier=identifier,selected=selected,elementType=9)


class CapabilityFixture:
    def __init__(self,root,device_class):
        self.root=root;self.device_class=device_class;self.methods=gate.CAPABILITY_METHODS[device_class]
        self.rows={};self.files={};self.ordinal=0;self.current=self.methods[0]
        self.manifest=[dict(testIdentifier='P1RecoveryLayoutUITests/'+m+'()',testIdentifierURL='test://com.apple.xcode/P0SignIn/P0SignInUITests/P1RecoveryLayoutUITests/'+m,attachments=[]) for m in self.methods]
        self.summary=dict(result='Passed',passedTests=len(self.methods),failedTests=0,skippedTests=0,totalTestCount=len(self.methods),expectedFailures=0,devicesAndConfigurations=[{'device':{'deviceId':'synthetic'}}])
        self.tests={'testNodes':[dict(nodeType='Test Case',nodeIdentifier='P1RecoveryLayoutUITests/'+m+'()',result='Passed') for m in self.methods]}
        if device_class=='tablet':self.tablet()
        else:self.phone()

    def add(self,name,row,display_name=None):
        self.ordinal+=1;filename=str(self.ordinal)+('.png' if isinstance(row,bytes) else '.json')
        self.manifest[self.methods.index(self.current)]['attachments'].append(dict(deviceId='synthetic',exportedFileName=filename,suggestedHumanReadableName=(display_name or name)+'_0'+Path(filename).suffix))
        self.rows[name]=row;self.files[name]=filename
        return row

    def metrics(self,kind='none',largest=False,landscape=False,selected=0,offset=0,details=False):
        viewport=[0,0,800,400] if landscape else [0,0,400,800]
        region=[0,0,800,120] if landscape else [0,0,400,200]
        m=metric(viewport,region if kind!='none' else None,selected=selected,kind=kind,largest=largest)
        if kind!='none':m['scrollViews'][0]['contentOffset']=[0,offset]
        if details:
            row=metric(viewport,[0,180,800,160],kind=kind,largest=largest)['scrollViews'][0]
            row['path']='window/1';m['scrollViews'].append(row)
        m['causalPrevious']['scrollViews']=copy.deepcopy(m['scrollViews'])
        return m

    def tabs(self,landscape=False,selected=0):
        return [observed([i*100,350 if landscape else 750,90,40],title,'p1-tab-'+title,i==selected) for i,title in enumerate(['Home','Apps','Sources','Settings'])]

    def screen(self,name,m):
        vp=m['windowBounds'];self.add(name+'-pixels',png(vp[2],vp[3]),display_name=name)
        row=dict(schema='p1-layout-screen-v1',case=name,source='XCUIScreen.main',pixelWidth=vp[2],pixelHeight=vp[3],imageOrientation=0,viewport=observed(vp),
                 metrics=self.metrics(m['recoveryKind'],m['largestText'],vp[2]>vp[3],m['selectedTab']),admissionEligible=False)
        self.add(name+'-screen',row)

    def geometry(self,name,kind='none',largest=False,landscape=False,title='Home'):
        m=self.metrics(kind,largest,landscape);vp=m['windowBounds'];tabs=self.tabs(landscape)
        row=dict(schema='p1-layout-observation-v1',case=name,geometryPassed=True,bannerExpected=kind!='none',navigationTitle=title,
                 predicateFailures=[],screenshotSource='XCUIScreen.main',layoutMetrics=m,expectedKind=kind,expectedLargest=largest,expectedLandscape=landscape,
                 viewport=observed(vp),navigationBar=observed([0,130 if landscape else 210,vp[2],50]),navigationAction=observed([vp[2]-70,135 if landscape else 215,60,40]),
                 inheritedSizeCategory=dict(exists=True,accessibilityValue='sizeCategory=AX5' if largest else 'sizeCategory=default'),
                 expectedProductionIdentity=gate.IDENTITIES.get(kind),productionIdentity=observed([10,0,300,40],gate.IDENTITIES.get(kind,'')),
                 passiveCurrentKind=observed([20,230,300,50],kind),content=observed([20,200 if landscape else 300,300,60]),tabs=tabs,
                 tabCandidates=inventory(tabs,vp,nested=self.device_class=='tablet'),region=observed([0,0,vp[2],120 if landscape else 200]) if kind!='none' else dict(exists=False),admissionEligible=False)
        self.add(name,row);self.screen(name,m);return m

    def tablet(self):
        self.geometry('capability-tabs-initial')
        before=self.metrics();apps=self.metrics(selected=1)
        for name,selected,prior,current in [('capability-tabs-apps',1,before,apps),('capability-tabs-home',0,apps,self.metrics())]:
            control=self.tabs(selected=selected)[selected]
            row=dict(schema='p1-layout-tab-selection-v1',case=name,expectedTab=selected,before=prior,actual=current,tabCandidates=inventory(self.tabs(selected=1-selected),current['windowBounds'],nested=True),
                     controlBefore=self.tabs(selected=1-selected)[selected],control=control,content=observed([20,230,300,50],'Synthetic Apps content' if selected else 'Synthetic destination'),driver='ordinary-XCTest-tap',admissionEligible=False)
            self.add(name+'-selection',row);self.screen(name,current)
        self.geometry('capability-tabs-returned',title='Details')
        self.current=self.methods[1]
        self.geometry('capability-rotation-portrait');self.geometry('capability-rotation-landscape',landscape=True);self.geometry('capability-rotation-returned')

    def target(self,search,attempt,target,m,element,clip,offset,path):
        return self.add(search+'-target-'+str(attempt),dict(schema='p1-layout-target-v1',case=search+'-target-'+str(attempt),search=search,attempt=attempt,target=copy.deepcopy(target),element=element,layoutMetrics=m,scrollPath=path,clippingViewport=clip,offset=offset,admissionEligible=False))

    def phone(self):
        self.geometry('capability-targets-initial','operation',True,True)
        element=observed([0,0,800,120],identifier='v3.recovery.region');clip=[0,20,800,100]
        target=observed([10,140,300,50],'Resume Status Check')
        name='capability-targets-resume'
        self.target(name,0,target,self.metrics('operation',True,True),element,clip,[0,0],'window/0')
        m=self.metrics('operation',True,True)
        drag=dict(schema='p1-layout-drag-v1',case='drag-1',metrics=m,viewport=m['windowBounds'],element=element,visibleBounds=clip,interiorBounds=[12,32,776,76],
                  start=[400,87],end=[400,53],direction='up',driver='ordinary-XCTest-controlled-coordinate-drag',velocity=80,pressDuration=.05,holdDuration=.2,
                  navigationBars=[observed([0,130,800,50])],tabs=self.tabs(True),scrollPath='window/0',offsetBefore=[0,0],target=copy.deepcopy(target),search=name,attempt=0,admissionEligible=False)
        self.add('drag',drag)
        target['frame']=[10,70,300,50]
        self.add('drag-after',dict(schema='p1-layout-drag-after-v1',case='drag-1',metrics=self.metrics('operation',True,True,offset=70),viewport=observed([0,0,800,400]),foreground=True,
                                  scrollPath='window/0',offsetAfter=[0,70],offsetDelta=70,progress=True,target=copy.deepcopy(target),admissionEligible=False))
        m=self.metrics('operation',True,True,offset=70)
        self.target(name,1,target,m,element,clip,[0,70],'window/0')
        self.add(name+'-input',dict(schema='p1-layout-action-v1',case=name,label='Resume Status Check',scrollAttempts=1,button=copy.deepcopy(target),visibleIntersection=[10,70,300,50],region=element,
                                  layoutMetrics=m,clippingViewport=clip,priorCallbackCounter=0,expectedCallbackCounter=1,driver='ordinary-XCTest-visible-coordinate-tap',admissionEligible=False))
        self.screen(name+'-visible',m)
        before=m;after=self.metrics('operation',True,True,offset=70,details=True)
        actual=observed([10,370,300,50],'resume-operation:1','p1-recovery-last-action');actual['hittable']=False
        search=name+'-callback-observer'
        self.add(name+'-observer',dict(schema='p1-layout-observer-v1',case=search+'-observation-0',search=search,attempt=0,
            expectedLabel='resume-operation:1',queryCount=1,target=actual,actionBefore=before,layoutMetrics=after,
            element=observed([0,180,800,160],identifier='p1-fixture-details-list'),scrollPath='window/1',clippingViewport=[0,200,800,140],offset=[0,0],admissionEligible=False))
        self.add(name+'-callback',dict(schema='p1-layout-callback-v1',case=name,expected='resume-operation',actual=actual,
            actionBefore=before,layoutMetrics=after,priorCallbackCounter=0,expectedCallbackCounter=1,observerSearch=search,observerAttempts=0,admissionEligible=False))
        self.screen(name+'-callback',after)
        self.geometry(name+'-after','operation',True,True)
        m=self.metrics('operation',True,True,details=True)
        element=observed([0,180,800,160],identifier='p1-fixture-details-list');target=observed([10,230,300,50],'Fixture Next Recovery','p1-fixture-next-recovery')
        search='p1-fixture-next-recovery-search-1'
        self.target(search,0,target,m,element,[0,200,800,140],[0,0],'window/1')
        self.add('fixture-input',dict(schema='p1-layout-fixture-input-v1',case='fixture-input-1',identifier='p1-fixture-next-recovery',search=search,scrollAttempts=0,button=target,element=element,
                                     visibleIntersection=[10,230,300,50],clippingViewport=[0,200,800,140],layoutMetrics=m,navigationBars=[observed([0,130,800,50])],tabs=self.tabs(True),
                                     driver='ordinary-XCTest-visible-coordinate-tap',admissionEligible=False))
        self.screen('fixture-input-1',m)
        self.geometry('capability-targets-next','direct',True,True,'Details')

    def passive_scroll(self):
        """Insert one real-input-shaped scroll before the passive receipt appears."""
        name='capability-targets-resume';search=name+'-callback-observer'
        final=self.rows[name+'-observer'];callback=self.rows[name+'-callback']
        tick=final['layoutMetrics']['observationSequence']
        def at(sequence,offset):
            m=copy.deepcopy(final['layoutMetrics']);m['observationSequence']=sequence
            m['runnerRequestBracket']=[sequence,sequence+.1]
            m['causalPrevious']['observationSequence']=sequence-1
            for receipt in [m,m['causalPrevious']]:receipt['scrollViews'][1]['contentOffset']=[0,offset]
            return m
        initial=copy.deepcopy(final)
        initial.update(target={'exists':False},queryCount=0,layoutMetrics=at(tick-6,-30),offset=[0,-30])
        final.update(attempt=1,case=search+'-observation-1')
        self.add(name+'-observer-initial',initial);callback['observerAttempts']=1
        drag=dict(schema='p1-layout-drag-v1',case='observer-drag-1',metrics=at(tick-4,-30),viewport=[0,0,800,400],
            element=final['element'],visibleBounds=final['clippingViewport'],interiorBounds=[12,212,776,116],
            start=[400,287],end=[400,253],direction='up',driver='ordinary-XCTest-controlled-coordinate-drag',
            velocity=80,pressDuration=.05,holdDuration=.2,navigationBars=[observed([0,130,800,50])],tabs=self.tabs(True),
            scrollPath='window/1',offsetBefore=[0,-30],target={'exists':False},search=search,attempt=0,admissionEligible=False)
        self.add('observer-drag',drag)
        self.add('observer-drag-after',dict(schema='p1-layout-drag-after-v1',case='observer-drag-1',metrics=at(tick-2,0),
            viewport=observed([0,0,800,400]),foreground=True,scrollPath='window/1',offsetAfter=[0,0],offsetDelta=30,
            progress=True,target=copy.deepcopy(final['target']),admissionEligible=False))
        return self

    def verify(self):
        for name,row in self.rows.items():
            file=self.root/self.files[name]
            if isinstance(row,bytes):file.write_bytes(row)
            else:file.write_text(json.dumps(row))
        (self.root/'manifest.json').write_text(json.dumps(self.manifest))
        return gate.verify_capabilities(self.root,self.summary,self.tests,'synthetic',self.device_class,capture.parse,capture.ordinary,lambda b:b.startswith(b'\x89PNG'))


class RecoveryCapabilities(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def fixture(self,kind='phone'):return CapabilityFixture(self.root,kind)
    def test_tablet_focused_contract(self):
        result=self.fixture('tablet').verify();self.assertEqual(result['test_count'],2);self.assertFalse(result['admissionEligible']);self.assertFalse(result['full_matrix_complete'])
    def test_phone_focused_contract(self):
        result=self.fixture().verify();self.assertEqual(result['test_count'],1);self.assertEqual(result['action_count'],1);self.assertEqual(result['scope'],'recovery-capability-only')
    def test_short_collection_cannot_pass_full_matrix(self):
        f=self.fixture();f.verify()
        with self.assertRaises(ValueError):gate.verify(f.root,f.summary,f.tests,'synthetic',capture.parse,capture.ordinary,lambda b:True)
    def test_non_nested_tabs_do_not_prove_capability(self):
        f=self.fixture('tablet');r=f.rows['capability-tabs-initial'];r['tabCandidates']=inventory(r['tabs'],r['viewport']['frame'])
        with self.assertRaisesRegex(ValueError,'nested tab capability'):f.verify()
    def test_equal_frame_siblings_are_not_deduplicated(self):
        f=self.fixture('tablet');g=f.rows['capability-tabs-initial']['tabCandidates'][0];r=g['candidates'][1];r['path']=[1];r['snapshot']['path']=[1];r['ancestors']=r['ancestors'][:1];g['selectedPath']=[1]
        with self.assertRaisesRegex(ValueError,'ambiguous|unrelated'):f.verify()
    def test_live_label_mismatch_fails(self):
        f=self.fixture('tablet');f.rows['capability-tabs-initial']['tabCandidates'][0]['candidates'][1]['observed']['label']='Apps'
        with self.assertRaisesRegex(ValueError,'snapshot/live'):f.verify()
    def test_mismatching_ancestor_frame_fails(self):
        f=self.fixture('tablet');g=f.rows['capability-tabs-initial']['tabCandidates'][0];g['candidates'][1]['ancestors'][1]=copy.deepcopy(g['candidates'][1]['ancestors'][1]);g['candidates'][1]['ancestors'][1]['frame']=[1,1,20,20]
        with self.assertRaisesRegex(ValueError,'ancestry attributes|ancestor candidate'):f.verify()
    def test_missing_ancestry_fails(self):
        f=self.fixture('tablet');f.rows['capability-tabs-initial']['tabCandidates'][0]['candidates'][1]['ancestors'].pop()
        with self.assertRaisesRegex(ValueError,'ancestry'):f.verify()
    def test_parent_selection_fails(self):
        f=self.fixture('tablet');f.rows['capability-tabs-initial']['tabCandidates'][0]['selectedPath']=[0]
        with self.assertRaisesRegex(ValueError,'ambiguous'):f.verify()
    def test_incomplete_snapshot_fails(self):
        f=self.fixture('tablet');f.rows['capability-tabs-initial']['tabCandidates'][0]['snapshotComplete']=False
        with self.assertRaisesRegex(ValueError,'incomplete'):f.verify()
    def test_missing_actual_tab_selection_fails(self):
        f=self.fixture('tablet');f.rows['capability-tabs-apps-selection']['actual']['selectedTab']=0
        with self.assertRaisesRegex(ValueError,'selected tab'):f.verify()
    def test_selected_tab_frame_may_change_after_actual_input(self):
        f=self.fixture('tablet');f.rows['capability-tabs-apps-selection']['control']['frame']=[100,750,95,40]
        self.assertTrue(f.verify()['collection_complete'])
    def test_wrong_pre_input_leaf_rejected(self):
        f=self.fixture('tablet');f.rows['capability-tabs-apps-selection']['controlBefore']['identifier']='p1-tab-Settings'
        with self.assertRaisesRegex(ValueError,'structural leaf'):f.verify()
    def test_wrong_tab_content_fails(self):
        f=self.fixture('tablet');f.rows['capability-tabs-home-selection']['content']['label']='Synthetic Apps content'
        with self.assertRaisesRegex(ValueError,'response content'):f.verify()
    def test_portrait_cannot_be_renamed_landscape(self):
        f=self.fixture('tablet');m=f.rows['capability-rotation-landscape']['layoutMetrics'];m['interfaceOrientation']=m['causalPrevious']['interfaceOrientation']=1
        with self.assertRaisesRegex(ValueError,'orientation'):f.verify()
    def test_new_window_during_rotation_fails(self):
        f=self.fixture('tablet');m=f.rows['capability-rotation-landscape']['layoutMetrics'];m['windowObservationID']=m['causalPrevious']['windowObservationID']='replacement'
        with self.assertRaisesRegex(ValueError,'window'):f.verify()
    def test_stale_branch_rejected(self):
        f=self.fixture();m=f.rows['capability-targets-next']['layoutMetrics'];m['recoveryKind']=m['causalPrevious']['recoveryKind']='operation'
        with self.assertRaisesRegex(ValueError,'branch/size'):f.verify()
    def test_stale_observation_rejected(self):
        f=self.fixture();m=f.rows['capability-targets-next']['layoutMetrics'];m['observationSequence']=2;m['causalPrevious']['observationSequence']=1
        with self.assertRaisesRegex(ValueError,'stale/reused'):f.verify()
    def test_wrong_action_branch_rejected(self):
        f=self.fixture();m=f.rows['capability-targets-resume-input']['layoutMetrics'];m['recoveryKind']=m['causalPrevious']['recoveryKind']='direct'
        with self.assertRaisesRegex(ValueError,'branch/size|branch'):f.verify()
    def test_wrong_action_orientation_rejected(self):
        f=self.fixture();m=f.rows['capability-targets-resume-input']['layoutMetrics'];m['interfaceOrientation']=m['causalPrevious']['interfaceOrientation']=1
        with self.assertRaisesRegex(ValueError,'orientation'):f.verify()
    def test_fast_drag_recipe_rejected(self):
        f=self.fixture();f.rows['drag']['velocity']=1000
        with self.assertRaisesRegex(ValueError,'unsafe drag'):f.verify()
    def test_drag_away_from_target_rejected(self):
        f=self.fixture();f.rows['drag']['direction']='down'
        with self.assertRaisesRegex(ValueError,'away from target'):f.verify()
    def test_unsafe_edge_drag_rejected(self):
        f=self.fixture();f.rows['drag']['start']=[1,87]
        with self.assertRaisesRegex(ValueError,'unsafe area'):f.verify()
    def test_false_progress_rejected(self):
        f=self.fixture();f.rows['drag-after']['progress']=False
        with self.assertRaisesRegex(ValueError,'progress'):f.verify()
    def test_offset_mismatch_rejected(self):
        f=self.fixture();f.rows['drag-after']['offsetAfter']=[0,600]
        with self.assertRaisesRegex(ValueError,'offset'):f.verify()
    def test_ambiguous_list_correspondence_rejected(self):
        f=self.fixture();m=f.rows['fixture-input']['layoutMetrics'];m['scrollViews'].append(copy.deepcopy(m['scrollViews'][-1]))
        with self.assertRaisesRegex(ValueError,'ambiguous'):f.verify()
    def test_clipped_next_button_rejected(self):
        f=self.fixture();f.rows['fixture-input']['visibleIntersection'][3]=43
        with self.assertRaisesRegex(ValueError,'clipped'):f.verify()
    def test_next_button_over_navigation_rejected(self):
        f=self.fixture();f.rows['fixture-input']['navigationBars'][0]['frame']=[0,220,800,50]
        with self.assertRaisesRegex(ValueError,'overlaps'):f.verify()
    def test_missing_attempt_rejected(self):
        f=self.fixture();f.rows['capability-targets-resume-target-0']['search']='other'
        with self.assertRaisesRegex(ValueError,'identity|attempt'):f.verify()
    def test_unbound_final_target_rejected(self):
        f=self.fixture();f.rows['capability-targets-resume-target-1']['target']['frame'][1]+=1
        with self.assertRaisesRegex(ValueError,'final target'):f.verify()
    def test_duplicate_target_drag_rejected(self):
        f=self.fixture();r=copy.deepcopy(f.rows['drag']);r['case']='drag-2';f.add('duplicate-drag',r)
        a=copy.deepcopy(f.rows['drag-after']);a['case']='drag-2';f.add('duplicate-after',a)
        with self.assertRaisesRegex(ValueError,'duplicate target'):f.verify()
    def test_wrong_callback_counter_rejected(self):
        f=self.fixture();f.rows['capability-targets-resume-callback']['actual']['label']='resume-operation:2'
        with self.assertRaisesRegex(ValueError,'current-action|action sequence'):f.verify()
    def test_passive_callback_does_not_require_actionable_visibility(self):
        f=self.fixture();receipt=f.rows['capability-targets-resume-callback']
        self.assertFalse(receipt['actual']['hittable'])
        self.assertGreater(receipt['actual']['frame'][1],340)
        self.assertTrue(f.verify()['collection_complete'])
    def test_passive_callback_requires_unique_exact_id(self):
        f=self.fixture();f.rows['capability-targets-resume-observer']['queryCount']=2
        with self.assertRaisesRegex(ValueError,'ambiguous passive'):f.verify()
    def test_passive_callback_wrong_identity_rejected(self):
        f=self.fixture();f.rows['capability-targets-resume-callback']['actual']['identifier']='other'
        with self.assertRaisesRegex(ValueError,'current-action'):f.verify()
    def test_passive_callback_stale_counter_rejected(self):
        f=self.fixture();f.rows['capability-targets-resume-input']['expectedCallbackCounter']=0
        with self.assertRaisesRegex(ValueError,'current-action counter'):f.verify()
    def test_passive_callback_boolean_counter_rejected(self):
        f=self.fixture();f.rows['capability-targets-resume-input']['priorCallbackCounter']=False
        with self.assertRaisesRegex(ValueError,'current-action counter'):f.verify()
    def test_passive_callback_input_counter_binding_rejected(self):
        f=self.fixture();f.rows['capability-targets-resume-callback']['expectedCallbackCounter']=2
        with self.assertRaisesRegex(ValueError,'counter differs'):f.verify()
    def test_passive_callback_input_receipt_binding_rejected(self):
        f=self.fixture();r=f.rows['capability-targets-resume-callback'];r['actionBefore']=copy.deepcopy(r['actionBefore']);r['actionBefore']['viewCount']+=1
        with self.assertRaisesRegex(ValueError,'actual input'):f.verify()
    def test_passive_callback_wrong_session_rejected(self):
        f=self.fixture();m=f.rows['capability-targets-resume-callback']['layoutMetrics'];m['processSession']=m['causalPrevious']['processSession']='other'
        with self.assertRaisesRegex(ValueError,'process or window'):f.verify()
    def test_passive_callback_stale_observation_rejected(self):
        f=self.fixture();r=f.rows['capability-targets-resume-callback'];r['layoutMetrics']=r['actionBefore']
        with self.assertRaisesRegex(ValueError,'stale/reused'):f.verify()
    def test_passive_callback_missing_observation_rejected(self):
        f=self.fixture();f.rows['capability-targets-resume-observer']['search']='other'
        with self.assertRaisesRegex(ValueError,'passive observation'):f.verify()
    def test_passive_callback_incomplete_observer_sequence_rejected(self):
        f=self.fixture();f.rows['capability-targets-resume-callback']['observerAttempts']=1
        with self.assertRaisesRegex(ValueError,'passive observation'):f.verify()
    def test_passive_callback_final_observation_must_match(self):
        f=self.fixture();r=f.rows['capability-targets-resume-callback'];r['actual']=dict(r['actual'],frame=[10,371,300,50])
        with self.assertRaisesRegex(ValueError,'final passive observation'):f.verify()
    def test_passive_callback_extra_scroll_rejected(self):
        f=self.fixture();r=copy.deepcopy(f.rows['drag']);r.update(search='capability-targets-resume-callback-observer',attempt=0,case='extra-observer-scroll');f.add('extra-observer-scroll',r)
        with self.assertRaisesRegex(ValueError,'extra passive observer'):f.verify()
    def test_passive_callback_scroll_sequence_replayed(self):
        self.assertTrue(self.fixture().passive_scroll().verify()['collection_complete'])
    def test_passive_callback_missing_scroll_rejected(self):
        f=self.fixture().passive_scroll();f.rows['observer-drag']['search']='other'
        with self.assertRaisesRegex(ValueError,'passive scroll input'):f.verify()
    def test_passive_callback_unobserved_offset_rejected(self):
        f=self.fixture().passive_scroll();f.rows['observer-drag-after']['offsetAfter']=[0,2]
        with self.assertRaisesRegex(ValueError,'unobserved passive scroll'):f.verify()
    def test_passive_callback_wrong_scroll_target_rejected(self):
        f=self.fixture().passive_scroll();f.rows['observer-drag']['target']={'exists':True}
        with self.assertRaisesRegex(ValueError,'passive scroll target'):f.verify()
    def test_passive_callback_scroll_context_rejected(self):
        f=self.fixture().passive_scroll();m=f.rows['observer-drag']['metrics'];m['processSession']=m['causalPrevious']['processSession']='other'
        with self.assertRaisesRegex(ValueError,'process or window'):f.verify()
    def test_passive_callback_extra_unbound_observer_rejected(self):
        f=self.fixture();r=copy.deepcopy(f.rows['capability-targets-resume-observer']);r.update(search='other',case='other-observation-0');f.add('unbound-observer',r)
        with self.assertRaisesRegex(ValueError,'unbound/wrong-method passive'):f.verify()
    def test_passive_callback_self_consistent_high_counter_rejected(self):
        f=self.fixture();name='capability-targets-resume'
        for key in [name+'-input',name+'-callback']:
            f.rows[key].update(priorCallbackCounter=9,expectedCallbackCounter=10)
        f.rows[name+'-callback']['actual']['label']='resume-operation:10'
        f.rows[name+'-observer']['expectedLabel']='resume-operation:10'
        with self.assertRaisesRegex(ValueError,'fresh-launch callback counters'):f.verify()
    def test_missing_failure_receipt_cannot_be_success(self):
        f=self.fixture();f.add('failure',dict(schema='p1-layout-target-failure-v1',case='failed',admissionEligible=False))
        with self.assertRaisesRegex(ValueError,'retained layout failure'):f.verify()
    def test_stale_screenshot_window_rejected(self):
        f=self.fixture();m=f.rows['capability-targets-initial-screen']['metrics'];m['windowObservationID']=m['causalPrevious']['windowObservationID']='other'
        with self.assertRaisesRegex(ValueError,'window'):f.verify()
    def test_raw_methods_cannot_be_swapped(self):
        f=self.fixture('tablet');f.tests['testNodes'][0]['nodeIdentifier']='P1RecoveryLayoutUITests/testRecoveryBranchesDefault()'
        with self.assertRaisesRegex(ValueError,'methods'):f.verify()


if __name__=='__main__':unittest.main()
