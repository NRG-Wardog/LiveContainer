"""Strict diagnostic layout evidence, separate from timing feasibility."""
import re
import math
import struct
from exports import require,frame,leaves

METHODS=['testRecoveryBranchesDefault','testRecoveryBranchesLargest','testRecoveryCompactLandscape','testRecoveryStateAndSizeTransitions']
KINDS=['none','operation','direct','refresh','unreadable']
ACTIONS={'operation':{'resume':'resume-operation','confirm':'reconcile-operation'},
    'direct':{'inspect':'inspect-direct','confirm':'reconcile-direct'},'refresh':{'confirm':'reconcile-refresh'},
    'unreadable':{'copy':'copy-diagnostics-exact','confirm':'discard-unreadable'}}
TRANSITIONS=['initial','shown','largest','rotated','kind-direct','kind-refresh','kind-unreadable','kind-operation','portrait','standard-with-banner','cleared','final-root']

IDENTITIES={'operation':'A previous install may still be running','direct':'A previous certificate creation has an unresolved result',
    'refresh':'A previous refresh may still be running','unreadable':'SideStore paused changes because its recovery record is malformed\nError ID: SS-STATUS-FIXTURE'}

def context(name):
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
    bracket=metrics.get('runnerRequestBracket');require(isinstance(bracket,list) and len(bracket)==2 and all(finite(x) for x in bracket) and 0<=bracket[0]<=bracket[1],'missing runner request-duration bracket')
    start=metrics.get('startedUptime');finish=metrics.get('finishedUptime')
    require(finite(start) and finite(finish) and 0<=start<=finish,'invalid layout observation times')
    window=frame(metrics.get('windowBounds'));offered=frame(metrics.get('offeredFrame'));size=metrics.get('offeredSize')
    require(near(window,viewport) and inside(offered,window),'actual window/offered frame differs')
    require(isinstance(size,list) and len(size)==2 and all(finite(x) and x>0 for x in size) and near(size,offered[2:]),'offered parent size differs')
    orientation=metrics.get('interfaceOrientation')
    require(type(orientation) is int and orientation in ([3,4] if window[2]>window[3] else [1,2]),'native interface orientation differs')
    return offered,size

def clipping_viewport(metrics,viewport,region):
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
    require(effective[3]<=min(320,size[1]*.4)+1,'measured safe viewport exceeds cap')
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


def verify(root,summary,tests,device,parse,ordinary,valid_png):
    keys=['passedTests','failedTests','skippedTests','totalTestCount','expectedFailures']
    require(summary.get('result')=='Passed' and all(type(summary.get(k)) is int for k in keys) and [summary[k] for k in keys]==[4,0,0,4,0],'four passed/zero skipped layout tests required')
    configurations=summary.get('devicesAndConfigurations')
    require(isinstance(configurations,list) and len(configurations)==1 and configurations[0].get('device',{}).get('deviceId')==device,'layout device differs')
    cases=list(leaves(tests));identifiers={'P1RecoveryLayoutUITests/'+m+'()' for m in METHODS}
    require(len(cases)==4 and {r.get('nodeIdentifier') for r in cases}==identifiers and all(r.get('result')=='Passed' for r in cases),'wrong layout XCTest methods')
    manifest=parse(ordinary(root,'manifest.json'));require(isinstance(manifest,list) and len(manifest)==4,'wrong layout attachment inventory')
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
    geometries,actions,expected_screens=expected()
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
        tabs=row.get('tabs');require(isinstance(tabs,list) and len(tabs)==4 and {t.get('identifier') for t in tabs}=={'p1-tab-'+title for title in ['Home','Apps','Sources','Settings']},'actual tabs missing')
        inventory=row.get('tabCandidates');require(isinstance(inventory,list) and len(inventory)==4,'missing adaptive tab inventory')
        require({c.get('identifier') for c in inventory}=={t['identifier'] for t in tabs},'adaptive tab inventory differs')
        for candidate in inventory:
            found=candidate.get('candidates');require(isinstance(found,list),'missing tab candidates')
            eligible=[c for c in found if c.get('exists') is True and c.get('hittable') is True]
            require(len(eligible)==1,'ambiguous actual tab candidate')
            chosen=next(t for t in tabs if t['identifier']==candidate['identifier'])
            require(eligible[0]==chosen and type(chosen.get('elementType')) is int,'selected tab candidate differs')
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
        button=frame(row.get('button',{}).get('frame'));visible=frame(row.get('visibleIntersection'));region=frame(row.get('region',{}).get('frame'))
        measured=clipping_viewport(row.get('layoutMetrics'),frame(row.get('layoutMetrics',{}).get('windowBounds')),region)
        require(near(measured,frame(row.get('clippingViewport'))) and inside(visible,measured),'input outside measured clipping viewport')
        require(row['button'].get('hittable') is True and inside(visible,region) and inside(visible,button) and visible[2]>=min(44,button[2]) and visible[3]>=min(44,button[3]),'control clipped/unreachable')
        actual_method,row=records.get(('p1-layout-callback-v1',name),(None,{}));actual=row.get('actual',{})
        require(actual_method==method and row.get('expected')==callback and actual.get('exists') is True and re.fullmatch(re.escape(callback)+r':[1-9][0-9]*',actual.get('label','')),'missing synthetic callback proof')
    for name,selected in [('transition-apps-tab',1),('transition-home-tab',0)]:
        method,row=records.get(('p1-layout-tab-selection-v1',name),(None,{}))
        require(method==METHODS[3] and row.get('expectedTab')==selected and row.get('driver')=='ordinary-XCTest-tap','missing actual tab input')
        metrics=row.get('actual',{});metric_basis(metrics,frame(metrics.get('windowBounds')),selected)
        control=row.get('control',{});require(control.get('exists') is True and control.get('hittable') is True and control.get('identifier')=='p1-tab-'+('Apps' if selected else 'Home'),'wrong actual tab control')
        content=row.get('content',{});require(content.get('exists') is True,'actual tab content missing')
    drags={name:(method,row) for (schema,name),(method,row) in records.items() if schema=='p1-layout-drag-v1'}
    require(bool(drags),'actual interior drag evidence missing')
    for name,(method,row) in drags.items():
        viewport=frame(row.get('viewport'));metrics=row.get('metrics',{});metric_basis(metrics,viewport)
        visible=frame(row.get('visibleBounds'));interior=frame(row.get('interiorBounds'))
        require(inside(visible,viewport) and inside(visible,frame(metrics.get('offeredFrame'))) and inside(visible,frame(row.get('element',{}).get('frame'))) and inside(interior,visible),'drag outside actual viewport')
        if row.get('element',{}).get('identifier')=='v3.recovery.region':
            clip=clipping_viewport(metrics,viewport,frame(row['element']['frame']));require(inside(visible,clip),'drag outside measured recovery clipping viewport')
        require(near(interior,[visible[0]+12,visible[1]+12,visible[2]-24,visible[3]-24]),'drag edge margin differs')
        for point in [row.get('start'),row.get('end')]:
            require(isinstance(point,list) and len(point)==2 and all(finite(x) for x in point) and interior[0]<=point[0]<=interior[0]+interior[2] and interior[1]<=point[1]<=interior[1]+interior[3],'drag endpoint touches unsafe area')
        after_method,after=records.get(('p1-layout-drag-after-v1',name),(None,{}))
        require(after_method==method and after.get('foreground') is True,'drag left foreground app')
        metric_basis(after.get('metrics'),frame(after.get('viewport',{}).get('frame')))
        require(near(viewport,frame(after['viewport']['frame'])),'drag changed actual viewport')
    found={}
    for name,method in expected_screens.items():
        matches=[(m,p) for n,(m,p) in screens.items() if n==name or n.startswith(name+'_')]
        require(len(matches)==1 and matches[0][0]==method,'missing/wrong-method layout screenshot: '+name);found[name]=matches[0][1]
        screen_method,receipt=records.get(('p1-layout-screen-v1',name),(None,{}))
        require(screen_method==method,'missing screenshot orientation receipt')
        check_screen(receipt,ordinary(root,matches[0][1]).read_bytes())
    return {'collection_complete':True,'test_count':4,'method_ids':sorted(identifiers),'geometry_count':len(geometries),
        'action_count':len(actions),'required_screenshots':found,'admissionEligible':False,'full_application':False}
