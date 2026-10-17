"""Strict diagnostic layout evidence, separate from timing feasibility."""
import re
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
        require(actual_method==method and row.get('geometryPassed') is True and row.get('bannerExpected') is banner,'missing/failed layout geometry: '+name)
        viewport=frame(row.get('viewport',{}).get('frame'));bar=frame(row.get('navigationBar',{}).get('frame'))
        require(inside(bar,viewport),'navigation outside viewport')
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
        tabs=row.get('tabs');require(isinstance(tabs,list) and len(tabs)==4 and {t.get('label') for t in tabs}=={'Home','Apps','Sources','Settings'},'actual tabs missing')
        tab_frames=[]
        for tab in tabs:
            require(tab.get('exists') is True and tab.get('hittable') is True,'tab unavailable');f=frame(tab.get('frame'));require(inside(f,viewport),'tab outside viewport');tab_frames.append(f)
        region=row.get('region',{});require(region.get('exists') is banner,'wrong banner presence')
        if banner:
            r=frame(region.get('frame'));require(inside(r,viewport) and r[3]<=min(320,viewport[3]*.4)+1 and r[1]+r[3]<=bar[1]+1 and disjoint(r,nav) and all(disjoint(r,t) for t in tab_frames),'banner covers navigation/tabs or exceeds cap')
        if row.get('navigationTitle')=='Home':
            content=frame(row.get('content',{}).get('frame'));require(bar[1]+bar[3]<=content[1]+1 and min(content[1]+content[3],viewport[1]+viewport[3])-max(content[1],viewport[1])>=1,'content hidden by navigation')
    for name,(method,callback) in actions.items():
        actual_method,row=records.get(('p1-layout-action-v1',name),(None,{}))
        require(actual_method==method and row.get('driver')=='ordinary-XCTest-visible-coordinate-tap' and type(row.get('scrollAttempts')) is int and 0<=row['scrollAttempts']<12,'missing actual scrolled input')
        button=frame(row.get('button',{}).get('frame'));visible=frame(row.get('visibleIntersection'));region=frame(row.get('region',{}).get('frame'))
        require(row['button'].get('hittable') is True and inside(visible,region) and inside(visible,button) and visible[2]>=min(44,button[2]) and visible[3]>=min(44,button[3]),'control clipped/unreachable')
        actual_method,row=records.get(('p1-layout-callback-v1',name),(None,{}));actual=row.get('actual',{})
        require(actual_method==method and row.get('expected')==callback and actual.get('exists') is True and re.fullmatch(re.escape(callback)+r':[1-9][0-9]*',actual.get('label','')),'missing synthetic callback proof')
    found={}
    for name,method in expected_screens.items():
        matches=[(m,p) for n,(m,p) in screens.items() if n==name or n.startswith(name+'_')]
        require(len(matches)==1 and matches[0][0]==method,'missing/wrong-method layout screenshot: '+name);found[name]=matches[0][1]
    return {'collection_complete':True,'test_count':4,'method_ids':sorted(identifiers),'geometry_count':len(geometries),
        'action_count':len(actions),'required_screenshots':found,'admissionEligible':False,'full_application':False}
