"""Diagnostic-only minimal bootstrap; identical child protocol/behavior."""
import time
_CHILD_FIRST_PYTHON=time.monotonic()
import os,struct,sys,errno
_CHILD_IMPORTS_COMPLETE=time.monotonic()
LAUNCH_RECORD=struct.Struct("!4sBqqq16sQdddddi")
LAUNCH_MAGIC=b"P1D1"
def child_main(args):
    if len(args)!=7 or args[0]!='--child' or args[2]!='--launch-receipt' or args[-1]!='/usr/bin/true':raise SystemExit('private launch gate requires exact child arguments')
    descriptor=int(args[1]);target=args[2:];receipt=None
    if target[0]=='--launch-receipt':
        receipt=int(target[1]);session=bytes.fromhex(target[2]);command=int(target[3]);target=target[4:]
        os.set_inheritable(receipt,False)
    gate_enter=time.monotonic()
    signal_byte=os.read(descriptor,1);gate_exit=time.monotonic();os.close(descriptor)
    if signal_byte!=b'G':os._exit(125)
    def emit(kind,number):
        try:
            record=LAUNCH_RECORD.pack(LAUNCH_MAGIC,kind,os.getpid(),os.getpgrp(),os.getsid(0),session,command,_CHILD_FIRST_PYTHON,_CHILD_IMPORTS_COMPLETE,gate_enter,gate_exit,time.monotonic(),number)
            return os.write(receipt,record)==len(record)
        except (OSError,ValueError,struct.error):return False
    if receipt is None:os.execvp(target[0],target)
    if not emit(1,0):os._exit(125)
    try:os.execvp(target[0],target)
    except OSError as error:
        if receipt is not None:emit(2,error.errno if type(error.errno) is int and error.errno>0 else errno.EIO)
        os._exit(126)
    except (ValueError,IndexError):
        if receipt is not None:emit(2,errno.EINVAL)
        os._exit(126)


if __name__=='__main__':child_main(sys.argv[1:])
