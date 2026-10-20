"""Metadata-only exception for the owned benign native probe, never helper stacks.

Returned text is never a filesystem path input or an acceptance predicate.
"""
import re

MAX_REPORT_BYTES=512*1024
MAX_PATH_BYTES=1024
LIVE_KEYS=frozenset(('owned-object','owned-registry','child-live','launch-binding',
                     'launch-eof','launch-no-exec-failure','launch-pre-exec','launch-state'))


def printable_path(value):
    return (type(value) is str and 0<len(value.encode('utf-8'))<=MAX_PATH_BYTES and
            value.isprintable() and '\n' not in value and '\r' not in value)


def extract(raw,*,pid,parent,expected_path,pre_checks,post_checks,image_unchanged,owned_native_probe):
    # Failure emits a fixed code only, never a rejected header, report or exception.
    def reject(code):return {'code':code}
    if owned_native_probe is not True:return reject('native-probe-required')
    for checks in (pre_checks,post_checks):
        if type(checks) is not dict or any(checks.get(key) is not True for key in LIVE_KEYS):
            return reject('original-child-live-receipts-required')
    if image_unchanged is not True:return reject('unchanged-native-image-required')
    if type(raw) is not bytes or not 0<len(raw)<=MAX_REPORT_BYTES:return reject('bounded-report-required')
    try:text=raw.decode('utf-8',errors='strict')
    except UnicodeError:return reject('utf8-required')
    fields={}
    for name,code in [('Process','process'),('Path','path'),('Parent Process','parent')]:
        # Only one physical line per header. Unlike the authoritative historical
        # regex, horizontal padding cannot consume a newline or another header.
        values=re.findall(r'^'+re.escape(name)+r':([^\n]*)$',text,re.M)
        if len(values)!=1:return reject(code+'-unique-header-required')
        fields[name]=values[0].strip(' \t')
    if re.fullmatch(r'.+ \['+str(pid)+r'\]',fields['Process']) is None:return reject('exact-pid-required')
    if re.fullmatch(r'.+ \['+str(parent)+r'\]',fields['Parent Process']) is None:return reject('exact-parent-required')
    # Reject an apparent wrapped/continued Path line instead of retaining only
    # its first fragment. This gate affects metadata only, never acceptance.
    tail=text.split('\n')
    index=next(i for i,line in enumerate(tail) if line.startswith('Path:'))
    for line in tail[index+1:]:
        if re.match(r'^[A-Za-z][A-Za-z0-9 ()/_-]*:',line):break
        if line.strip(' \t'):
            return reject('single-line-path-header-required')
    value=fields['Path']
    if not printable_path(value):return reject('bounded-printable-single-line-path-required')
    return {'code':'bounded-path-retained','reportedPath':value,'pathBytes':len(value.encode('utf-8')),
            'pathPrintable':True,'pathSingleLine':True,'pathMatchesExpected':value==expected_path,
            'admissionEligible':False,'purpose':'benign-probe-rejection-only'}
