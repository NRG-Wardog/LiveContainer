import unittest
from roi_bytes import extract,ROLES

class CropTests(unittest.TestCase):
    def fixture(self):
        width,height,stride=8,4,40
        raw=bytes((i%256 for i in range(height*stride)))
        rois={role:(i,1,1,2) for i,role in enumerate(ROLES)}
        return raw,width,height,stride,rois
    def run_extract(self,args,**extra):
        return extract(*args,session='a'*32,record=1,**extra)
    def test_real_strided_bytes_and_same_frame_binding(self):
        args=self.fixture();crops,metadata=self.run_extract(args)
        for i,role in enumerate(ROLES):
            self.assertEqual(crops[role],args[0][40+i*4:44+i*4]+args[0][80+i*4:84+i*4])
        self.assertEqual(metadata['copiedBytes'],48)
        self.assertFalse(metadata['sourceBufferRetained']);self.assertFalse(metadata['admissionEligible'])
    def test_incomplete_or_clipped_regions_fail(self):
        for change in ('missing','clipped','overlap'):
            args=list(self.fixture())
            if change=='missing':args[-1].pop('marker')
            elif change=='clipped':args[-1]['marker']=(8,0,1,1)
            else:args[-1]['marker']=args[-1]['control']
            with self.assertRaises(ValueError):self.run_extract(args)
    def test_truncation_mutability_and_budget_fail(self):
        for raw in (self.fixture()[0][:-1],bytearray(self.fixture()[0])):
            args=list(self.fixture());args[0]=raw
            with self.assertRaises(ValueError):self.run_extract(args)
        with self.assertRaises(ValueError):self.run_extract(self.fixture(),max_bytes=47)
    def test_fractional_geometry_not_rounded_inward(self):
        args=list(self.fixture());args[-1]['control']=(0.1,1,1,2)
        with self.assertRaises(ValueError):self.run_extract(args)
    def test_record_limit_and_explicit_budget_limits(self):
        args=self.fixture()
        _,metadata=extract(*args,session='a'*32,record=6000)
        self.assertEqual(metadata['record'],6000)
        for record in (0,6001,12000,True):
            with self.assertRaises(ValueError):extract(*args,session='a'*32,record=record)
        for limit in (0,1024*1024+1,True):
            with self.assertRaises(ValueError):self.run_extract(args,max_bytes=limit)
    def test_exact_one_mib_and_one_pixel_over(self):
        width,stride=512,2048
        regions={'control':(0,0,512,511),'marker':(0,511,508,1)}
        regions.update({role:(508+i,511,1,1) for i,role in enumerate(ROLES[2:])})
        raw=bytes(stride*512)
        crops,metadata=self.run_extract((raw,width,512,stride,regions))
        self.assertEqual(metadata['copiedBytes'],1024*1024)
        self.assertEqual(sum(map(len,crops.values())),1024*1024)
        regions['marker']=(0,511,509,1)
        for i,role in enumerate(ROLES[2:-1]):regions[role]=(509+i,511,1,1)
        regions[ROLES[-1]]=(0,512,1,1)
        with self.assertRaisesRegex(ValueError,'ROI byte ceiling'):
            self.run_extract((bytes(stride*513),width,513,stride,regions))

if __name__=='__main__':unittest.main()
