import unittest,hashlib,copy,json
import packed_frames as p

class Tests(unittest.TestCase):
    def fixture(self):
        regions=[dict(role=role,x=i*3,y=0,width=2,height=2) for i,role in enumerate(p.ROLES)]
        plan=dict(schema='p1-direct-roi-plan-v1',session='a'*32,windowID=1,geometrySHA256='b'*64,sourceWidth=20,sourceHeight=4,sourceStride=80,regions=regions)
        raw=bytes(range(96));manifest=[]
        for i,r in enumerate(regions):manifest.append(dict(role=r['role'],rectangle=[r['x'],0,2,2],offset=i*16,bytes=16,stride=8,sha256=hashlib.sha256(raw[i*16:i*16+16]).hexdigest()))
        rows=[]
        for i in range(2):rows.append(dict(index=i,callbackBeforeMach=100+i*10,callbackAfterMach=101+i*10,status=0,statusName='complete',ptsValue=i+1,ptsTimescale=60,ptsFlags=1,newFrame=True,session='a'*32,geometrySHA256='b'*64,displayTimeMach=50+i*10,width=20,height=4,bytesPerRow=80,contentRect=[0,0,20,4],contentScale=1,scaleFactor=1,packedPixels=f'frame-{i:05d}.rois.bgra',packedPixelSHA256=hashlib.sha256(raw).hexdigest(),regions=copy.deepcopy(manifest),copiedBytes=96))
        return dict(frames=rows,completeFrames=2,deliveredRecords=2,overflowRecords=0,copiedBytes=192,error=None),plan,raw
    def test_retained_actual_crops(self):
        s,plan,raw=self.fixture();rows=p.inspect(s,plan,timebase=(125,3),expected_geometry=([0,0,20,4],1,1),load=lambda n:raw)
        self.assertEqual(rows[1]['crops']['anchor-4'],raw[80:96])
    def test_any_failure_no_subset(self):
        changes=[lambda s:s.update(overflowRecords=1),lambda s:s['frames'][0].update(error='failure'),lambda s:s['frames'][0].update(session='c'*32),lambda s:s['frames'][1].update(displayTimeMach=50),lambda s:s['frames'][0].update(callbackAfterMach=10**9),lambda s:s.update(completeFrames=1)]
        for change in changes:
            s,plan,raw=self.fixture();change(s)
            with self.assertRaises(ValueError):p.inspect(s,plan,timebase=(125,3),expected_geometry=([0,0,20,4],1,1),load=lambda n:raw)
    def test_swapped_crops_or_bytes_reject(self):
        s,plan,raw=self.fixture();s['frames'][0]['regions'].reverse()
        with self.assertRaises(ValueError):p.inspect(s,plan,timebase=(125,3),expected_geometry=([0,0,20,4],1,1),load=lambda n:raw)
        s,plan,raw=self.fixture()
        with self.assertRaises(ValueError):p.inspect(s,plan,timebase=(125,3),expected_geometry=([0,0,20,4],1,1),load=lambda n:raw[::-1])
    def test_ocr_input_is_actual_fixed_control(self):
        s,plan,raw=self.fixture();data=p.ocr_input(s,plan,timebase=(125,3),expected_geometry=([0,0,20,4],1,1),load=lambda n:raw)
        row=json.loads(data)['frames'][0]
        self.assertEqual(row['offset'],0);self.assertEqual(row['controlSHA256'],hashlib.sha256(raw[:16]).hexdigest())
        self.assertEqual(row['file'],'frame-00000.rois.bgra');self.assertEqual(row['record'],1)
    def test_boolean_reference_rejected(self):
        s,plan,raw=self.fixture()
        with self.assertRaises(ValueError):p.inspect(s,plan,timebase=(125,3),expected_geometry=([0,0,20,4],True,True),load=lambda n:raw)
    def test_first_prerequisite_keeps_actual_index(self):
        s,plan,raw=self.fixture();row=s['frames'][1]
        result=p.inspect_first(row,plan,timebase=(125,3),load=lambda n:raw)
        self.assertEqual(result['index'],1);self.assertFalse(result['allDeliveredRecordsEstablished'])
        row['regions'][0]['sha256']='a'*64
        with self.assertRaises(ValueError):p.inspect_first(row,plan,timebase=(125,3),load=lambda n:raw)
    def test_metadata_does_not_alias_input(self):
        s,plan,raw=self.fixture();rows=p.inspect(s,plan,timebase=(125,3),expected_geometry=([0,0,20,4],1,1),load=lambda n:raw)
        s['frames'][0]['regions'][0]['offset']=999;s['frames'][0]['contentRect'][0]=999
        self.assertEqual(rows[0]['regions'][0]['offset'],0);self.assertEqual(rows[0]['sourceGeometry'][0][0],0)
    def test_pts_and_unknown_fields_reject(self):
        for key,value in (('ptsFlags',0),('ptsTimescale',True),('foreign',1)):
            s,plan,raw=self.fixture();s['frames'][0][key]=value
            with self.assertRaises(ValueError):p.inspect(s,plan,timebase=(125,3),expected_geometry=([0,0,20,4],1,1),load=lambda n:raw)
        s,plan,raw=self.fixture();del s['frames'][0]['ptsValue']
        with self.assertRaises(ValueError):p.inspect(s,plan,timebase=(125,3),expected_geometry=([0,0,20,4],1,1),load=lambda n:raw)
    def test_unknown_status_and_geometry_fail(self):
        for update in ({'statusName':'blank'},{'status':True},{'contentRect':[1,0,20,4]},{'packedPixels':'../other'}):
            s,plan,raw=self.fixture();s['frames'][1].update(update)
            with self.assertRaises(ValueError):p.inspect(s,plan,timebase=(125,3),expected_geometry=([0,0,20,4],1,1),load=lambda n:raw)

if __name__=='__main__':unittest.main()
