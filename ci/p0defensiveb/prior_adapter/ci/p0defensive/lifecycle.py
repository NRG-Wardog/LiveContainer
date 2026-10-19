"""Owned-process lifecycle copied from reviewed p0cxx; no old source gate imported."""
import os, re, signal, subprocess, time
from pathlib import Path
from source_primitives import require
from inventory import dump
FIXED_ENV = ('DEVELOPER_DIR','PATH','HOME','TMPDIR','ASAN_OPTIONS','UBSAN_OPTIONS','PYTHONDONTWRITEBYTECODE','GIT_CONFIG_NOSYSTEM','GIT_CONFIG_GLOBAL','GIT_ALLOW_PROTOCOL','GIT_NO_REPLACE_OBJECTS','GIT_GRAFT_FILE','GIT_NO_LAZY_FETCH','GIT_TERMINAL_PROMPT','LOGIN_TRACE_PEER_ROOT','LOGIN_TRACE_PRODUCER_ROOT','INIT_DIAGNOSTICS_PEER_ROOT','INIT_DIAGNOSTICS_PRODUCER_ROOT','ADI_CONSUMPTION_PEER_ROOT','ADI_CONSUMPTION_PRODUCER_ROOT','SIDE_STORE_TEST_SOURCE','LIVE_CONTAINER_TEST_SOURCE','ANISETTE_KIT_TEST_SOURCE','MAINTAINED_LIVE_CONTAINER_TEST_SOURCE','P0LOGIN_NESTED_COMMANDS','P0LOGIN_EXPECTED_OWNER_ROOT','P0LOGIN_EXPECTED_PEER_ROOT','P0LOGIN_EXPECTED_PRODUCER_ROOT')
def command_environment(name,args,env=None):
    env=dict(os.environ if env is None else env)
    env={k:v for k,v in env.items() if k in FIXED_ENV and not k.startswith('GIT_')}
    # SwiftPM creates bounded local shared clones from its resolver mirror. Only
    # the fixed native package commands may use file transport; the source graph
    # and mirror chain are proved after resolution and before compilation.
    package_commands={'sidesign-resolve','sidesign-frozen-resolve','sidesign-build','sidesign-tests','anisette-resolve','anisette-frozen-resolve','anisette-build','anisette-discover','anisette-tests','sidesign-discover','anisette-trace-regression-discover','anisette-trace-regression-tests','sidesign-core-regression-discover','sidesign-core-regression-tests'}
    package_tool=str(args[0]) in {'swift','xcodebuild','/usr/bin/sandbox-exec'}
    protocols='https:file' if name in package_commands and package_tool else 'https'
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_ALLOW_PROTOCOL=protocols,GIT_NO_REPLACE_OBJECTS='1',GIT_GRAFT_FILE=os.devnull,GIT_NO_LAZY_FETCH='1',GIT_TERMINAL_PROMPT='0')
    return env

def finish_owned_child(process):
    """Signal only a retained, unreaped child identity. Never a reaped PGID."""
    state = {'pgid': process.pid, 'quiescent': False, 'pipesJoined': False,
             'signals': [], 'identityRetainedForSignals': False, 'reapedBeforeSignals': False,
             'postReapPolicy': 'read-only-group-disappearance', 'errors': []}
    result = {'ownedProcessGroup': state}
    try:
        # SIG_IGN/custom handlers could reap asynchronously and invalidate PID
        # reservation. This driver is single-threaded and owns all child waits.
        require(signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL, 'SIGCHLD identity reservation unavailable')
        if process.returncode is None:
            process.poll()  # Last possible reap before the nonzero-signal phase.
        state['reapedBeforeSignals'] = process.returncode is not None
        if process.returncode is None:
            require(os.getpgid(process.pid) == process.pid, 'Owned child process group differs')
            state['identityRetainedForSignals'] = True
            # No poll/wait/communicate is allowed between this reservation and
            # the last signal. An exited child remains an unreaped zombie, so
            # its PID/PGID cannot be reused by an unrelated process group.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                require(process.returncode is None and signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL,
                        'Owned child identity lost before signal')
                try:
                    os.killpg(process.pid, sig)
                    state['signals'].append(int(sig))
                except ProcessLookupError:
                    break
                if sig == signal.SIGTERM:
                    time.sleep(0.5)  # Bounded grace, deliberately without reaping.
    except Exception as error:
        state['errors'].append(type(error).__name__ + ': ' + str(error))
    # The signal phase has irrevocably ended. No nonzero signal below here,
    # even if a descendant retains pipes or a numeric group is reused.
    try:
        stdout, stderr = process.communicate(timeout=3)
        result.update(stdout=stdout, stderr=stderr)
        state['pipesJoined'] = True
    except Exception as error:
        state['errors'].append('Pipe join: ' + type(error).__name__)
        try:
            process.wait(timeout=1)
        except Exception as wait_error:
            state['errors'].append('Owned child reap: ' + type(wait_error).__name__)
    result['terminationReturncode'] = process.returncode
    state['leaderReaped'] = process.returncode is not None
    until = time.monotonic() + 1
    while True:
        try:
            os.killpg(process.pid, 0)  # Read-only observation, never ownership proof.
        except ProcessLookupError:
            state['quiescent'] = state['leaderReaped']
            break
        except OSError as error:
            state['errors'].append('Group observation: ' + type(error).__name__)
            break
        if time.monotonic() >= until:
            state['errors'].append('Surviving or reused group; no post-reap signal permitted')
            break
        time.sleep(0.05)
    if state['errors'] or not state['quiescent'] or not state['pipesJoined']:
        result['quiescenceError'] = 'Owned child cleanup/observation incomplete; fail closed'
    return result


class CommandRunner:
    def run(self,name,args,*,cwd=None,env=None,strict_stderr=False,stdout_only=False,timeout=7200):
        require(re.fullmatch('[a-z0-9_-]+',name),'unsafe log name')
        if getattr(self,'deadline',None) is not None:
            timeout=min(timeout,self.deadline-time.monotonic())
            require(timeout>0,'capture deadline reached; reserve workflow time for settlement and upload')
        env=command_environment(name,args,env)
        if str(args[0])=='git':args=['git','--no-replace-objects','-c','core.hooksPath='+os.devnull,'-c','core.fsmonitor=false',*args[1:]]
        args=[str(a) for a in args]
        log=self.evidence/'logs'/name;require(not log.with_suffix('.log').exists(),'duplicate execution ID: '+name)
        dump(log.with_suffix('.command.json'),{'argv':args,'cwd':str(Path.cwd() if cwd is None else cwd),'environment':{k:env[k] for k in FIXED_ENV if k in env}})
        receipt={'returncode':None,'stdout':b'','stderr':b'','timeout_seconds':timeout}
        process=None;primary=None
        try:
            require(signal.getsignal(signal.SIGCHLD)==signal.SIG_DFL,'SIGCHLD identity reservation unavailable')
            process=subprocess.Popen(args,cwd=cwd,env=env,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,text=False,start_new_session=True)
            stdout,stderr=process.communicate(timeout=timeout)
            receipt.update(returncode=process.returncode,stdout=stdout or b'',stderr=stderr or b'')
        except Exception as error:
            primary=error;receipt['error']=type(error).__name__+': '+str(error)
            if isinstance(error,subprocess.TimeoutExpired):
                receipt.update(stdout=error.stdout or b'',stderr=error.stderr or b'')
        finally:
            if process is not None:
                settled=finish_owned_child(process)
                receipt.update({k:v for k,v in settled.items() if k not in ('stdout','stderr')})
                if 'stdout' in settled:receipt['stdout']=settled['stdout'] or b''
                if 'stderr' in settled:receipt['stderr']=settled['stderr'] or b''
                self.command_quiescence.append({'label':name,**settled['ownedProcessGroup']})
            log.with_suffix('.log').write_bytes(receipt['stdout'])
            log.with_suffix('.stderr.log').write_bytes(receipt['stderr'])
            # A cleanup exit code must never turn a primary timeout into success.
            code=receipt['returncode'] if receipt['returncode'] is not None else 124 if isinstance(primary,subprocess.TimeoutExpired) else 125
            log.with_suffix('.exit-code.txt').write_text(str(code)+'\n')
            dump(log.with_suffix('.settlement.json'),{k:v for k,v in receipt.items() if k not in ('stdout','stderr')})
        if primary is not None:raise primary
        require(not receipt.get('quiescenceError'),'command writers did not settle: '+name)
        require(receipt['returncode']==0,'command failed: '+name+' (see captured log)')
        require(not strict_stderr or not receipt['stderr'],'unexpected runtime stderr: '+name)
        return (receipt['stdout'] if stdout_only else receipt['stdout']+receipt['stderr']).decode('utf-8',errors='strict')
