import unittest,copy,json,sys,struct,zlib,ast
from pathlib import Path
from hashlib import sha256
import timeout_case as t
sys.path.insert(0,str(t.VIDEO))
from test_analyze import Analysis

def png(channel):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',100,100,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+bytes([channel])*300)*100))+chunk(b'IEND',b'')

def exports_fixture(device,inputs):
    method='testProbeTimeoutPixels';identifier='P0SignInUITests/'+method+'()'
    url='test://com.apple.xcode/P0SignIn/P0SignInUITests/P0SignInUITests/'+method
    summary=dict(result='Passed',passedTests=1,failedTests=0,skippedTests=0,totalTestCount=1,expectedFailures=0,devicesAndConfigurations=[{'device':{'deviceId':device}}])
    tests={'testNodes':[{'nodeType':'Test Case','nodeIdentifier':identifier,'nodeIdentifierURL':url,'result':'Passed'}]}
    controls=dict(schema='p1-video-controls-v1',scenario='timeout',windowFrame=[0,0,300,200],copyFrame=[10,10,100,30],markerFrame=[20,170,192,16],copyLabel='Copy Details',copyHittable=True)
    complete=dict(schema='p1-video-completion-v1',scenario='timeout',completed=True,copyAfterLabel='Copy Details',copyAfterHittable=True,admissionEligible=False)
    clock=lambda phase,lo,hi:dict(name='video-timeout-'+phase,beforeUptime=lo,afterUptime=hi,clock='XCTest-process-systemUptime; not assumed equal to app clock')
    values={'controls':controls,'input':inputs,'complete':complete,'before':png(254),'after':png(255),'before-clock':clock('before',8,8.5),'after-clock':clock('after',12,12.5)}
    rows=[];files={}
    for name,value in values.items():
        leaf=name+('.png' if type(value) is bytes else '.json')
        files[leaf]=value if type(value) is bytes else t.handoff_contract.canonical(value)
        rows.append(dict(deviceId=device,exportedFileName=leaf,suggestedHumanReadableName='video-timeout-'+name))
    return dict(summaryBytes=t.handoff_contract.canonical(summary),testsBytes=t.handoff_contract.canonical(tests),manifestBytes=t.handoff_contract.canonical([dict(testIdentifier=identifier,testIdentifierURL=url,attachments=rows)]),files=files)


class Tests(unittest.TestCase):
    def fixture(self):
        calibration,decoded,events,_,controls,strip=Analysis().fixture()
        identity=dict(session='a'*32,simulatorUDID='11111111-1111-1111-1111-111111111111',hostPID=123,appContainerReceiptSHA256='b'*64,sourceSHA256='c'*64)
        apps=[];mach=[];commands=[];receipts=[]
        for command in calibration['commands']:
            row=dict(id=command['id'],kind=command['kind'],hostBeforeNs=round(command['hostBefore']*1e9),hostAfterNs=round(command['hostAfter']*1e9),response=command['response'])
            commands.append(row);receipts.append(dict(requestBytes=t.handoff_contract.canonical({'id':row['id'],'kind':row['kind']}),responseBytes=t.handoff_contract.canonical(row['response']),hostBeforeNs=row['hostBeforeNs'],hostAfterNs=row['hostAfterNs'],errorType=None))
        for n,row in enumerate(calibration['exchanges']):
            phase=row['stage'];ordinal=n%8+1;hb=round(row['hostBefore']*1e9);ha=round(row['hostAfter']*1e9)
            apps.append(dict(phase=phase,ordinal=ordinal,requestID=row['id'],hostBeforeNs=hb,hostAfterNs=ha,appReceive=row['appReceive'],appSend=row['appSend']))
            mach.append(dict(phase=phase,ordinal=ordinal,hostBeforeNs=hb-1000,hostAfterNs=hb,machTicks=hb-500,timebaseNumer=1,timebaseDenom=1))
        clock=dict(schema='p1-direct-bound-clocks-v1',identity=identity,appExchanges=apps,machExchanges=mach,model='scenario-wide-constant-offset-and-unit-rate-conditional',admissionEligible=False)
        added=[]
        for i,(source,anchor) in enumerate((s,a) for s in ('packet','feature') for a in range(1,5)):
            now=108+i*.001
            added.append(dict(type='direct-anchor-draw',schema='p1-direct-anchor-draw-v1',session='a'*32,uptime=now,clock='app-ProcessInfo.systemUptime',timingMeaning='fixture-draw-only',displayTimeEstablished=False,admissionEligible=False,enqueuedUptime=109.1,journalStartUptime=109.2,priorWrites=[],source=source,anchor=anchor,draw=1,beforeUptime=now,afterUptime=now+.0001))
        added.append(dict(type='direct-anchor-initial-draws',schema='p1-direct-anchor-initial-draws-v1',session='a'*32,uptime=109.1,clock='app-ProcessInfo.systemUptime',timingMeaning='fixture-draw-only',displayTimeEstablished=False,admissionEligible=False,enqueuedUptime=109.1,journalStartUptime=109.2,priorWrites=[],firstDrawSources=[dict(source=s,anchor=a) for s in ('packet','feature') for a in range(1,5)],initialDrawsEnqueued=True,retainedEvidenceRequired=True))
        events=events[:1]+added+events[1:]
        records=[];ocr=[];markers=[]
        for frame in decoded['observations']:
            i=frame['index'];label=frame['label'];path=f'frame-{i:05d}.rois.bgra'
            records.append(dict(index=i,status='complete',newFrame=True,displayTicks=round((100+frame['pts'])*1e9),timebaseNumer=1,timebaseDenom=1,regions=[dict(role='control',offset=0,sha256='d'*64,rectangle=[0,0,20,10])],packedPixels=path,packedSHA256='e'*64))
            ocr.append(dict(record=i+1,file=path,packedSHA256='e'*64,controlSHA256='d'*64,pixelSize=[20,10],resampled=False,absenceEstablished=False,label=label,observations=[dict(text=label,confidence=.99,box=[0,0,1,1])]))
            markers.append(dict(schema='p1-direct-complete-crop-geometry-v1',nativeIndex=i,session='a'*32,packedPixelSHA256='e'*64,displayTimeMach=str(records[-1]['displayTicks']),streamBindingProofSHA256='f'*64,geometryProof={'primitiveValid':True},actualMarker=i+1,admissionEligible=False))
        raw=t.evidence_joins.ocr_manifest(records,'a'*32);output=dict(schema='p1-direct-control-ocr-v1',session='a'*32,inputSHA256=sha256(raw).hexdigest(),admissionEligible=False,allFramesClassified=True,frames=ocr)
        independent=[dict(phase=p,label='Copy Details',observations=[dict(text='Copy Details',confidence=.99,box=[0,0,1,1])],decodedMarker=m) for p,m in (('before',1),('after',390))]
        exports=exports_fixture(identity['simulatorUDID'],controls)
        for row in independent:
            leaf=row['phase']+'.png';row.update(exportedFileName=leaf,pngSHA256=sha256(exports['files'][leaf]).hexdigest(),pixelSize=[100,100])
        return dict(screenshot_exports=exports,clock_document=clock,expected_identity=identity,commands=commands,raw_receipts=receipts,events=events,strip=strip,controls=controls,records=records,marker_proofs=markers,ocr_input_bytes=raw,ocr_result=output,independent=independent,stream_binding_hash='f'*64)
    def test_synthetic_conditional_join(self):
        r=t.inspect(**self.fixture());self.assertTrue(r['conditionalTimeoutEvidence']);self.assertFalse(r['admissionEligible']);self.assertFalse(r['fullP1Established'])
    def test_unknown_pixel_rejects(self):
        d=self.fixture();d['ocr_result']['frames'][60].update(label='unknown',observations=[])
        with self.assertRaises(ValueError):t.inspect(**d)
    def test_dropped_marker_or_raw_response_rejects(self):
        for mode in ('marker','receipt'):
            d=self.fixture()
            if mode=='marker':d['marker_proofs'].pop()
            else:d['raw_receipts'][0]['responseBytes']=b'{}'
            with self.assertRaises(ValueError):t.inspect(**d)
    def test_gap_and_missing_independent_reject(self):
        d=self.fixture();d['records'][60]['displayTicks']+=200_000_000
        with self.assertRaises(ValueError):t.inspect(**d)
        d=self.fixture();d['independent'].pop()
        with self.assertRaises(ValueError):t.inspect(**d)

    def test_arbitrary_ocr_input_hash_rejected(self):
        d=self.fixture();d['ocr_input_bytes']=b'{}';d['ocr_result']['inputSHA256']=sha256(b'{}').hexdigest()
        with self.assertRaisesRegex(ValueError,'OCR manifest'):t.inspect(**d)
    def test_partial_or_changed_manifest_rejected(self):
        for mode in ('drop','offset','hash','width','reorder'):
            d=self.fixture();value=json.loads(d['ocr_input_bytes'])
            if mode=='drop':value['frames'].pop()
            elif mode=='reorder':value['frames'].reverse()
            else:value['frames'][0][{'offset':'offset','hash':'packedSHA256','width':'width'}[mode]]=999
            raw=t.handoff_contract.canonical(value);d['ocr_input_bytes']=raw;d['ocr_result']['inputSHA256']=sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError,'OCR manifest'):t.inspect(**d)
    def test_interior_independent_markers_rejected(self):
        d=self.fixture();d['independent'][0]['decodedMarker']=200;d['independent'][1]['decodedMarker']=201
        with self.assertRaisesRegex(ValueError,'bracket calibration'):t.inspect(**d)
    def test_actual_png_and_hash_required(self):
        for mode in ('hash','bytes','size','same'):
            d=self.fixture()
            if mode=='hash':d['independent'][0]['pngSHA256']='0'*64
            elif mode=='size':d['independent'][0]['pixelSize']=[99,100]
            elif mode=='same':d['screenshot_exports']['files']['before.png']=d['screenshot_exports']['files']['after.png']
            else:d['screenshot_exports']['files']['before.png']=b'not a PNG'
            with self.assertRaises(ValueError):t.inspect(**d)
    def test_export_method_device_input_and_inventory_required(self):
        for mode in ('method','device','input','inventory','clock'):
            d=self.fixture();e=d['screenshot_exports']
            if mode=='method':
                v=json.loads(e['testsBytes']);v['testNodes'][0]['nodeIdentifier']='Other/test()';e['testsBytes']=t.handoff_contract.canonical(v)
            elif mode=='device':
                v=json.loads(e['manifestBytes']);v[0]['attachments'][0]['deviceId']='other';e['manifestBytes']=t.handoff_contract.canonical(v)
            elif mode=='input':
                v=json.loads(e['files']['input.json']);v['firstAfter']+=.5;e['files']['input.json']=t.handoff_contract.canonical(v)
            elif mode=='clock':del e['files']['before-clock.json']
            else:e['files']['foreign.json']=b'{}'
            with self.assertRaises(ValueError):t.inspect(**d)
    def test_screenshot_runner_order_is_same_clock_only(self):
        for phase,key,value in [('before','afterUptime',9.1),('after','beforeUptime',10.5)]:
            d=self.fixture();e=d['screenshot_exports'];name=phase+'-clock.json';v=json.loads(e['files'][name]);v[key]=value;e['files'][name]=t.handoff_contract.canonical(v)
            with self.assertRaisesRegex(ValueError,'runner ordering'):t.inspect(**d)
    def test_png_validator_is_maintained_function(self):
        folder=Path(__file__).parent/'fixtures'
        raw=(folder/'maintained_valid_png.py').read_bytes()
        binding=json.loads((folder/'maintained_valid_png.json').read_bytes())
        self.assertEqual(binding['sourceSHA256'],'8682c21e8e499a45d0090a7db8e5cc606f83a98d527a777aa3f2736645c494c8')
        self.assertEqual(binding['fixtureSHA256'],'3c29c59cd9dd4d9479b61c123a54f8201b8eed9fc97ef37f4e04cbeb3cae47bb')
        self.assertEqual(sha256(raw).hexdigest(),binding['fixtureSHA256'])
        def body(source):return ast.dump(next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='valid_png'))
        self.assertEqual(body(raw.decode()),body(Path(t.evidence_joins.__file__).read_text()))
    def test_manifest_matches_packed_frames_wire_format(self):
        sys.path.insert(0,str(t.LOCAL/'pixels'))
        import packed_frames
        from test_packed_frames import Tests as Pixels
        samples,plan,raw=Pixels().fixture();kwargs=dict(timebase=(125,3),expected_geometry=([0,0,20,4],1,1),load=lambda n:raw)
        records=packed_frames.inspect(samples,plan,**kwargs)
        self.assertEqual(t.evidence_joins.ocr_manifest(records,plan['session']),packed_frames.ocr_input(samples,plan,**kwargs))
    def test_boolean_ocr_or_marker_ordinal_rejected(self):
        for key in ('ocr','marker'):
            d=self.fixture()
            if key=='ocr':d['ocr_result']['frames'][0]['record']=True
            else:d['marker_proofs'][0]['nativeIndex']=False
            with self.assertRaises(ValueError):t.inspect(**d)

if __name__=='__main__':unittest.main()
