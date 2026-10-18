"""Strict diagnostic layout evidence, separate from timing feasibility."""
import re
import math
import struct
from exports import require,frame,leaves

METHODS=['testRecoveryBranchesDefault','testRecoveryBranchesLargest','testRecoveryCompactLandscape','testRecoveryStateAndSizeTransitions']
CAPABILITY_METHODS={'tablet':['testCapabilityNestedTabSelection','testCapabilityNoBannerRotation'],'phone':['testCapabilityLandscapeTargets'],'phone-default':['testCapabilityIdentifierFreeTabs']}
KINDS=['none','operation','direct','refresh','unreadable']
ACTIONS={'operation':{'resume':'resume-operation','confirm':'reconcile-operation'},
    'direct':{'inspect':'inspect-direct','confirm':'reconcile-direct'},'refresh':{'confirm':'reconcile-refresh'},
    'unreadable':{'copy':'copy-diagnostics-exact','confirm':'discard-unreadable'}}
TRANSITIONS=['initial','shown','largest','rotated','kind-direct','kind-refresh','kind-unreadable','kind-operation','portrait','standard-with-banner','cleared','final-root']

IDENTITIES={'operation':'A previous install may still be running','direct':'A previous certificate creation has an unresolved result',
    'refresh':'A previous refresh may still be running','unreadable':'SideStore paused changes because its recovery record is malformed\nError ID: SS-STATUS-FIXTURE'}

def context(name):
    if name=='capability-default-tabs':return 'none',False,False,'Home'
    if name.startswith('capability-tabs-'):return 'none',False,False,'Home' if name.endswith('initial') else 'Details'
    if name.startswith('capability-rotation-'):return 'none',False,name.endswith('landscape'),'Home'
    if name.startswith('capability-targets-'):return ('direct' if name.endswith('next') else 'operation'),True,True,'Details' if name.endswith('next') else 'Home'
    match=re.fullmatch(r'layout-(none|operation|direct|refresh|unreadable)-(default|AX5)-(portrait|landscape)',name)
    if match:return match[1],match[2]=='AX5',match[3]=='landscape','Home'
    if not name.startswith('transition-'):return None
    suffix=name[len('transition-'):]
    kind='none' if suffix in ['initial','cleared','final-root'] else suffix[len('kind-'):] if suffix.startswith('kind-') else 'operation'
    largest=suffix in ['largest','rotated','portrait'] or suffix.startswith('kind-')
    landscape=suffix=='rotated' or suffix.startswith('kind-')
    return kind,largest,landscape,'Home' if suffix in ['initial','final-root'] else 'Details'


def inside(a,b):return a[0]>=b[0]-1 and a[1]>=b[1]-1 and a[0]+a[2]<=b[0]+b[2]+1 and a[1]+a[3]<=b[1]+b[3]+1
def disjoint(a,b):return min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0])<=1 or min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1])<=1


def near(a,b):return len(a)==len(b) and all(abs(x-y)<=1 for x,y in zip(a,b))
def intersection(a,b):
    x=max(a[0],b[0]);y=max(a[1],b[1]);w=min(a[0]+a[2],b[0]+b[2])-x;h=min(a[1]+a[3],b[1]+b[3])-y
    require(w>0 and h>0,'empty measured clipping intersection');return [x,y,w,h]
def finite(value):return type(value) in (int,float) and math.isfinite(value)

def converted_frame(view,key='bounds'):
    local=frame(view.get(key));transform=view.get('localToWindow')
    require(isinstance(transform,list) and len(transform)==6 and all(finite(x) for x in transform),'missing actual coordinate transform')
    a,b,c,d,tx,ty=transform
    require((abs(b)<=1e-6 and abs(c)<=1e-6 and abs(a)>1e-6 and abs(d)>1e-6) or (abs(a)<=1e-6 and abs(d)<=1e-6 and abs(b)>1e-6 and abs(c)>1e-6),'non-rectilinear clipping transform')
    x,y,w,h=local;corners=[(a*i+c*j+tx,b*i+d*j+ty) for i,j in [(x,y),(x+w,y),(x,y+h),(x+w,y+h)]]
    xs,ys=zip(*corners);return [min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)]


def metric_basis(metrics,viewport,selected=0):
    require(isinstance(metrics,dict) and metrics.get('schema')=='p1-layout-metrics-v1' and metrics.get('complete') is True and metrics.get('applicationActive') is True,'missing/inactive layout metrics')
    require(type(metrics.get('viewCount')) is int and 0<metrics['viewCount']<=4096,'incomplete UIKit hierarchy')
    require(type(metrics.get('selectedTab')) is int and metrics['selectedTab']==selected,'actual selected tab differs')
    previous=metrics.get('causalPrevious',{});first=previous.get('observationSequence');second=metrics.get('observationSequence')
    require(type(first) is int and type(second) is int and 0<first<second and metrics.get('probeValueReadCount')==2,'cached/noncausal geometry observation')
    require(near(frame(previous.get('windowBounds')),frame(metrics.get('windowBounds'))) and near(frame(previous.get('offeredFrame')),frame(metrics.get('offeredFrame'))) and previous.get('selectedTab')==selected,'geometry changed between causal requests')
    require(previous.get('schema')=='p1-layout-metrics-v1' and previous.get('complete') is True and previous.get('applicationActive') is True,'previous getter observation incomplete')
    for key in ['processSession','windowObservationID']:
        require(isinstance(metrics.get(key),str) and bool(metrics[key]) and previous.get(key)==metrics[key],'getter session/window changed')
    require(previous.get('interfaceOrientation')==metrics.get('interfaceOrientation') and previous.get('offeredSize')==metrics.get('offeredSize'),'getter orientation/offered size changed')
    require(metrics.get('recoveryKind') in KINDS and type(metrics.get('largestText')) is bool and previous.get('recoveryKind')==metrics['recoveryKind'] and previous.get('largestText') is metrics['largestText'],'missing/changed measured branch/size')
    bracket=metrics.get('runnerRequestBracket');require(isinstance(bracket,list) and len(bracket)==2 and all(finite(x) for x in bracket) and 0<=bracket[0]<=bracket[1],'missing runner request-duration bracket')
    start=metrics.get('startedUptime');finish=metrics.get('finishedUptime')
    require(finite(start) and finite(finish) and 0<=start<=finish,'invalid layout observation times')
    window=frame(metrics.get('windowBounds'));offered=frame(metrics.get('offeredFrame'));size=metrics.get('offeredSize')
    require(near(window,viewport) and inside(offered,window),'actual window/offered frame differs')
    require(isinstance(size,list) and len(size)==2 and all(finite(x) and x>0 for x in size) and near(size,offered[2:]),'offered parent size differs')
    orientation=metrics.get('interfaceOrientation')
    require(type(orientation) is int and orientation in ([3,4] if window[2]>window[3] else [1,2]),'native interface orientation differs')
    return offered,size

def clipping_viewport(metrics,viewport,region,enforce_cap=True):
    offered,size=metric_basis(metrics,viewport)
    rows=metrics.get('scrollViews');require(isinstance(rows,list),'missing UIKit scroll inventory')
    matches=[]
    for row in rows:
        require(isinstance(row,dict) and isinstance(row.get('view'),dict),'invalid UIKit scroll record')
        try:f=frame(row['view'].get('frame'))
        except ValueError:continue
        if near(f,region):matches.append(row)
    require(len(matches)==1,'ambiguous recovery scroll correspondence')
    row=matches[0];view=row['view'];ancestors=row.get('ancestors');path=row.get('path')
    require(isinstance(path,str) and re.fullmatch(r'window(?:/[0-9]+)+',path),'wrong recovery ancestry path')
    require(isinstance(ancestors,list) and len(ancestors)==path.count('/'),'wrong recovery ancestry depth')
    require(row.get('scrollEnabled') is True and view.get('hidden') is False and finite(view.get('alpha')) and view['alpha']>0.01,'unavailable UIKit scroll region')
    require(near(converted_frame(view),frame(view['frame'])),'scroll frame coordinate conversion differs')
    clipped=intersection(frame(view['frame']),viewport)
    for i,ancestor in enumerate(ancestors):
        require(isinstance(ancestor,dict) and ancestor.get('hidden') is False and finite(ancestor.get('alpha')) and ancestor['alpha']>0.01,'hidden clipping ancestry')
        a=frame(ancestor.get('frame'));require(near(converted_frame(ancestor),a),'ancestor coordinate conversion differs')
        if i==0:require(near(a,viewport),'clipping ancestry is not rooted in actual window')
        require(type(ancestor.get('clips')) is bool,'missing clipping flag')
        if ancestor['clips']:clipped=intersection(clipped,a)
    require(near(clipped,frame(row.get('clippedBounds'))),'clipping ancestry bounds differ')
    local=frame(view.get('bounds'));insets=row.get('safeAreaInsets')
    require(isinstance(insets,list) and len(insets)==4 and all(finite(x) and x>=0 for x in insets),'invalid observed safe-area insets')
    top,left,bottom,right=insets
    local_safe=[local[0]+left,local[1]+top,local[2]-left-right,local[3]-top-bottom]
    require(near(frame(row.get('localSafeAreaFrame')),frame(local_safe)),'safe-area guide/insets differ')
    safe=frame(row.get('safeAreaFrame'));mapping=dict(view,bounds=local_safe)
    require(near(converted_frame(mapping),safe) and inside(safe,frame(view['frame'])),'safe viewport coordinate conversion differs')
    effective=intersection(intersection(safe,clipped),offered)
    require(near(effective,frame(row.get('safeClippingViewport'))),'measured clipping viewport differs')
    if enforce_cap:require(effective[3]<=min(320,size[1]*.4)+1,'measured safe viewport exceeds cap')
    return effective

def check_screen(row,png):
    require(row.get('source')=='XCUIScreen.main','full screen pixels required')
    require(len(png)>=24 and png[:8]==b'\x89PNG\r\n\x1a\n','invalid full screen PNG')
    width,height=struct.unpack('>II',png[16:24]);require(width==row.get('pixelWidth') and height==row.get('pixelHeight'),'raw screenshot dimensions differ')
    require(type(row.get('imageOrientation')) is int and 0<=row['imageOrientation']<=7,'missing screenshot orientation')
    viewport=frame(row.get('viewport',{}).get('frame'));metrics=row.get('metrics',{})
    metric_basis(metrics,viewport,metrics.get('selectedTab'))
    scale=metrics.get('screenScale');require(finite(scale) and scale>0,'invalid screen scale')
    require(near(sorted([width,height]),sorted([viewport[2]*scale,viewport[3]*scale])),'screenshot does not cover actual full viewport')


def expected():
    geometries={};actions={};screens={}
    for method,size,orientation in zip(METHODS[:3],['default','AX5','AX5'],['portrait','portrait','landscape']):
        for kind in KINDS:
            name=f'layout-{kind}-{size}-{orientation}';geometries[name]=(method,kind!='none');screens[name]=method
            for suffix,callback in ACTIONS.get(kind,{}).items():
                action=name+'-'+suffix;actions[action]=(method,callback)
                geometries[action+'-after']=(method,True)
                for end in ['visible','callback','after']+(['confirmation'] if suffix=='confirm' else []):screens[action+'-'+end]=method
    for suffix in TRANSITIONS:
        name='transition-'+suffix;geometries[name]=(METHODS[3],suffix not in ['initial','cleared','final-root']);screens[name]=METHODS[3]
    screens.update({"transition-apps-tab":METHODS[3],"transition-home-tab":METHODS[3]})
    return geometries,actions,screens


def same_context(before,after,rotation=False,state_change=False,tab_change=False):
    for key in ['processSession','windowObservationID']:
        require(before.get(key)==after.get(key),'stale/wrong process or window')
    require(before['observationSequence']<after['causalPrevious']['observationSequence'],'stale/reused observation sequence')
    require(before['runnerRequestBracket'][1]<=after['runnerRequestBracket'][0],'reordered runner observation')
    if not rotation:
        require(before['interfaceOrientation']==after['interfaceOrientation'] and near(frame(before['windowBounds']),frame(after['windowBounds'])),'context orientation/window changed')
    if not state_change:
        require(before.get('recoveryKind')==after.get('recoveryKind') and before.get('largestText')==after.get('largestText'),'context branch/size changed')
    if not tab_change:require(before['selectedTab']==after['selectedTab'],'context tab changed')


def validate_structural_tabs(inventory,tabs=None):
    titles=['Home','Apps','Sources','Settings'];chosen=[];paths=[]
    require([g.get('title') for g in inventory]==titles,'structural tab order differs')
    bar=inventory[0].get('tabBar');require(isinstance(bar,dict),'missing unique native tab bar')
    def pair(row,expected_type):
        path=row.get('path');ancestors=row.get('ancestors');snap=row.get('snapshot');live=row.get('observed')
        require(isinstance(path,list) and path and all(type(i) is int and i>=0 for i in path),'invalid structural path')
        require(isinstance(ancestors,list) and len(ancestors)==len(path),'incomplete structural ancestry')
        for index,a in enumerate(ancestors):
            require(isinstance(a,dict) and a.get('path')==path[:index] and type(a.get('elementType')) is int and isinstance(a.get('identifier'),str) and isinstance(a.get('label'),str) and type(a.get('selected')) is bool,'broken structural ancestry')
            frame(a.get('frame'))
        require(isinstance(snap,dict) and isinstance(live,dict) and snap.get('path')==path,'missing structural snapshot/live pair')
        require(live.get('exists') is True and live.get('hittable') is True and live.get('elementType')==expected_type and type(live.get('selected')) is bool,'structural control unavailable')
        require(all(snap.get(k)==live.get(k) for k in ['identifier','label','elementType','selected']) and near(frame(snap.get('frame')),frame(live.get('frame'))),'structural snapshot/live differs')
        return path,snap,live
    bar_path,bar_snapshot,bar_live=pair(bar,22)
    viewport=frame(inventory[0].get('viewport'));require(inside(frame(bar_live['frame']),viewport),'native tab bar outside viewport')
    for title,g in zip(titles,inventory):
        require(g.get('resolution')=='unique-native-tabbar-v1' and g.get('tabBar')==bar and g.get('viewport')==inventory[0]['viewport'],'mixed structural tab proof')
        require(g.get('identifier')=='p1-tab-'+title and type(g.get('queryCount')) is int and g['queryCount']==0,'identifier-free proof contradicted')
        require(type(g.get('barQueryCount')) is int and g['barQueryCount']==1 and type(g.get('buttonQueryCount')) is int and g['buttonQueryCount']==4,'native bar/button ambiguity')
        require(g.get('snapshotComplete') is True and type(g.get('snapshotNodeCount')) is int and 0<g['snapshotNodeCount']<=4096,'incomplete structural snapshot')
        rows=g.get('candidates');require(isinstance(rows,list) and len(rows)==1,'ambiguous structural button')
        path,snap,live=pair(rows[0],9)
        require(len(path)>len(bar_path) and path[:len(bar_path)]==bar_path and rows[0]['ancestors'][len(bar_path)]==bar_snapshot,'button outside proven tab bar')
        require(live.get('identifier')=='' and live.get('label')==title and g.get('selectedPath')==path,'wrong structural button identity')
        require(inside(frame(live['frame']),viewport) and inside(frame(live['frame']),frame(bar_live['frame'])),'structural button outside bar/viewport')
        paths.append(path);chosen.append(live)
    require(paths==sorted(paths) and len({tuple(p) for p in paths})==4 and all(not (len(q)>len(p) and q[:len(p)]==p) for p in paths for q in paths),'structural button order/leaf ambiguity')
    require(sum(t['selected'] for t in chosen)==1,'structural selection ambiguous')
    if tabs is not None:require(tabs==chosen,'retained structural controls differ')
    return chosen


def validate_tab_inventory(inventory,tabs=None,require_nested=False):
    titles=['Home','Apps','Sources','Settings']
    require(isinstance(inventory,list) and len(inventory)==4 and {c.get('identifier') for c in inventory}=={'p1-tab-'+t for t in titles},'missing adaptive tab inventory')
    if any(g.get('resolution')=='unique-native-tabbar-v1' for g in inventory):
        require(not require_nested,'nested capability requires original identifier chains')
        return validate_structural_tabs(inventory,tabs)
    chosen=[]
    for group in inventory:
        title=group.get('title');identifier=group.get('identifier');rows=group.get('candidates')
        require(title in titles and identifier=='p1-tab-'+title,'wrong tab inventory title')
        require(group.get('snapshotComplete') is True and type(group.get('snapshotNodeCount')) is int and 0<group['snapshotNodeCount']<=4096,'incomplete tab snapshot')
        require(isinstance(rows,list) and rows and type(group.get('queryCount')) is int and group['queryCount']==len(rows),'tab query/snapshot inventory differs')
        paths=[]
        for row in rows:
            path=row.get('path');ancestors=row.get('ancestors');snap=row.get('snapshot');live=row.get('observed')
            require(isinstance(path,list) and path and all(type(i) is int and i>=0 for i in path),'invalid tab ancestry path')
            require(path not in paths,'duplicate tab ancestry path');paths.append(path)
            require(isinstance(ancestors,list) and len(ancestors)==len(path),'incomplete tab ancestry')
            for index,ancestor in enumerate(ancestors):
                require(isinstance(ancestor,dict) and ancestor.get('path')==path[:index],'broken tab ancestry path')
                require(type(ancestor.get('elementType')) is int and isinstance(ancestor.get('identifier'),str) and isinstance(ancestor.get('label'),str) and type(ancestor.get('selected')) is bool,'missing ancestry attributes')
                frame(ancestor.get('frame'))
            require(isinstance(snap,dict) and isinstance(live,dict) and snap.get('path')==path,'missing snapshot/live tab pair')
            require(live.get('exists') is True and live.get('hittable') is True,'tab unavailable')
            for key in ['identifier','label','elementType','selected']:
                require(snap.get(key)==live.get(key),'tab snapshot/live changed')
            require(live.get('identifier')==identifier and live.get('label')==title and live.get('elementType')==9 and type(live.get('selected')) is bool,'wrong actual tab identity/type')
            require(near(frame(snap.get('frame')),frame(live.get('frame'))),'tab snapshot/live frame changed')
        for row in rows:
            for ancestor in row['ancestors']:
                if ancestor['identifier']==identifier:
                    matches=[r for r in rows if r['path']==ancestor['path']]
                    require(len(matches)==1 and matches[0]['snapshot']==ancestor,'omitted/mismatching ancestor candidate')
        leaves=[p for p in paths if not any(len(q)>len(p) and q[:len(p)]==p for q in paths)]
        require(len(leaves)==1 and group.get('selectedPath')==leaves[0],'ambiguous actual tab candidate')
        leaf=leaves[0];selected=rows[paths.index(leaf)]['observed']
        for row,path in zip(rows,paths):
            require(leaf[:len(path)]==path,'unrelated duplicate tab controls')
            live=row['observed']
            require(all(live.get(k)==selected.get(k) for k in ['identifier','label','elementType','selected']) and near(frame(live['frame']),frame(selected['frame'])),'nested duplicate tab attributes differ')
            if path!=leaf:
                ancestor=rows[paths.index(leaf)]['ancestors'][len(path)]
                require(ancestor==row['snapshot'],'candidate ancestry attributes differ')
        if require_nested:require(len(rows)>=2,'nested tab capability not exercised')
        if tabs is not None:
            matches=[t for t in tabs if t.get('identifier')==identifier]
            require(len(matches)==1 and matches[0]==selected,'selected tab candidate differs')
        chosen.append(selected)
    return chosen


def scroll_record(metrics,element,enforce_cap):
    viewport=frame(metrics.get('windowBounds'));region=frame(element.get('frame'))
    clip=clipping_viewport(metrics,viewport,region,enforce_cap)
    rows=[r for r in metrics['scrollViews'] if near(frame(r['view']['frame']),region)]
    require(len(rows)==1,'ambiguous actual scroll')
    row=rows[0];offset=row.get('contentOffset')
    require(isinstance(offset,list) and len(offset)==2 and all(finite(v) for v in offset),'missing measured scroll offset')
    return clip,row


def validate_drag(row,after):
    viewport=frame(row.get('viewport'));metrics=row.get('metrics',{});metric_basis(metrics,viewport)
    element=row.get('element',{});recovery=element.get('identifier')=='v3.recovery.region'
    require(element.get('identifier') in ['v3.recovery.region','p1-fixture-details-list'],'wrong scroll target')
    clip,scroll=scroll_record(metrics,element,recovery)
    visible=frame(row.get('visibleBounds'));interior=frame(row.get('interiorBounds'))
    require(near(visible,clip) and inside(interior,visible),'drag outside measured clipping viewport')
    require(near(interior,[visible[0]+12,visible[1]+12,visible[2]-24,visible[3]-24]),'drag edge margin differs')
    target=row.get('target')
    if isinstance(target,dict) and target.get('exists') is True:
        target_frame=frame(target.get('frame'));needed=min(44,target_frame[3])
        if target_frame[1]+target_frame[3]<clip[1]+needed:require(row.get('direction')=='down','drag goes away from target above')
        elif target_frame[1]>clip[1]+clip[3]-needed:require(row.get('direction')=='up','drag goes away from target below')
    require(row.get('driver')=='ordinary-XCTest-controlled-coordinate-drag' and row.get('velocity')==80 and row.get('pressDuration')==0.05 and row.get('holdDuration')==0.2,'unsafe drag input recipe')
    require(isinstance(row.get('tabs'),list) and len(row['tabs'])==4 and isinstance(row.get('navigationBars'),list) and row['navigationBars'],'missing drag navigation inventory')
    for control in row['tabs']+row['navigationBars']:
        require(control.get('exists') is True and disjoint(interior,frame(control.get('frame'))),'drag overlaps navigation/tabs')
    for point in [row.get('start'),row.get('end')]:
        require(isinstance(point,list) and len(point)==2 and all(finite(x) for x in point) and interior[0]<=point[0]<=interior[0]+interior[2] and interior[1]<=point[1]<=interior[1]+interior[3],'drag endpoint touches unsafe area')
    start,end=row['start'],row['end'];distance=abs(end[1]-start[1])
    require(start[0]==end[0] and 8<=distance<=interior[3]*0.6+1 and row.get('direction')==('down' if end[1]>start[1] else 'up'),'unsafe drag direction/distance')
    require(after.get('foreground') is True,'drag left foreground app')
    after_metrics=after.get('metrics');metric_basis(after_metrics,frame(after.get('viewport',{}).get('frame')))
    same_context(metrics,after_metrics)
    _,after_scroll=scroll_record(after_metrics,element,recovery)
    require(row.get('scrollPath')==scroll['path']==after.get('scrollPath')==after_scroll['path'],'scroll correspondence changed')
    require(row.get('offsetBefore')==scroll['contentOffset'] and after.get('offsetAfter')==after_scroll['contentOffset'],'offset receipt differs')
    delta=after_scroll['contentOffset'][1]-scroll['contentOffset'][1]
    require(finite(after.get('offsetDelta')) and abs(after['offsetDelta']-delta)<=1e-6 and after.get('progress') is (abs(delta)>0.5),'false drag progress receipt')


def capability_expected(device_class):
    methods=CAPABILITY_METHODS[device_class];geometries={};actions={};screens={}
    if device_class=='tablet':
        for name in ['capability-tabs-initial','capability-tabs-returned']:geometries[name]=(methods[0],False)
        for suffix in ['portrait','landscape','returned']:geometries['capability-rotation-'+suffix]=(methods[1],False)
        screens.update({'capability-tabs-apps':methods[0],'capability-tabs-home':methods[0]})
    elif device_class=='phone-default':
        geometries['capability-default-tabs']=(methods[0],False)
    else:
        for name in ['capability-targets-initial','capability-targets-resume-after','capability-targets-next']:geometries[name]=(methods[0],True)
        actions['capability-targets-resume']=(methods[0],'resume-operation')
        screens.update({n:methods[0] for n in ['capability-targets-resume-visible','capability-targets-resume-callback']})
    screens.update({n:m for n,(m,_) in geometries.items()})
    return geometries,actions,screens


def verify_capabilities(root,summary,tests,device,device_class,parse,ordinary,valid_png):
    require(device_class in CAPABILITY_METHODS,'unknown capability device class')
    return _verify(root,summary,tests,device,parse,ordinary,valid_png,device_class)


def verify(root,summary,tests,device,parse,ordinary,valid_png):
    return _verify(root,summary,tests,device,parse,ordinary,valid_png,None)


def _verify(root,summary,tests,device,parse,ordinary,valid_png,capability):
    methods=CAPABILITY_METHODS[capability] if capability else METHODS
    count=len(methods)
    keys=['passedTests','failedTests','skippedTests','totalTestCount','expectedFailures']
    require(summary.get('result')=='Passed' and all(type(summary.get(k)) is int for k in keys) and [summary[k] for k in keys]==[count,0,0,count,0],'exact passed/zero skipped layout tests required')
    configurations=summary.get('devicesAndConfigurations')
    require(isinstance(configurations,list) and len(configurations)==1 and configurations[0].get('device',{}).get('deviceId')==device,'layout device differs')
    cases=list(leaves(tests));identifiers={'P1RecoveryLayoutUITests/'+m+'()' for m in methods}
    require(len(cases)==count and {r.get('nodeIdentifier') for r in cases}==identifiers and all(r.get('result')=='Passed' for r in cases),'wrong layout XCTest methods')
    manifest=parse(ordinary(root,'manifest.json'));require(isinstance(manifest,list) and len(manifest)==count,'wrong layout attachment inventory')
    records={};screens={};seen=set();seen_methods=set()
    for group in manifest:
        identifier=group.get('testIdentifier');require(identifier in identifiers and identifier not in seen_methods,'wrong/duplicate layout attachment method');seen_methods.add(identifier)
        method=identifier.split('/')[1][:-2]
        require(group.get('testIdentifierURL')=='test://com.apple.xcode/P0SignIn/P0SignInUITests/P1RecoveryLayoutUITests/'+method,'wrong layout target URL')
        for row in group.get('attachments',[]):
            require(row.get('deviceId')==device,'layout attachment device differs')
            path=ordinary(root,row.get('exportedFileName'));require(path.name not in seen,'reused layout attachment');seen.add(path.name)
            try:value=parse(path)
            except (ValueError,UnicodeDecodeError):value=None
            if isinstance(value,dict) and str(value.get('schema','')).startswith('p1-layout-'):
                key=(value['schema'],value.get('case'));require(key not in records,'duplicate layout report')
                require(value.get('admissionEligible') is False,'admission-shaped layout report');records[key]=(method,value)
            if valid_png(path.read_bytes()):
                name=row.get('suggestedHumanReadableName',row.get('attachmentName'))
                require(isinstance(name,str),'unnamed screenshot');require(name not in screens,'duplicate layout screenshot name');screens[name]=(method,path.name)
    geometries,actions,expected_screens=capability_expected(capability) if capability else expected()
    for name,(method,banner) in geometries.items():
        actual_method,row=records.get(('p1-layout-observation-v1',name),(None,{}))
        require(actual_method==method and row.get('geometryPassed') is True and row.get('bannerExpected') is banner and row.get('predicateFailures')==[],'missing/failed layout geometry: '+name)
        viewport=frame(row.get('viewport',{}).get('frame'));bar=frame(row.get('navigationBar',{}).get('frame'))
        require(inside(bar,viewport),'navigation outside viewport')
        metric_basis(row.get('layoutMetrics'),viewport)
        require(row.get('screenshotSource')=='XCUIScreen.main','full screen observation required')
        navigation=row.get('navigationAction',{});nav=frame(navigation.get('frame'))
        require(navigation.get('exists') is True and navigation.get('hittable') is True and inside(nav,viewport),'navigation action unavailable')
        expected_context=context(name)
        if expected_context:
            kind,largest,landscape,title=expected_context
            require(row.get('expectedKind')==kind and row.get('navigationTitle')==title and row.get('expectedLargest') is largest and row.get('expectedLandscape') is landscape,'wrong branch/trait expectation')
            require(row['layoutMetrics'].get('recoveryKind')==kind and row['layoutMetrics'].get('largestText') is largest,'actual metric branch/size differs')
            size=row.get('inheritedSizeCategory',{})
            require(size.get('exists') is True and size.get('accessibilityValue')==('sizeCategory=AX5' if largest else 'sizeCategory=default'),'inherited text size differs')
            require(viewport[2]>viewport[3] if landscape else viewport[3]>viewport[2],'actual viewport orientation differs')
            require(row.get('expectedProductionIdentity')==IDENTITIES.get(kind),'wrong production banner identity expectation')
            if kind!='none':
                identity=row.get('productionIdentity',{})
                require(identity.get('exists') is True and identity.get('label')==IDENTITIES[kind],'actual production banner identity absent')
            if title=='Details':
                passive=row.get('passiveCurrentKind',{})
                require(passive.get('exists') is True and passive.get('label')==kind,'actual fixture kind differs')
        tabs=row.get('tabs');require(isinstance(tabs,list) and len(tabs)==4,'actual tabs missing')
        validate_tab_inventory(row.get('tabCandidates'),tabs,require_nested=capability=='tablet' and name.startswith('capability-tabs-'))
        if any(g.get('resolution')=='unique-native-tabbar-v1' for g in row['tabCandidates']):
            require([t['selected'] for t in tabs]==[i==row['layoutMetrics']['selectedTab'] for i in range(4)],'structural selected tab differs from measured state')
        tab_frames=[]
        for tab in tabs:
            require(tab.get('exists') is True and tab.get('hittable') is True,'tab unavailable');f=frame(tab.get('frame'));require(inside(f,viewport),'tab outside viewport');tab_frames.append(f)
        region=row.get('region',{});require(region.get('exists') is banner,'wrong banner presence')
        if banner:
            r=frame(region.get('frame'));require(inside(r,viewport) and r[1]+r[3]<=bar[1]+1 and disjoint(r,nav) and all(disjoint(r,t) for t in tab_frames),'banner covers navigation/tabs')
            clipping_viewport(row['layoutMetrics'],viewport,r)
        if row.get('navigationTitle')=='Home':
            content=frame(row.get('content',{}).get('frame'));require(bar[1]+bar[3]<=content[1]+1 and min(content[1]+content[3],viewport[1]+viewport[3])-max(content[1],viewport[1])>=1,'content hidden by navigation')
    for name,(method,callback) in actions.items():
        actual_method,row=records.get(('p1-layout-action-v1',name),(None,{}))
        require(actual_method==method and row.get('driver')=='ordinary-XCTest-visible-coordinate-tap' and type(row.get('scrollAttempts')) is int and 0<=row['scrollAttempts']<12,'missing actual scrolled input')
        primary=re.fullmatch(r'(layout-(?:operation|direct|refresh|unreadable)-(?:default|AX5)-(?:portrait|landscape))-(resume|confirm|inspect|copy)',name)
        if primary:
            kind,largest,landscape,_=context(primary[1]);m=row.get('layoutMetrics',{});window=frame(m.get('windowBounds'))
            require(m.get('recoveryKind')==kind and m.get('largestText') is largest and (window[2]>window[3]) is landscape,'action branch/size/orientation differs')
        button=frame(row.get('button',{}).get('frame'));visible=frame(row.get('visibleIntersection'));region=frame(row.get('region',{}).get('frame'))
        measured=clipping_viewport(row.get('layoutMetrics'),frame(row.get('layoutMetrics',{}).get('windowBounds')),region)
        require(near(measured,frame(row.get('clippingViewport'))) and inside(visible,measured),'input outside measured clipping viewport')
        require(row['button'].get('hittable') is True and inside(visible,region) and inside(visible,button) and visible[2]>=min(44,button[2]) and visible[3]>=min(44,button[3]),'control clipped/unreachable')
        action_row=row
        actual_method,row=records.get(('p1-layout-callback-v1',name),(None,{}));actual=row.get('actual',{})
        require(actual_method==method and row.get('expected')==callback and actual.get('exists') is True and re.fullmatch(re.escape(callback)+r':[1-9][0-9]*',actual.get('label','')),'missing synthetic callback proof')
        validate_callback(row,action_row,callback,records,method)
    selections=[('capability-tabs-apps',1),('capability-tabs-home',0)] if capability=='tablet' else [] if capability else [('transition-apps-tab',1),('transition-home-tab',0)]
    for name,selected in selections:
        method,row=records.get(('p1-layout-tab-selection-v1',name),(None,{}))
        require(method==(methods[0] if capability else METHODS[3]) and row.get('expectedTab')==selected and row.get('driver')=='ordinary-XCTest-tap','missing actual tab input')
        metrics=row.get('actual',{});metric_basis(metrics,frame(metrics.get('windowBounds')),selected)
        control=row.get('control',{});require(control.get('exists') is True and control.get('hittable') is True and control.get('identifier')=='p1-tab-'+('Apps' if selected else 'Home'),'wrong actual tab control')
        content=row.get('content',{});require(content.get('exists') is True,'actual tab content missing')
        if capability:
            before=row.get('before',{});metric_basis(before,frame(before.get('windowBounds')),1-selected)
            same_context(before,metrics,tab_change=True)
            resolved_tabs=validate_tab_inventory(row.get('tabCandidates'),require_nested=True)
            chosen=next(t for t in resolved_tabs if t['identifier']==control['identifier'])
            require(row.get('controlBefore')==chosen,'tab input differs from structural leaf')
            require(all(chosen.get(k)==control.get(k) for k in ['identifier','label','elementType']) and inside(frame(control.get('frame')),frame(metrics['windowBounds'])),'wrong post-selection control')
            require(control.get('selected') is True,'ordinary tab input did not select control')
            require(content.get('label')==('Synthetic Apps content' if selected else 'Synthetic destination'),'wrong tab response content')
    drags={name:(method,row) for (schema,name),(method,row) in records.items() if schema=='p1-layout-drag-v1'}
    if not capability or capability=='phone':require(bool(drags),'actual interior drag evidence missing')
    for name,(method,row) in drags.items():
        after_method,after=records.get(('p1-layout-drag-after-v1',name),(None,{}))
        require(after_method==method,'wrong/missing drag after method');validate_drag(row,after)
    for (schema,name),(method,row) in records.items():
        require(schema not in ['p1-layout-failure-v1','p1-layout-target-failure-v1'],'retained layout failure in successful collection')
        if schema=='p1-layout-target-v1':validate_target(row)
        if schema=='p1-layout-observer-v1':
            expected_observers={n+'-callback-observer':m for n,(m,_) in actions.items()}
            require(expected_observers.get(row.get('search'))==method,'unbound/wrong-method passive observation')
            validate_observer(row)
        if schema=='p1-layout-fixture-input-v1':
            validate_fixture_input(row);expected_screens[name]=method
    if capability:
        validate_capability_records(records,capability)
    found={}
    for name,method in expected_screens.items():
        matches=[(m,p) for n,(m,p) in screens.items() if n==name or n.startswith(name+'_')]
        require(len(matches)==1 and matches[0][0]==method,'missing/wrong-method layout screenshot: '+name);found[name]=matches[0][1]
        screen_method,receipt=records.get(('p1-layout-screen-v1',name),(None,{}))
        require(screen_method==method,'missing screenshot orientation receipt')
        check_screen(receipt,ordinary(root,matches[0][1]).read_bytes())
        # Bind pixels to the same native scene and state as their raw geometry/input.
        bound=records.get(('p1-layout-observation-v1',name),(None,{}))[1].get('layoutMetrics')
        if bound is None and name.endswith('-visible'):
            bound=records.get(('p1-layout-action-v1',name[:-8]),(None,{}))[1].get('layoutMetrics')
        if bound is None and name.endswith('-callback'):
            bound=records.get(('p1-layout-callback-v1',name[:-9]),(None,{}))[1].get('layoutMetrics')
        if bound is not None:same_context(bound,receipt['metrics'])
    return {'collection_complete':True,'scope':'recovery-capability-only' if capability else 'recovery-full-diagnostic',
        'full_matrix_complete':capability is None,'test_count':count,'method_ids':sorted(identifiers),'geometry_count':len(geometries),
        'action_count':len(actions),'required_screenshots':found,'admissionEligible':False,'full_application':False}


def validate_target(row,suffix='target'):
    metrics=row.get('layoutMetrics',{});viewport=frame(metrics.get('windowBounds'));metric_basis(metrics,viewport)
    element=row.get('element',{});clip,scroll=scroll_record(metrics,element,element.get('identifier')=='v3.recovery.region')
    require(near(clip,frame(row.get('clippingViewport'))) and row.get('scrollPath')==scroll['path'] and row.get('offset')==scroll['contentOffset'],'target clipping/offset receipt differs')
    require(isinstance(row.get('search'),str) and bool(row['search']) and type(row.get('attempt')) is int and 0<=row['attempt']<12,'invalid bounded target attempt')
    require(row.get('case')==row['search']+'-'+suffix+'-'+str(row['attempt']),'target attempt identity differs')
    target=row.get('target');require(isinstance(target,dict) and type(target.get('exists')) is bool,'missing target observation')
    if target['exists']:frame(target.get('frame'))


def validate_observer(row):
    validate_target(row,'observation')
    require(row.get('element',{}).get('identifier')=='p1-fixture-details-list','wrong passive observer scroll')
    before=row.get('actionBefore',{});metric_basis(before,frame(before.get('windowBounds')))
    same_context(before,row['layoutMetrics'])
    count=row.get('queryCount');target=row['target']
    require(type(count) is int and count in [0,1] and target['exists'] is (count==1),'ambiguous passive receipt')
    require(isinstance(row.get('expectedLabel'),str) and bool(row['expectedLabel']),'missing passive expected label')
    if target['exists']:
        require(target.get('identifier')=='p1-recovery-last-action' and target.get('label')==row['expectedLabel'],'wrong/stale passive receipt label')


def validate_callback(row,action,expected,records,method):
    prior=action.get('priorCallbackCounter');counter=action.get('expectedCallbackCounter')
    require(type(prior) is int and prior>=0 and type(counter) is int and counter==prior+1,'invalid current-action counter')
    require(row.get('priorCallbackCounter')==prior and row.get('expectedCallbackCounter')==counter,'callback counter differs from input')
    label=expected+':'+str(counter)
    require(row['actual'].get('label')==label and row['actual'].get('identifier')=='p1-recovery-last-action','wrong current-action receipt')
    before=action['layoutMetrics'];after=row.get('layoutMetrics',{})
    require(row.get('actionBefore')==before,'callback not bound to actual input')
    metric_basis(after,frame(after.get('windowBounds')));same_context(before,after)
    search=row.get('observerSearch');attempt=row.get('observerAttempts')
    require(search==row['case']+'-callback-observer' and type(attempt) is int and 0<=attempt<12,'invalid passive observer bound')
    observations=[(m,r) for (schema,_),(m,r) in records.items() if schema=='p1-layout-observer-v1' and r.get('search')==search]
    observations.sort(key=lambda item:item[1].get('attempt',-1))
    require([r['attempt'] for _,r in observations]==list(range(attempt+1)),'missing/duplicate passive observation')
    for index,(m,observation) in enumerate(observations):
        require(m==method and observation.get('actionBefore')==before and observation.get('expectedLabel')==label,'passive observation input binding differs')
        validate_observer(observation)
        require(observation['target']['exists'] is (index==attempt),'passive search continued after exact receipt')
        if index==attempt:
            require(observation['target']==row['actual'] and observation['layoutMetrics']==after,'callback differs from final passive observation')
        else:
            pairs=[(n,d) for (s,n),(dm,d) in records.items() if s=='p1-layout-drag-v1' and d.get('search')==search and d.get('attempt')==index and dm==method]
            require(len(pairs)==1,'missing/duplicate passive scroll input')
            name,drag=pairs[0];after_method,settled=records.get(('p1-layout-drag-after-v1',name),(None,{}))
            require(after_method==method and drag.get('target')==observation['target'],'passive scroll target differs')
            same_context(observation['layoutMetrics'],drag['metrics'])
            same_context(settled['metrics'],observations[index+1][1]['layoutMetrics'])
            require(near(settled['offsetAfter'],observations[index+1][1]['offset']),'unobserved passive scroll offset')
    require(not any(d.get('search')==search and (type(d.get('attempt')) is not int or d['attempt']>=attempt) for (s,_),(_,d) in records.items() if s=='p1-layout-drag-v1'),'extra passive observer scroll')


def validate_fixture_input(row):
    metrics=row.get('layoutMetrics',{});viewport=frame(metrics.get('windowBounds'));metric_basis(metrics,viewport)
    require(row.get('driver')=='ordinary-XCTest-visible-coordinate-tap' and type(row.get('scrollAttempts')) is int and 0<=row['scrollAttempts']<12,'unsafe fixture input')
    element=row.get('element',{});require(element.get('identifier')=='p1-fixture-details-list','wrong fixture scroll element')
    clip,_=scroll_record(metrics,element,False)
    button=row.get('button',{});f=frame(button.get('frame'));visible=frame(row.get('visibleIntersection'))
    require(button.get('exists') is True and button.get('hittable') is True and button.get('identifier')==row.get('identifier'),'wrong actual fixture control')
    require(near(clip,frame(row.get('clippingViewport'))) and inside(visible,clip) and inside(visible,f)
            and visible[2]>=min(44,f[2]) and visible[3]>=min(44,f[3]),'fixture target clipped/unreachable')
    require(isinstance(row.get('tabs'),list) and len(row['tabs'])==4 and isinstance(row.get('navigationBars'),list) and row['navigationBars'],'missing fixture navigation inventory')
    require(all(t.get('exists') is True and disjoint(visible,frame(t.get('frame'))) for t in row['tabs']+row['navigationBars']),'fixture input overlaps navigation/tabs')


def validate_capability_records(records,device_class):
    def record(schema,name):
        require((schema,name) in records,'missing capability record: '+name)
        return records[(schema,name)][1]
    def geometry(name):return record('p1-layout-observation-v1',name)['layoutMetrics']
    def contextual(metrics,kind,largest,landscape):
        window=frame(metrics.get('windowBounds'));metric_basis(metrics,window)
        require(metrics['recoveryKind']==kind and metrics['largestText'] is largest,'wrong capability branch/size')
        require((window[2]>window[3]) is landscape,'wrong capability orientation')
    if device_class=='phone-default':
        contextual(geometry('capability-default-tabs'),'none',False,False)
        row=record('p1-layout-observation-v1','capability-default-tabs')
        validate_structural_tabs(row.get('tabCandidates'),row.get('tabs'))
    elif device_class=='tablet':
        initial=geometry('capability-tabs-initial');returned=geometry('capability-tabs-returned')
        apps=record('p1-layout-tab-selection-v1','capability-tabs-apps')
        home=record('p1-layout-tab-selection-v1','capability-tabs-home')
        same_context(initial,apps['before'])
        require(apps['actual']==home['before'],'tab roundtrip continuity differs')
        same_context(home['actual'],returned)
        prior=None
        for suffix in ['portrait','landscape','returned']:
            current=geometry('capability-rotation-'+suffix)
            contextual(current,'none',False,suffix=='landscape')
            if prior:same_context(prior,current,rotation=True)
            prior=current
    else:
        initial=geometry('capability-targets-initial');after=geometry('capability-targets-resume-after');changed=geometry('capability-targets-next')
        action=record('p1-layout-action-v1','capability-targets-resume')
        contextual(action['layoutMetrics'],'operation',True,True)
        require(action.get('label')=='Resume Status Check','wrong overshoot target')
        require(type(action.get('priorCallbackCounter')) is int and action['priorCallbackCounter']==0
                and type(action.get('expectedCallbackCounter')) is int and action['expectedCallbackCounter']==1,'unexpected fresh-launch callback counters')
        same_context(initial,action['layoutMetrics']);same_context(action['layoutMetrics'],after)
        inputs=[r for (schema,_),(method,r) in records.items() if schema=='p1-layout-fixture-input-v1']
        require(len(inputs)==1 and inputs[0].get('identifier')=='p1-fixture-next-recovery','missing/duplicate next-kind input')
        fixture=inputs[0];validate_fixture_input(fixture)
        contextual(fixture['layoutMetrics'],'operation',True,True)
        same_context(after,fixture['layoutMetrics']);same_context(fixture['layoutMetrics'],changed,state_change=True)
        contextual(changed,'direct',True,True)
        callback=record('p1-layout-callback-v1','capability-targets-resume')
        require(callback.get('actual',{}).get('label')=='resume-operation:1','unexpected synthetic action sequence')
        # Every search attempt is raw and consecutive; match the final visible
        # target to the exact input receipt, not merely a friendly case name.
        for name,input_row,target_key in [('capability-targets-resume',action,'button'),(fixture.get('search'),fixture,'button')]:
            attempts=[r for (schema,_),(_,r) in records.items() if schema=='p1-layout-target-v1' and r.get('search')==name]
            attempts.sort(key=lambda r:r.get('attempt',-1))
            require([r['attempt'] for r in attempts]==list(range(input_row['scrollAttempts']+1)),'missing/duplicate target attempt')
            for target in attempts:validate_target(target);contextual(target['layoutMetrics'],'operation',True,True)
            final=attempts[-1]
            require(final['layoutMetrics']==input_row['layoutMetrics'] and final['target']==input_row[target_key],'input not bound to final target observation')
            previous=None
            for target in attempts:
                if previous:same_context(previous,target['layoutMetrics'])
                previous=target['layoutMetrics']

            for index,target in enumerate(attempts[:-1]):
                pairs=[(n,r) for (schema,n),(_,r) in records.items() if schema=='p1-layout-drag-v1' and r.get('search')==name and r.get('attempt')==index]
                require(len(pairs)==1,'missing/duplicate target-controlled drag')
                drag_name,drag=pairs[0];after_drag=record('p1-layout-drag-after-v1',drag_name)
                require(drag.get('target')==target['target'],'drag target differs from search observation')
                same_context(target['layoutMetrics'],drag['metrics'])
                same_context(after_drag['metrics'],attempts[index+1]['layoutMetrics'])
                require(near(after_drag['offsetAfter'],attempts[index+1]['offset']),'unobserved scroll after controlled drag')
            require(not any(r.get('search')==name and (type(r.get('attempt')) is not int or r['attempt']>=input_row['scrollAttempts']) for (schema,_),(_,r) in records.items() if schema=='p1-layout-drag-v1'),'extra target-controlled drag')
