"""Fresh nonce-bound app/runner channels; clock domains remain separate."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import time


def require(ok, message):
    if not ok: raise ValueError(message)


def parse(path):
    require(path.is_file() and not path.is_symlink(), 'missing/linked protocol file')
    def unique(pairs):
        result={}
        for k,v in pairs:
            require(k not in result, 'duplicate protocol JSON key');result[k]=v
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path, value):
    require(not path.is_symlink() and not path.with_suffix('.tmp').exists(),'stale/linked request path')
    tmp=path.with_suffix('.tmp');tmp.write_bytes(canonical(value));tmp.replace(path)


class Channel:
    def __init__(self, root, session, role, output, remaining=None):
        require(re.fullmatch('[a-f0-9]{32}',session) and role in ['app','runner'],'invalid session/role')
        require(root.is_dir() and not root.is_symlink(),'missing/linked channel')
        self.root,self.session,self.role,self.output=root.resolve(),session,role,output
        require(not any(self.root.glob('request*.json')) and not any(self.root.glob('response*.json')),'stale channel request/response')
        self.sequence=0;self.rows=[];self.remaining=remaining
    def request(self, kind, timeout=20, **extra):
        if self.remaining is not None:timeout=self.remaining(timeout)
        self.sequence+=1
        request=dict(session=self.session,id=self.sequence,kind=kind,**extra)
        if self.role=='runner':request['schema']='p1-capability-request-v1'
        before=time.monotonic();atomic(self.root/'request.json',request);response=None
        try:
            while time.monotonic()-before < timeout:
                for name in ['error.json','journal-error.txt']:
                    require(not (self.root/name).exists(),self.role+' channel reported failure')
                if (self.root/'response.json').exists():
                    value=parse(self.root/'response.json')
                    require(value.get('session')==self.session,'response nonce differs')
                    if type(value.get('id')) is int and value['id']==self.sequence:response=value;break
                    require(type(value.get('id')) is int and value['id']==self.sequence-1,'stale/future response ID')
                time.sleep(.002)
            after=time.monotonic()
            require(response is not None,self.role+' request timed out: '+kind)
            width=4 if self.role=='runner' else 3
            rp=self.root/f'request-{self.sequence:0{width}d}.json';sp=self.root/f'response-{self.sequence:0{width}d}.json'
            require(parse(rp)==request and parse(sp)==response,'acknowledgement preceded durable request/response')
            return response
        finally:
            row={'request':request,'hostBefore':before,'hostAfter':time.monotonic(),'response':response}
            self.rows.append(row)
            self.output.write_text(json.dumps({'schema':'p1-capability-host-channel-v1','session':self.session,'role':self.role,'rows':self.rows,'admissionEligible':False},indent=2,allow_nan=False)+'\n')


def expected_runner_requests(session):
    rows=[]
    for phase in ['pre','mid','post']:
        for _ in range(8):rows.append(dict(kind='clock',phase=phase))
        for ordinal in range(1,4):rows.append(dict(kind='capture',phase=phase,ordinal=ordinal))
    rows.extend([dict(kind='after'),dict(kind='complete')])
    return [dict(schema='p1-capability-request-v1',session=session,id=i,**r) for i,r in enumerate(rows,1)]


def expected_app_requests(session):
    rows=[]
    for phase in ['pre','mid','post']:
        if phase=='mid':rows.append(dict(kind='capability-mid'))
        if phase=='post':rows.append(dict(kind='capability-post'))
        for _ in range(8):rows.append(dict(kind='clock',phase=phase))
        rows.append(dict(kind={'pre':'ready','mid':'third','post':'finish'}[phase]))
    return [dict(session=session,id=i,**r) for i,r in enumerate(rows,1)]
