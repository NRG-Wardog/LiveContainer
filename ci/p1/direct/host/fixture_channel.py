"""Descriptor-bound adapter for the unchanged fixture request/response format.

Caller must first prove this fresh scenario directory belongs to the exact
session-bound app container. Responses lack their own nonce in the maintained
fixture; this adapter does not invent one or authenticate ownership by a path.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import time


def require(ok, message):
    if not ok:raise ValueError(message)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def parse(raw):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'duplicate JSON key');result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


class Directory:
    def __init__(self, path):
        self.path=Path(path)
        require(self.path.is_absolute() and self.path.resolve()==self.path,'noncanonical channel path')
        self.fd=os.open(self.path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK)
        info=os.fstat(self.fd)
        self.identity=(info.st_dev,info.st_ino)
        self.closed=False
    def check(self):
        require(not self.closed,'closed channel')
        info=os.stat(self.path,follow_symlinks=False)
        require(stat.S_ISDIR(info.st_mode) and (info.st_dev,info.st_ino)==self.identity,'channel directory replaced')
    def read(self,name,limit=65536):
        require(type(name) is str and '/' not in name and name not in ('','.','..'),'invalid channel leaf')
        self.check()
        try:fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=self.fd)
        except FileNotFoundError:return None
        try:
            before=os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<before.st_size<=limit,'invalid bounded regular file')
            raw=b''
            while len(raw)<=limit:
                part=os.read(fd,min(65536,limit+1-len(raw)))
                if not part:break
                raw+=part
            after=os.fstat(fd)
            require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                    (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'file changed during read')
            require(len(raw)==before.st_size and len(raw)<=limit,'file read bound')
            self.check()
            return raw
        finally:os.close(fd)
    def publish(self,name,raw):
        require(name=='request.json' and type(raw) is bytes and 0<len(raw)<=8192,'request publication shape')
        self.check();temporary='request.direct-tmp'
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=self.fd)
        try:
            view=memoryview(raw)
            while view:
                written=os.write(fd,view);require(written>0,'short request write');view=view[written:]
            os.fsync(fd)
        finally:os.close(fd)
        # A dangling symlink is detected by read(), never followed by rename.
        self.read(name,8192)
        self.check()
        os.rename(temporary,name,src_dir_fd=self.fd,dst_dir_fd=self.fd)
        os.fsync(self.fd)
        require(self.read(name,8192)==raw,'published request mismatch')
    def close(self):
        if not self.closed:
            self.closed=True;os.close(self.fd)


class FixtureChannel:
    def __init__(self,directory,*,checkpoint,remaining,retain,monotonic_ns=time.monotonic_ns,sleep=time.sleep):
        self.directory=directory;self.checkpoint=checkpoint;self.remaining=remaining
        self.retain=retain;self.now=monotonic_ns;self.sleep=sleep;self.sequence=0;self.failed=False
        require(directory.read('request.json') is None and directory.read('response.json') is None,'stale fixture channel')
        self.previous_response=None
    def exchange(self,sequence,kind):
        require(not self.failed and type(sequence) is int and sequence==self.sequence+1 and kind in ('clock','ready','mid','third','post','finish'),'request sequence/kind')
        self.sequence=sequence;request=canonical({'id':sequence,'kind':kind})
        before=self.now();after=None;response=None;raw=None;error=None
        try:
            timeout=self.remaining(5)
            require(type(timeout) in (int,float) and 0<timeout<=5,'bounded response reserve')
            deadline=min(before+5_000_000_000,before+int(timeout*1_000_000_000))
            self.checkpoint();self.directory.publish('request.json',request)
            while self.now()<deadline:
                self.checkpoint()
                require(self.directory.read('journal-error.txt') is None,'fixture journal failed')
                raw=self.directory.read('response.json',8192)
                if raw is not None:
                    value=parse(raw)
                    require(type(value) is dict and type(value.get('id')) is int,'response identity absent')
                    if value['id']==sequence:
                        response=value;break
                    require(value['id']==sequence-1 and raw==self.previous_response,'unexpected stale/future response')
                self.sleep(.001)
            after=self.now()
            require(response is not None and after<=deadline,'fixture response deadline')
            self.previous_response=raw
            return {'id':sequence,'kind':kind,'hostBeforeNs':before,'hostAfterNs':after,'response':response}
        except BaseException as exc:
            self.failed=True;error=type(exc).__name__;raise
        finally:
            if after is None:after=self.now()
            try:
                self.retain({'id':sequence,'kind':kind,'hostBeforeNs':before,'hostAfterNs':after,
                             'requestBytes':request,'responseBytes':raw,'response':response,'errorType':error,
                             'directoryIdentity':self.directory.identity,'admissionEligible':False})
            except BaseException:
                self.failed=True
                raise
