#!/usr/bin/env python3
"""Independent fresh unsigned actual-host compile. Never grants P1 admission."""
import argparse
import configparser
import os
from pathlib import Path
import platform
import sys

import capture

HERE=Path(__file__).resolve().parent
original=capture.base.module('reviewed_p1_host_helper',HERE.parent/'native_gate.py')
p0=original.p0
require=original.require
PARENT='fbaafb939bfd3b7c08fdc8ff4b8d2aae43526ece'
SUBMODULES={
 'LiveContainer/OpenSSL':{'commit':'623c84da314e85363236507ca38a4bde65df21c3','declared_repository':'https://github.com/krzyzanowskim/OpenSSL','repository':'https://github.com/krzyzanowskim/OpenSSL','tree':'21bc09387e7f91a46eb8bd26587ce1d052277801'},
 'LiveContainer/litehook':{'commit':'8025e0c8ebdf5cdd1d2a4f45025813234bf9dc55','declared_repository':'https://github.com/LiveContainer/litehook','repository':'https://github.com/LiveContainerMirror/litehook.git','tree':'62bc06a17a1c12d805aec1ada25910bfa9f89781'}}

class Host:
    # Exact reviewed command/environment, full-history clone and unsigned build
    # implementations. Only acquisition/source identity is scoped to new P1.
    run=original.Capture.run
    clone=original.Capture.clone
    native_build=original.Capture.native_build
    def __init__(self,host,work,evidence,approved):
        self.host,self.work,self.evidence,self.approved=host,work,evidence,approved
        self.sources=work/'sources';self.results=work/'results';self.live=self.sources/'LiveContainer'
        self.stage='initialization'
        self.state={'schema':'p1-independent-host-compile-v1','status':'FAILED_OR_INCOMPLETE',
            'source':capture.SOURCE,'source_sha256':capture.SOURCE_SHA,'approved_inputs_sha256':approved,
            'production_ready':False,'admission_eligible':False,'full_native_lane_executed':False,
            'ui_executed':False,'ipa_built':False,'fresh_dependency_validation':False}
    def proof(self):
        source=p0.primitives.verify_checkout(self.live,capture.SOURCE['commit'],owner='LiveContainer',require_full_history=True)
        require(source['tree']==capture.SOURCE['tree'],'host source tree differs')
        source['origin']=p0.primitives.verify_origin(self.live,capture.SOURCE['repository'],capture.SOURCE['commit'])
        require(original.git(self.live,'rev-parse','HEAD^').decode().strip()==PARENT,'wrong source parent')
        require(original.git(self.live,'diff','--name-only',PARENT,capture.SOURCE['commit']).decode().splitlines()==[capture.base.SHELL],'unexpected P1 source transition')
        require(capture.sha(self.live/capture.base.SHELL)==capture.SOURCE_SHA,'compiler shell bytes differ')
        result={'LiveContainer':source}
        for path,row in SUBMODULES.items():
            child=self.sources/path
            require(original.git(child,'rev-parse','HEAD^{tree}').decode().strip()==row['tree'],'dependency tree differs')
            result[path]=p0.primitives.verify_origin(child,row['repository'],row['commit'])
        return result
    def execute(self,inputs):
        require(platform.system()=='Darwin','native host compile requires macOS')
        require(not self.work.exists() and not self.evidence.exists(),'fresh host build/evidence required')
        self.sources.mkdir(parents=True);self.results.mkdir();(self.evidence/'logs').mkdir(parents=True);(self.evidence/'provenance').mkdir()
        try:
            inherited=p0.parse((self.host/'ci/p0/inputs-sidestore.json').read_bytes())
            require({k:v for k,v in inherited['submodules'].items() if k.startswith('LiveContainer/')}==SUBMODULES,'dependency pins differ from reviewed P0')
            require(os.environ.get('GITHUB_REPOSITORY')=='NRG-Wardog/LiveContainer' and os.environ.get('GITHUB_REF')=='refs/heads/validation/p1-native-basis','dedicated workflow required')
            commit=original.git(self.host,'rev-parse','HEAD').decode().strip();require(commit==os.environ.get('GITHUB_SHA'),'workflow host differs')
            self.state['github']={k:os.environ.get(k) for k in ['GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REPOSITORY']}
            self.state['validation_tree']=original.git(self.host,'rev-parse','HEAD^{tree}').decode().strip()
            require('Xcode 26.4.1' in self.run('xcode-version',['xcodebuild','-version']),'unreviewed Xcode')
            self.run('swift-version',['swift','--version'])
            self.stage='fetch';self.clone('livecontainer',capture.SOURCE,self.live)
            links={path:row['git_object'] for path,row in original.entries(self.live,capture.SOURCE['commit']).items() if row['type']=='commit'}
            require(set(links)=={Path(p).name for p in SUBMODULES},'unreviewed child dependency')
            modules=configparser.ConfigParser(interpolation=None);modules.read(self.live/'.gitmodules')
            for path,row in SUBMODULES.items():
                name=path.split('/',1)[1]
                require([dict(modules[s]) for s in modules.sections() if modules[s].get('path')==name]==[{'path':name,'url':row['declared_repository']}] and links[name]==row['commit'],'declared dependency differs')
                self.clone(name.lower(),row,self.live/name)
            p0.dump(self.evidence/'provenance/source-before.json',self.proof())
            self.native_build()
            p0.dump(self.evidence/'provenance/source-after.json',self.proof())
            self.state['status']='CAPTURED_FOR_REVIEW';self.stage='captured'
        finally:
            self.state['last_stage']=self.stage
            (self.evidence/'provenance/approved-inputs.json').write_bytes(inputs.read_bytes())
            p0.dump(self.evidence/'provenance/result.json',self.state)
            p0.dump(self.evidence/'evidence-index.json',{'schema':'p1-diagnostic-evidence-index-v1','files':{str(p.relative_to(self.evidence)):capture.sha(p) for p in sorted(self.evidence.rglob('*')) if p.is_file() and p.name!='evidence-index.json'}})

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--host-root',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True)
    p.add_argument('--approved-inputs-sha256',required=True);p.add_argument('--work',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True)
    a=p.parse_args();capture.validate(a.host_root,a.inputs,a.approved_inputs_sha256)
    Host(a.host_root.resolve(),a.work,a.evidence,a.approved_inputs_sha256).execute(a.inputs)
