import unittest,plistlib
from runner_recipe import configure
class Tests(unittest.TestCase):
    def call(self,value):return configure(plistlib.dumps(value),plistlib.dumps({'CFBundleIdentifier':'runner'}),'a'*32,'runner')
    def test_exact_only_environment_delta(self):
        value={'Tests':{'TestBundlePath':'__TESTROOT__/P0SignInUITests.xctest','IsUITestBundle':True,'EnvironmentVariables':{'A':'B'}}}
        raw,_=self.call(value);new=plistlib.loads(raw);self.assertEqual(new['Tests']['EnvironmentVariables'].pop('P1_DIRECT_SESSION'),'a'*32)
        self.assertEqual(new,value)
    def test_stale_restriction_rejects(self):
        for extra in ({'OnlyTestIdentifiers':['other']},{'EnvironmentVariables':{'P1_DIRECT_SESSION':'old'}}):
            with self.assertRaises(ValueError):self.call({'T':dict(TestBundlePath='P0SignInUITests.xctest',IsUITestBundle=True,**extra)})
    def test_multiple_or_no_targets_reject(self):
        for v in ({},{'a':{'TestBundlePath':'P0SignInUITests','IsUITestBundle':True},'b':{'TestBundlePath':'P0SignInUITests','IsUITestBundle':True}}):
            with self.assertRaises(ValueError):self.call(v)
if __name__=='__main__':unittest.main()
