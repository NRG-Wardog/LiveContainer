"""Bind only the reviewed timeout observer session into one original UI recipe."""
from hashlib import sha256
import plistlib,re
from fixture_channel import require,canonical

def configure(original,runner_info,session,runner_id):
    require(type(original) is bytes and type(runner_info) is bytes,'retained plist bytes')
    require(type(session) is str and re.fullmatch('[0-9a-f]{32}',session),'fresh session')
    info=plistlib.loads(runner_info);require(info.get('CFBundleIdentifier')==runner_id,'built runner identity')
    value=plistlib.loads(original);count=0
    def inject(node):
        nonlocal count
        if type(node) is dict:
            if 'TestBundlePath' in node:
                require(node.get('IsUITestBundle') is True and type(node['TestBundlePath']) is str and
                        'P0SignInUITests' in node['TestBundlePath'],'one expected UI bundle')
                require('OnlyTestIdentifiers' not in node and 'SkipTestIdentifiers' not in node,'unexpected recipe test restriction')
                env=node.setdefault('EnvironmentVariables',{})
                require(type(env) is dict and not any(k.startswith('P1_DIRECT') for k in env),'stale observer environment')
                env['P1_DIRECT_SESSION']=session;count+=1
            for child in list(node.values()):inject(child)
        elif type(node) is list:
            for child in node:inject(child)
    inject(value);require(count==1,'exactly one original UI target')
    proposed=plistlib.dumps(value)
    return proposed,canonical({'schema':'p1-direct-runner-recipe-v1','session':session,'runner':runner_id,
           'originalSHA256':sha256(original).hexdigest(),'runnerInfoSHA256':sha256(runner_info).hexdigest(),
           'modifiedSHA256':sha256(proposed).hexdigest(),'injectedEnvironmentKeys':['P1_DIRECT_SESSION'],
           'testSelection':'P0SignInUITests/P0SignInUITests/testProbeTimeoutPixels','admissionEligible':False})
