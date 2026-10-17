#!/usr/bin/env python3
"""Recover one immutable evidence ZIP as bounded, byte-identical chunks only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY='NRG-Wardog/LiveContainer'
BRANCH='validation/p1-native-basis'
RUN=39041266465
ATTEMPT=1
COMMIT='a6ea69fcd6bea9a3a9079b9429d81214ae579001'
ARTIFACT=12105047622
SIZE=1275112853
SHA256='33a21553949a8ef649ba6c32de0d969844de9357042c44712962b8e8ebb59fb9'
NAME=f'p1-video-diagnostic-{COMMIT}-{RUN}-{ATTEMPT}'
API=f'https://api.github.com/repos/{REPOSITORY}'
CHUNK_SIZE=256*1024*1024
BLOCK_SIZE=1024*1024


class TransportError(ValueError):pass


def require(ok,message):
    if not ok:raise TransportError(message)


def unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'duplicate JSON key');result[key]=value
    return result


def write(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(BLOCK_SIZE),b''):result.update(block)
    return result.hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def opener():return urllib.request.build_opener(NoRedirect)


def api_request(path,token):
    require(path in [f'/actions/artifacts/{ARTIFACT}',f'/actions/artifacts/{ARTIFACT}/zip',f'/actions/runs/{RUN}'],'unreviewed API resource')
    require(isinstance(token,str) and token and '\n' not in token and '\r' not in token,'missing/invalid ephemeral Actions token')
    return urllib.request.Request(API+path,headers={'Accept':'application/vnd.github+json',
        'Authorization':'Bearer '+token,'X-GitHub-Api-Version':'2022-11-28','User-Agent':'p1-evidence-transport'})


def api_json(path,token):
    with opener().open(api_request(path,token),timeout=60) as response:
        require(response.status==200,'metadata request failed')
        data=response.read(2*1024*1024+1);require(len(data)<=2*1024*1024,'unbounded metadata')
    return json.loads(data,object_pairs_hook=unique)


def verify_metadata(artifact,run):
    require(type(artifact.get('id')) is int and artifact['id']==ARTIFACT and artifact.get('name')==NAME,'wrong artifact identity')
    require(type(artifact.get('size_in_bytes')) is int and artifact['size_in_bytes']==SIZE and artifact.get('digest')=='sha256:'+SHA256 and artifact.get('expired') is False,'artifact bytes/expiry differ')
    nested=artifact.get('workflow_run',{})
    require(type(nested.get('id')) is int and nested['id']==RUN and nested.get('head_sha')==COMMIT and nested.get('head_branch')==BRANCH,'wrong artifact source run')
    require(type(run.get('id')) is int and run['id']==RUN and type(run.get('run_attempt')) is int and run['run_attempt']==ATTEMPT,'wrong original run/attempt')
    require(run.get('head_sha')==COMMIT and run.get('head_branch')==BRANCH and run.get('repository',{}).get('full_name')==REPOSITORY,'wrong source repository/commit')
    require(run.get('status')=='completed' and run.get('conclusion')=='failure','original run outcome differs')


def download_location(token):
    try:
        with opener().open(api_request(f'/actions/artifacts/{ARTIFACT}/zip',token),timeout=60):
            raise TransportError('missing artifact redirect')
    except urllib.error.HTTPError as error:
        try:
            require(error.code==302,'artifact redirect request failed')
            location=error.headers.get('Location','')
        finally:error.close()
    parsed=urllib.parse.urlsplit(location)
    require(parsed.scheme=='https' and parsed.hostname and parsed.username is None and parsed.password is None and not parsed.fragment and parsed.port in [None,443],'invalid artifact redirect')
    require(parsed.hostname.endswith(('.blob.core.windows.net','.githubusercontent.com')),'unreviewed artifact storage host')
    return location


def download(token,target):
    location=download_location(token)
    # A completely new request/opener, with no API headers or credentials. It
    # rejects any further redirect rather than forwarding Authorization.
    request=urllib.request.Request(location,headers={'User-Agent':'p1-evidence-transport'})
    count=0;h=hashlib.sha256()
    with opener().open(request,timeout=120) as response,target.open('xb') as stream:
        require(response.status==200,'artifact storage request failed')
        length=response.headers.get('Content-Length')
        if length is not None:require(length.isdecimal() and int(length)==SIZE,'storage byte count differs')
        while True:
            block=response.read(BLOCK_SIZE)
            if not block:break
            count+=len(block);require(count<=SIZE,'oversized archive')
            stream.write(block);h.update(block)
    require(count==SIZE and h.hexdigest()==SHA256,'original ZIP identity differs')


def split_verified(source,output,expected_size=SIZE,expected_sha256=SHA256,chunk_size=CHUNK_SIZE):
    require(source.is_file() and not source.is_symlink(),'missing/linked source ZIP')
    require(type(chunk_size) is int and 0<chunk_size<=CHUNK_SIZE,'unsafe chunk size')
    require(source.stat().st_size==expected_size and digest(source)==expected_sha256,'unverified original ZIP')
    require(not output.exists(),'fresh chunk output required');output.mkdir(parents=True)
    chunks=[];offset=0;whole=hashlib.sha256()
    with source.open('rb') as incoming:
        while offset<expected_size:
            number=len(chunks);name=f'part-{number:03d}.bin';path=output/name;size=min(chunk_size,expected_size-offset);remaining=size;h=hashlib.sha256()
            with path.open('xb') as stream:
                while remaining:
                    data=incoming.read(min(BLOCK_SIZE,remaining));require(data,'short original ZIP')
                    stream.write(data);h.update(data);whole.update(data);remaining-=len(data)
            chunks.append({'ordinal':number,'path':name,'offset':offset,'size':size,'sha256':h.hexdigest()});offset+=size
        require(incoming.read(1)==b'' and whole.hexdigest()==expected_sha256,'source changed while splitting')
    require(offset==expected_size,'incomplete chunk inventory')
    verify_chunks(output,chunks,expected_size,expected_sha256,chunk_size)
    return chunks


def verify_chunks(root,chunks,expected_size,expected_sha256,chunk_size):
    require(len(chunks)==(expected_size+chunk_size-1)//chunk_size,'chunk count differs')
    offset=0;whole=hashlib.sha256()
    for number,row in enumerate(chunks):
        require(type(row.get('ordinal')) is int and row['ordinal']==number and row.get('path')==f'part-{number:03d}.bin','chunk order/path differs')
        size=min(chunk_size,expected_size-offset)
        require(type(row.get('offset')) is int and row['offset']==offset and type(row.get('size')) is int and row['size']==size,'chunk boundaries differ')
        path=root/row['path'];require(path.is_file() and not path.is_symlink() and path.stat().st_size==size,'chunk missing/linked/wrong size')
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(BLOCK_SIZE),b''):h.update(block);whole.update(block)
        require(h.hexdigest()==row.get('sha256'),'chunk digest differs');offset+=size
    require(offset==expected_size and whole.hexdigest()==expected_sha256,'reconstructed ZIP identity differs')


def execute(work,output,token):
    require(os.environ.get('GITHUB_REPOSITORY')==REPOSITORY and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH,'dedicated transport lane required')
    require(not work.exists() and not output.exists(),'fresh transport paths required');work.mkdir(parents=True)
    artifact=api_json(f'/actions/artifacts/{ARTIFACT}',token);run=api_json(f'/actions/runs/{RUN}',token);verify_metadata(artifact,run)
    source=work/'original.zip';download(token,source)
    chunks=split_verified(source,output)
    # Metadata is only the authenticated source identity; no signed URL, API
    # request, Authorization header, environment dump, or token is retained.
    manifest={'schema':'p1-evidence-byte-transport-v1','source':{'repository':REPOSITORY,'run_id':RUN,'run_attempt':ATTEMPT,'commit':COMMIT,'artifact_id':ARTIFACT,'artifact_name':NAME,'size':SIZE,'sha256':SHA256},
        'chunks':chunks,'reconstruction':'Concatenate part-NNN.bin in ordinal order; verify exact original size and SHA256 before opening ZIP.',
        'transport_run':{key:os.environ.get(key) for key in ['GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT']},
        'zip_rewritten':False,'build_executed':False,'ui_executed':False,'admission_eligible':False}
    write(output/'manifest.json',manifest)
    return manifest


def safe_failure(error):
    return str(error) if isinstance(error,TransportError) else type(error).__name__


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--work',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    try:
        result=execute(a.work,a.output,os.environ.pop('GH_TOKEN',''))
        print(json.dumps({'source_sha256':result['source']['sha256'],'chunks':len(result['chunks']),'transport_complete':True}))
    except Exception as error:
        # Exception strings may contain signed storage URLs. Never print them.
        print('Evidence transport failed: '+safe_failure(error),file=sys.stderr);sys.exit(1)
