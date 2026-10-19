#!/usr/bin/env python3
"""Linux-only host allocation capture. Never links or runs a guest engine."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_gate as native
from native_gate import AK_COMMIT, AK_TREE, BASIS, FORK_SHA, FORK_URL, ordinary, parse, sha, dump, require, git, full_sha

# The driver compiles the actual loader and hook harness. Every repository
# source dependency is sealed here; downloaded engine headers are proved
# separately by the exact app fork's archive checksum and header byte inventory.
ALLOCATION_SOURCES = {'Native/Loader/elf_loader_emulator.cpp': '44a8b61dcf1d4d8d309f624c442c008278d33a68ccf14ec4dc9f4757d9cdce2a', '.ci/native-tests/fixtures/cxx_allocation_unit.cpp': 'cbbe243428144a0584593246a4d4b92d00ee9807cff457404d8d3a18d491680c', '.ci/native-tests/fixtures/cxx_allocation_hook_unit.cpp': '0614c634f0d8ca648bde35fde4d55ec07f657becb8b2a5cd1d78a92d7a0f1c62', 'Native/Loader/cxx_allocation_runtime.h': 'b76bdc4043c497700f93aff5ad82968f7660ebb6720bb2c71ea5615000380a62', 'Native/Loader/elf_loader_emulator.h': '16eb67e76dc4ae94350e55968e9313c2f4163817182c08af76a5c85b2ec09327', 'Native/Loader/elf_metadata_bounds.h': '7acd9287cc351b55141f40a0baecda9c3d3202a420cf4b7f0f2515572d877253', 'Native/Loader/android_tls_runtime.h': '51c6c123d78b2d53f70e1720c8bf8aa934cbdb149a66df0a6763b6614f4fda07', 'Native/Loader/vm_initialization_diagnostics.h': '023b34540c9fb31fcb6059fea3236eb411fc52d0438025dbe9d72e88c9337e5c', 'Native/Loader/adi_consumption_debug.h': '077b377c87b201893f83afbff5a4dd37e01354253f08045a3831adcb50022346', 'Native/anisette_base.h': '6c47c3fef881d99082d1eb7e687fc78de6339568118259884d2b8a0d6c6e8664', 'Native/include/anisette_core.h': 'ca1ea4005f77dcca17c68965ba2dd1f65596e282a57adb4277f1d90d8bd11f02', '.ci/native-tests/test_cxx_allocation.py': 'c0f2c97e40be67ac381792a9ebae60dbdb1363e0517741b1cbfa90f0d342d3d7'}
VARIANTS = ('normal', 'optimized', 'sanitized')


def verify_allocation_receipt(value):
    require(set(value)=={'results','guest_execution','leak_sanitizer_enabled','source_sha256'}, 'allocation receipt schema differs')
    require(value['guest_execution'] is False and value['leak_sanitizer_enabled'] is False, 'allocation receipt overclaims execution or sanitizer mode')
    require(ALLOCATION_SOURCES and value['source_sha256']==ALLOCATION_SOURCES, 'allocation source inventory differs')
    require(set(value['results'])==set(VARIANTS), 'all three allocation variants required')
    for result in value['results'].values():
        require(set(result)=={'allocator','hooks'}, 'allocation case schema differs')
        for label,count in (('allocator',32),('hooks',51)):
            expected={'checks':count,'failures':0,'guest_execution':False}
            require(result[label]==expected and all(type(result[label][k]) is type(v) for k,v in expected.items()), 'allocation checks failed, skipped, or differ')
    return value


def expected_commands(output, source, headers, variant, hooks):
    flags={'normal':[], 'optimized':['-O2','-DNDEBUG'], 'sanitized':['-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer']}[variant]
    common=['c++','-std=c++17','-ffunction-sections','-fdata-sections',*flags]
    for folder in (source/'Native/Loader',source/'Native',source/'Native/include',headers):common.extend(['-I',str(folder)])
    binary=output/(variant+'-hooks' if hooks else variant)
    if hooks:
        return [common+[str(source/'.ci/native-tests/fixtures/cxx_allocation_hook_unit.cpp'),'-o',str(binary)],[str(binary.resolve())]]
    obj=output/(variant+'.o')
    return [common+['-c',str(source/'Native/Loader/elf_loader_emulator.cpp'),'-o',str(obj)],
            common+['-Wl,--gc-sections',str(source/'.ci/native-tests/fixtures/cxx_allocation_unit.cpp'),str(obj),'-o',str(binary)],
            [str(binary.resolve())]]


def verify_raw_commands(output, value, source, headers):
    for variant in VARIANTS:
        for suffix,kind,count in (('', 'allocator', 3),('-hooks','hooks',2)):
            commands=parse(ordinary(output,variant+suffix+'.json').read_bytes())
            require(isinstance(commands,list) and len(commands)==count, 'allocation command count differs')
            require([x.get('command') for x in commands]==expected_commands(output,source,headers,variant,bool(suffix)), 'allocation command flags, inputs or executable differ')
            for command in commands:
                require(set(command)=={'command','exit_code','stdout','stderr'}, 'allocation command schema differs')
                require(type(command['exit_code']) is int and command['exit_code']==0, 'allocation command failed')
                require(command['stderr']=='', 'allocation command emitted diagnostics')
                require(isinstance(command['command'],list) and all(isinstance(x,str) for x in command['command']), 'allocation argv missing')
            require(parse(commands[-1]['stdout'])==value['results'][variant][kind], 'allocation raw output differs from receipt')


def extract_headers(archive, destination):
    require(sha(archive.read_bytes())==FORK_SHA, 'selected Unicorn archive checksum differs')
    found={}
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            parts=Path(item.filename).parts
            require(not item.filename.startswith('/') and '..' not in parts, 'unsafe engine archive path')
            # Only header bytes are materialized. No library or guest executable
            # from the archive is extracted, linked, loaded, or run.
            if len(parts)<2 or parts[-2]!='unicorn' or not parts[-1].endswith('.h'):
                continue
            require(((item.external_attr>>16)&0o170000)!=0o120000 and item.file_size<1024*1024, 'unsafe engine header entry')
            data=z.read(item)
            require(parts[-1] not in found or found[parts[-1]]==data, 'engine header slices disagree')
            found[parts[-1]]=data
    require({'unicorn.h','arm64.h','platform.h'}<=set(found), 'exact fork headers unavailable')
    (destination/'unicorn').mkdir(parents=True)
    for name,data in found.items():(destination/'unicorn'/name).write_bytes(data)
    return {name:sha(data) for name,data in sorted(found.items())}


class AllocationGate(native.Gate):
    def execute(self, prior=None):
        require(platform.system()=='Linux' and self.data['phase']=='allocation', 'allocation capture requires actual Linux and allocation phase')
        require(not self.work.exists() and not self.evidence.exists(), 'fresh work/evidence directories required')
        self.sources.mkdir(parents=True);self.results.mkdir();(self.evidence/'logs').mkdir(parents=True);(self.evidence/'provenance').mkdir()
        repo=os.environ.get('GITHUB_REPOSITORY');full_sha(os.environ.get('GITHUB_SHA'))
        run_id=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','')
        require(repo=='NRG-Wardog/LiveContainer' and run_id.isdigit() and int(run_id)>0 and attempt.isdigit() and int(attempt)>0, 'actual GitHub validation run identity required')
        require(git(self.host,'rev-parse','HEAD').decode().strip()==os.environ['GITHUB_SHA'], 'validation host checkout differs from runner SHA')
        require(os.environ.get('GITHUB_REF')=='refs/heads/validation/p0-cxx-allocation-linux', 'isolated allocation validation branch required')
        self.state.update(platform='linux',source_commit=AK_COMMIT,source_tree=AK_TREE,source_sha256=ALLOCATION_SOURCES,
            historical_basis=self.data['historical_basis'],approved_inputs_sha256=self.approved,owners=self.data['owners'],
            run={'url':'https://github.com/'+repo+'/actions/runs/'+run_id,'attempt':int(attempt),'host_commit':os.environ['GITHUB_SHA'],'host_tree':git(self.host,'rev-parse','HEAD^{tree}').decode().strip()})
        try:
            self.stage='toolchain';self.run('compiler-version',['c++','--version']);self.run('python-version',[sys.executable,'--version'])
            # Network denial is exercised before any host test. GitHub's hosted
            # Ubuntu runner provides passwordless sudo and Linux unshare.
            sandbox=['sudo','-n','unshare','--net','--']
            self.run('network-sandbox',[*sandbox,sys.executable,'-c','import socket; s=socket.socket(); s.settimeout(1);\ntry: s.connect(("1.1.1.1",443))\nexcept OSError: pass\nelse: raise SystemExit("network sandbox did not deny")'])
            self.acquire()
            self.stage='headers-only'
            archive=self.results/'Unicorn.xcframework.zip'
            self.run('unicorn-header-download',['curl','--fail','--location','--proto','=https','--proto-redir','=https','--output',archive,FORK_URL],timeout=300)
            headers=self.results/'unicorn-headers';header_hashes=extract_headers(archive,headers)
            dump(self.evidence/'provenance/unicorn-headers.json',{'url':FORK_URL,'archive_sha256':FORK_SHA,'headers_sha256':header_hashes,'engine_linked':False,'engine_executed':False})
            self.stage='host-only-cxx-allocation';output=self.evidence/'allocation-units'
            self.run('allocation-units',[*sandbox,sys.executable,'-B',self.roots['AnisetteKit']/'.ci/native-tests/test_cxx_allocation.py','--unicorn-include',headers,'--output',output],timeout=900)
            raw=ordinary(output,'result.json').read_bytes();receipt=verify_allocation_receipt(parse(raw));verify_raw_commands(output,receipt,self.roots['AnisetteKit'],headers)
            (self.evidence/'provenance/allocation-helper.json').write_bytes(raw)
            require(header_hashes=={p.name:sha(p.read_bytes()) for p in (headers/'unicorn').iterdir()}, 'engine headers changed during host test')
            dump(self.evidence/'provenance/source-after.json',self.source_proof())
            self.stage='captured';self.state['status']='CAPTURED_FOR_REVIEW'
        except Exception as error:
            self.state['primary_error']=type(error).__name__+': '+str(error)
            raise
        finally:
            settled=all(row.get('quiescent') is True and row.get('pipesJoined') is True and row.get('leaderReaped') is True and not row.get('errors') for row in self.command_quiescence)
            self.state['writers_quiescent']=settled;self.state['last_stage']=self.stage
            if not settled:self.state['status']='FAILED_UNSETTLED_WRITERS'
            self.state['retention_errors']=[] if settled else ['evidence index withheld: unsettled or unknown command writers']
            dump(self.evidence/'provenance/result.json',self.state)
            dump(self.evidence/'provenance/owned-command-groups.json',self.command_quiescence)
            (self.evidence/'provenance/approved-inputs.json').write_bytes(self.input_bytes)
            if settled:
                index={str(p.relative_to(self.evidence)):sha(p.read_bytes()) for p in sorted(self.evidence.rglob('*')) if p.is_file() and p.name!='evidence-index.json'}
                dump(self.evidence/'evidence-index.json',index)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs',type=Path,required=True);p.add_argument('--approved-inputs-sha256',required=True)
    p.add_argument('--host-root',type=Path,default=native.HERE.parents[1]);p.add_argument('--work',type=Path);p.add_argument('--evidence',type=Path)
    p.add_argument('--execute',action='store_true');p.add_argument('--check-transport',action='store_true')
    a=p.parse_args()
    try:
        raw=a.inputs.read_bytes();data=native.validate_inputs(raw,a.approved_inputs_sha256,a.host_root)
        require(data['phase']=='allocation','allocation inputs required')
        if a.check_transport:
            require(not a.execute,'transport check forbids execution');print(json.dumps(native.verify_transport(a.evidence)));return
        if not a.execute:
            print(json.dumps({'status':'SEALED_INPUTS_VALID','native_execution':False,'production_ready':False,'phase':'allocation'}));return
        require(a.work is not None and a.evidence is not None,'fresh --work and --evidence required')
        gate=AllocationGate(data,a.host_root.resolve(),a.work.resolve(),a.evidence.resolve(),a.approved_inputs_sha256);gate.input_bytes=raw;gate.execute()
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as error:p.exit(2,'BLOCKED: '+str(error)+'\n')


if __name__=='__main__':main()
