"""One optional bounded Apple sample experiment. Never an admission predicate.

PID attachment is best-effort, not atomic. Only a report bracketed by liveness
of the SAME retained OwnedProcess, with matching image/parent/PID, is retained.
No reaping changes, privilege requests, process-wide tracing or retries.
"""
from hashlib import sha256
from pathlib import Path
import errno,os,re,select,stat,struct,sys,threading,time,uuid
from fixture_channel import canonical,require

SAMPLE='/usr/bin/sample'
MAX_OUTPUT=512*1024
SAMPLE_SECONDS=5
INTERVAL_MS=10
COMMAND_SECONDS=8


def image_identity(path):
    """Bounded Mach-O header/UUID proof plus exact existing file bytes."""
    path=Path(path)
    require(path.is_absolute() and path.resolve()==path and not path.is_symlink(),'canonical image')
    with path.open('rb') as f:
        before=os.fstat(f.fileno())
        require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=128*1024*1024,'bounded ordinary image')
        head=f.read(128*1024*1024+1);require(len(head)==before.st_size,'image size changed')
        digest=sha256(head)
        after=os.fstat(f.fileno())
    require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),'image changed while reading')
    def thin(offset):
        require(offset+32<=len(head),'Mach-O header unavailable')
        magic,cpu,subtype,filetype,ncmds,size,flags,reserved=struct.unpack_from('<8I',head,offset)
        require(magic==0xfeedfacf and 0<ncmds<=512 and size<=1024*1024 and offset+32+size<=len(head),'unsupported Mach-O')
        cursor=offset+32;end=cursor+size;found=[]
        for _ in range(ncmds):
            require(cursor+8<=end,'invalid Mach-O command')
            kind,length=struct.unpack_from('<II',head,cursor)
            require(length>=8 and cursor+length<=end,'invalid Mach-O length')
            if kind==0x1b:
                require(length==24,'invalid LC_UUID');found.append(str(uuid.UUID(bytes=head[cursor+8:cursor+24])).upper())
            cursor+=length
        require(cursor==end and len(found)==1,'one LC_UUID required');return found[0]
    require(len(head)>=8,'image header absent')
    magic,count=struct.unpack_from('>II',head)
    if magic in (0xcafebabe,0xcafebabf):
        require(0<count<=8,'bounded fat slices');width=20 if magic==0xcafebabe else 32;uuids=[]
        for i in range(count):
            start=8+i*width;require(start+width<=len(head),'fat header absent')
            offset=struct.unpack_from('>I' if width==20 else '>Q',head,start+8)[0]
            # Reject far-away slices rather than unbounded/random image reads.
            uuids.append(thin(offset))
    else:uuids=[thin(0)]
    return {'path':str(path),'sha256':digest.hexdigest(),'uuids':sorted(set(uuids))}


def validate_report(raw,*,pid,parent,image):
    require(type(raw) is bytes and 0<len(raw)<=MAX_OUTPUT,'bounded sample report')
    text=raw.decode('utf-8',errors='strict')
    def field(name):
        values=re.findall(r'^'+re.escape(name)+r':\s*(.*?)\s*$',text,re.M)
        require(len(values)==1,'missing/duplicate sample identity');return values[0]
    require(re.fullmatch(r'.+ \['+str(pid)+r'\]',field('Process')) is not None,'sample PID mismatch')
    require(field('Path')==image['path'],'sample image path mismatch')
    require(re.fullmatch(r'.+ \['+str(parent)+r'\]',field('Parent Process')) is not None,'sample parent mismatch')
    require('Call graph:' in text and 'Binary Images:' in text,'unsupported sample report format')
    images=text.split('Binary Images:',1)[1]
    matches=re.findall(r'<([0-9A-Fa-f-]{36})>\s+'+re.escape(image['path'])+r'\s*$',images,re.M)
    require(len(matches)==1 and matches[0].upper() in image['uuids'],'sample image UUID mismatch')
    return {'pid':pid,'parentPID':parent,'image':image,'reportSHA256':sha256(raw).hexdigest(),'bytes':len(raw)}


def outcome(code,raw):
    """Only classify diagnostic failure; never expose rejected raw report."""
    lower=raw.lower()
    if any(term in lower for term in (b'operation not permitted',b'permission denied',b'not authorized',b'access denied')):return 'denied'
    if any(term in lower for term in (b'usage:',b'unknown option',b'unrecognized option',b'illegal option',b'invalid option')):return 'unsupported'
    if code!=0:return 'failed'
    return 'inconclusive'


class Experiment:
    def __init__(self,scope,process_scope,output,session,helper_image,helper_path):
        self.scope=scope;self.ps=process_scope;self.output=Path(output);self.session=session
        self.scope_session=scope.session;self.expected_image=helper_image;self.helper_path=str(helper_path)
        self.thread=None;self.cancel=threading.Event();self.done=threading.Event()
        self.raw=None;self.error=None;self.started=False;self.counter=0;self.saved=False
        self.row={'schema':'p1-owned-helper-sample-v1','session':session,'scopeSession':scope.session,
                  'status':'not-started','admissionEligible':False,'atomicAttachment':False,
                  'durationSeconds':SAMPLE_SECONDS,'intervalMilliseconds':INTERVAL_MS,'maxOutputBytes':MAX_OUTPUT,
                  'schedulerStateEstablished':False,'pressureEstablished':False,'samplingCanPerturbTiming':True,
                  'resourceObservations':'omitted-not-capability-verified'}
    def _launch(self,argv,write_fd,deadline):
        self.counter+=1
        launch=self.ps.LaunchReceipt(self.counter,deadline,max(0,deadline-time.monotonic()))
        return self.scope.spawn(argv,write_fd,write_fd,launch=launch)
    def _live(self,process,argv):
        require(type(process) is self.ps.OwnedProcess and self.scope.session==self.scope_session and
                self.scope.processes.get(process.pid) is process,'original owned process required')
        rows=[r for r in self.scope.rows if r['pid']==process.pid]
        require(len(rows)==1 and rows[0]['argv']==list(argv) and rows[0]['settled'] is False,'owned argv/registry mismatch')
        with process.lock:
            require(process.poll() is None,'original child exited')
            launch=process.launch
            require(type(launch) is self.ps.LaunchReceipt and launch.row['session']==self.scope_session and
                    launch.row['pid']==process.pid and launch.row['registration']['durable'] is True,'owned launch mismatch')
            launch.observe()
            require(launch.row['eof'] and launch.row['exec_failure'] is None and launch.row['pre_exec'] is not None and
                    (launch.row['state'],launch.row['reason']) in [('unknown','pending'),('pre-exec-observed',None)],
                    'target exec unresolved or rejected')
    def _run(self,argv,deadline):
        if self.cancel.is_set():return {'status':'cancelled','code':None,'raw':b'','samplerPID':None}
        read_fd,write_fd=os.pipe();os.set_blocking(read_fd,False)
        process=None;raw=bytearray();status=None;code=None
        try:
            process=self._launch(argv,write_fd,deadline)
            os.close(write_fd);write_fd=None
            eof=False
            while True:
                if self.cancel.is_set():status='cancelled';break
                if time.monotonic()>=deadline:status='timeout';break
                with process.lock:
                    process.launch.observe();code=process.poll()
                if eof and code is not None:break
                ready,_,_=select.select([] if eof else [read_fd],[],[],min(.05,max(0,deadline-time.monotonic())))
                if ready:
                    block=os.read(read_fd,min(65536,MAX_OUTPUT+1-len(raw)))
                    if not block:eof=True
                    else:raw.extend(block)
                    if len(raw)>MAX_OUTPUT:status='output-limit';break
        finally:
            if write_fd is not None:os.close(write_fd)
            os.close(read_fd)
            if process is not None:
                # Same existing registered lifecycle/cleanup, not a raw PID kill.
                try:self.scope.settle(process)
                finally:
                    with process.lock:process.launch.finish()
                if status is None and code==0:process.launch.require()
        return {'status':status,'code':code,'raw':bytes(raw),'samplerPID':None if process is None else process.pid}
    def preflight(self):
        require(self.row['status']=='not-started','single capability preflight')
        if sys.platform!='darwin':self.row['status']='unsupported';self.row['reason']='non-darwin';return
        if (os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('GITHUB_REPOSITORY')!='NRG-Wardog/LiveContainer' or
                os.environ.get('RUNNER_OS')!='macOS' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted' or not os.environ.get('GITHUB_RUN_ID','').isdigit() or
                os.getuid()!=os.geteuid() or os.geteuid()==0):
            self.row.update(status='unsupported',reason='isolated-ci-account-required');return
        if not Path(SAMPLE).is_file() or not os.access(SAMPLE,os.X_OK):
            self.row['status']='unavailable';self.row['reason']='installed-sample-absent';return
        child=None;fd=None
        try:
            image=image_identity(Path(sys.executable).resolve())
            argv=[sys.executable,'-B','-c','import time; time.sleep(30)']
            deadline=min(time.monotonic()+8,self.scope.deadline)
            fd=os.open(os.devnull,os.O_WRONLY)
            child=self._launch(argv,fd,deadline)
            # Preflight child has no competing waiter and is never reaped until
            # the sampling command has settled. Readiness is bounded, not guessed.
            while True:
                try:self._live(child,argv);break
                except ValueError:
                    if child.poll() is not None or time.monotonic()>=deadline:raise
                    time.sleep(.01)
            result=self._run([SAMPLE,str(child.pid),'1',str(INTERVAL_MS),'-file','/dev/stdout'],min(deadline,time.monotonic()+4))
            self._live(child,argv)
            if result['status'] is not None:self.row.update(status=result['status'],reason='capability-command');return
            if result['code']!=0 or outcome(result['code'],result['raw'])=='denied':self.row.update(status=outcome(result['code'],result['raw']),reason='capability-command');return
            validate_report(result['raw'],pid=child.pid,parent=os.getpid(),image=image)
            self.row.update(status='available',capability='owned-same-user-child-report-validated')
        except (ValueError,OSError) as error:
            self.row.update(status='denied' if isinstance(error,OSError) and error.errno in (errno.EPERM,errno.EACCES) else 'unsupported',reason='capability-or-report-validation',errorType=type(error).__name__)
        finally:
            if fd is not None:os.close(fd)
            if child is not None:
                try:self.scope.settle(child)
                finally:
                    with child.lock:child.launch.finish()
            # Caller retains only capability metadata, never this synthetic report.
    def start(self,helper,*,deadline):
        require(not self.started,'one diagnostic attempt');self.started=True
        if self.row['status']!='available':return
        self.row['trigger']='before-publish-roi';self.row['requestedHostNs']=time.monotonic_ns()
        def run():
            try:
                process=helper.process;argv=list(helper.argv)
                require(process is not None,'helper launch unresolved')
                require(helper.scope is self.scope and len(argv)==7 and argv[0]==self.helper_path and argv[4]==self.session,'exact helper session/command required')
                self._live(process,argv)
                image=image_identity(Path(argv[0]))
                require(image['sha256']==self.expected_image,'compiled helper bytes changed')
                self.row.update(pid=process.pid,preLiveHostNs=time.monotonic_ns(),status='running')
                result=self._run([SAMPLE,str(process.pid),str(SAMPLE_SECONDS),str(INTERVAL_MS),'-file','/dev/stdout'],
                                 min(deadline,self.scope.deadline,time.monotonic()+COMMAND_SECONDS))
                # Validate SAME original Popen wrapper, never rediscover by PID.
                self._live(process,argv)
                self.row['postLiveHostNs']=time.monotonic_ns()
                require(image_identity(Path(argv[0]))==image,'compiled helper image changed during sample')
                if result['status'] is not None:self.row.update(status=result['status']);return
                if result['code']!=0 or outcome(result['code'],result['raw'])=='denied':self.row.update(status=outcome(result['code'],result['raw']));return
                identity=validate_report(result['raw'],pid=process.pid,parent=os.getpid(),image=image)
                self.raw=result['raw'];self.row.update(status='validated-statistical-report',identity=identity)
            except (ValueError,OSError) as error:
                self.row.update(status='denied' if isinstance(error,OSError) and error.errno in (errno.EPERM,errno.EACCES) else 'inconclusive',reason='identity-or-capability-validation',errorType=type(error).__name__)
            except BaseException as error:
                self.error=error;self.row.update(status='failed',reason='diagnostic-worker',errorType=type(error).__name__)
            finally:
                self.row['finishedHostNs']=time.monotonic_ns();self.done.set()
        self.thread=threading.Thread(target=run,name='p1-bounded-helper-sample',daemon=True);self.thread.start()
    def _save(self,name,raw):
        with (self.output/name).open('xb') as f:f.write(raw)
    def finish(self,timeout):
        if self.saved:return dict(self.row)
        if self.thread is not None:
            self.cancel.set();self.thread.join(timeout=max(0,timeout))
            require(not self.thread.is_alive(),'diagnostic writer unsettled')
        # Called during existing cleanup, never from capture callback/writer.
        if self.raw is not None:self._save('helper-sample.txt',self.raw)
        self._save('helper-sample.json',canonical(self.row));self.saved=True
        if self.error is not None:raise self.error
        return dict(self.row)
