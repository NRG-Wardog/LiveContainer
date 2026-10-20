"""Capability-only discriminators. No rejected report bytes or stack analysis."""
import errno
import os
from pathlib import Path
import re
import sys
import time
import helper_sample as h
import native_probe

BRANCH='refs/heads/validation/p1-sample-capability'

class Rejection(ValueError):
    def __init__(self,stage,code):
        self.stage=stage;self.code=code
        super().__init__(code)


def check(ok,stage,code,checks):
    checks[code]=bool(ok)
    if not ok:raise Rejection(stage,code)


def validate(raw,*,pid,parent,image,checks):
    check(type(raw) is bytes and 0<len(raw)<=h.MAX_OUTPUT,'report-bounds','bounded-report',checks)
    try:text=raw.decode('utf-8',errors='strict')
    except UnicodeError:
        checks['utf8']=False
        raise Rejection('report-format','utf8') from None
    checks['utf8']=True
    def field(name,code):
        values=re.findall(r'^'+re.escape(name)+r':\s*(.*?)\s*$',text,re.M)
        check(len(values)>0,'report-header',code+'-present',checks)
        check(len(values)==1,'report-header',code+'-unique',checks)
        return values[0]
    check(re.fullmatch(r'.+ \['+str(pid)+r'\]',field('Process','process')) is not None,'report-pid','pid-matches',checks)
    check(field('Path','path')==image['path'],'report-path','path-matches',checks)
    check(re.fullmatch(r'.+ \['+str(parent)+r'\]',field('Parent Process','parent')) is not None,'report-parent','parent-matches',checks)
    check('Call graph:' in text,'report-format','call-graph-present',checks)
    check('Binary Images:' in text,'report-format','binary-images-present',checks)
    images=text.split('Binary Images:',1)[1]
    matches=re.findall(r'<([0-9A-Fa-f-]{36})>\s+'+re.escape(image['path'])+r'\s*$',images,re.M)
    check(len(matches)==1,'report-uuid','image-uuid-record-unique',checks)
    check(matches[0].upper() in image['uuids'],'report-uuid','uuid-matches',checks)
    # Original parser is the final authority; no widening of accepted reports.
    return h.validate_report(raw,pid=pid,parent=parent,image=image)


class Diagnostic(h.Experiment):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.stage='not-started';self.checks={}
        self.row.update(schema='p1-sample-capability-diagnostic-v1',durationSeconds=1,checks=self.checks,
                        rawReportRetained=False,stackInterpretation=False)

    def _live(self,process,argv):
        prefix=self.stage
        def need(ok,code):check(ok,prefix,code,self.checks)
        need(type(process) is self.ps.OwnedProcess and self.scope.session==self.scope_session and
             self.scope.processes.get(process.pid) is process,'owned-object')
        rows=[r for r in self.scope.rows if r['pid']==process.pid]
        need(len(rows)==1 and rows[0]['argv']==list(argv) and rows[0]['settled'] is False,'owned-registry')
        with process.lock:
            need(process.poll() is None,'child-live')
            launch=process.launch
            need(type(launch) is self.ps.LaunchReceipt and launch.row['session']==self.scope_session and
                 launch.row['pid']==process.pid and launch.row['registration']['durable'] is True,'launch-binding')
            launch.observe()
            need(launch.row['eof'],'launch-eof')
            need(launch.row['exec_failure'] is None,'launch-no-exec-failure')
            need(launch.row['pre_exec'] is not None,'launch-pre-exec')
            need((launch.row['state'],launch.row['reason']) in [('unknown','pending'),('pre-exec-observed',None)],'launch-state')

    def preflight(self):
        h.require(self.row['status']=='not-started','single capability preflight')
        if sys.platform!='darwin':
            self.row.update(status='unsupported',stage='environment',code='non-darwin');return
        if (os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('GITHUB_REPOSITORY')!='NRG-Wardog/LiveContainer' or
            os.environ.get('RUNNER_OS')!='macOS' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted' or
            not os.environ.get('GITHUB_RUN_ID','').isdigit() or os.environ.get('GITHUB_REF')!=BRANCH or
            os.environ.get('GITHUB_EVENT_NAME')!='push' or os.getuid()!=os.geteuid() or os.geteuid()==0):
            self.row.update(status='unsupported',stage='environment',code='isolated-exact-branch-ci-required');return
        if not Path(h.SAMPLE).is_file() or not os.access(h.SAMPLE,os.X_OK):
            self.row.update(status='unavailable',stage='tool',code='installed-sample-absent');return
        child=None;fd=None;result=None
        try:
            argv,image=native_probe.prepare(self)
            deadline=min(time.monotonic()+8,self.scope.deadline)
            self.stage='child-launch';fd=os.open(os.devnull,os.O_WRONLY)
            child=self._launch(argv,fd,deadline)
            self.row.update(expectedPID=child.pid,expectedParentPID=os.getpid())
            self.stage='pre-sample-liveness'
            while True:
                try:self._live(child,argv);break
                except ValueError:
                    if child.poll() is not None or time.monotonic()>=deadline:raise
                    time.sleep(.01)
            self.row['preSampleChecks']=dict(self.checks);self.checks.clear()
            self.stage='sampler-command-or-launch-receipt'
            result=self._run([h.SAMPLE,str(child.pid),'1',str(h.INTERVAL_MS),'-file','/dev/stdout'],min(deadline,time.monotonic()+4))
            self.row.update(samplerPID=result['samplerPID'],samplerExitCode=result['code'])
            self.stage='post-sample-liveness';self._live(child,argv)
            self.row['postSampleChecks']=dict(self.checks);self.checks.clear()
            self.stage='native-image-after-sample'
            check(h.image_identity(Path(argv[0]))==image,self.stage,'native-image-unchanged',self.checks)
            if result['status'] is not None:
                self.row.update(status=result['status'],stage='sampler-command',code='bounded-command-incomplete');return
            if result['code']!=0 or h.outcome(result['code'],result['raw'])=='denied':
                self.row.update(status=h.outcome(result['code'],result['raw']),stage='sampler-command',code='command-result');return
            self.stage='report-validation'
            validate(result['raw'],pid=child.pid,parent=os.getpid(),image=image,checks=self.checks)
            self.row.update(status='available',stage='complete',code='owned-child-report-validated')
        except native_probe.ProbeFailure as error:
            self.row.update(status=error.status,stage=error.stage,code=error.code)
        except Rejection as error:
            self.row.update(status='unsupported',stage=error.stage,code=error.code)
        except (ValueError,OSError,self.ps.LaunchReceiptError) as error:
            denied=isinstance(error,OSError) and error.errno in (errno.EPERM,errno.EACCES)
            self.row.update(status='denied' if denied else 'unsupported',stage=self.stage,code='operation-rejected',
                            errorType=type(error).__name__)
        finally:
            # Invalid (and valid synthetic) raw bytes never reach files/console.
            if result is not None:result['raw']=b''
            if fd is not None:os.close(fd)
            if child is not None:
                try:self.scope.settle(child)
                finally:
                    with child.lock:child.launch.finish()

    def start(self,*args,**kwargs):
        raise RuntimeError('capability-only diagnostic cannot sample helpers')
