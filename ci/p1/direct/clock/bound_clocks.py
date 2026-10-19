"""Strict session-scoped clock rows, conditional on a stable-rate scenario.

Caller must authenticate identity against the owned process/container/source
receipts. This parser cannot make caller-provided identity authentic by itself.
"""
from fractions import Fraction
import math
import re
import direct_clock as clock

IDENTITY_KEYS={'session','simulatorUDID','hostPID','appContainerReceiptSHA256','sourceSHA256'}
APP_KEYS={'phase','ordinal','requestID','hostBeforeNs','hostAfterNs','appReceive','appSend'}
MACH_KEYS={'phase','ordinal','hostBeforeNs','hostAfterNs','machTicks','timebaseNumer','timebaseDenom'}


def exact(row, keys):
    if type(row) is not dict or set(row)!=keys:raise ValueError('exact clock schema required')


def identity(row):
    exact(row,IDENTITY_KEYS)
    for key,size in (('session',32),('appContainerReceiptSHA256',64),('sourceSHA256',64)):
        if type(row[key]) is not str or re.fullmatch('[0-9a-f]{'+str(size)+'}',row[key]) is None:
            raise ValueError('clock identity hash/session')
    if type(row['simulatorUDID']) is not str or re.fullmatch('[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}',row['simulatorUDID']) is None:
        raise ValueError('clock simulator identity')
    if type(row['hostPID']) is not int or not 2<=row['hostPID']<=2**31-1:raise ValueError('clock host identity')


def uptime(value):
    if type(value) not in (float,int) or not math.isfinite(value) or value<0:raise ValueError('native Double uptime required')
    if type(value) is int and (value>2**53 or int(float(value))!=value):raise ValueError('inexact serialized Double integer')
    value=float(value)
    low=max(0.,math.nextafter(value,-math.inf));high=math.nextafter(value,math.inf)
    if not math.isfinite(high):raise ValueError('uptime overflow')
    return Fraction(low)*10**9,Fraction(high)*10**9


def inspect(document, expected_identity):
    exact(document,{'schema','identity','appExchanges','machExchanges','model','admissionEligible'})
    identity(expected_identity);identity(document['identity'])
    if document['identity']!=expected_identity:raise ValueError('foreign clock identity')
    if document['schema']!='p1-direct-bound-clocks-v1' or document['admissionEligible'] is not False:
        raise ValueError('clock envelope')
    if document['model']!='scenario-wide-constant-offset-and-unit-rate-conditional':raise ValueError('clock model must be explicit')
    app=document['appExchanges'];mach=document['machExchanges']
    if type(app) is not list or type(mach) is not list or len(app)!=24 or len(mach)!=24:raise ValueError('all24 clock samples required')
    phases={};last=None;last_app_send=None
    for phase,first_id in zip(clock.PHASES,(1,11,21)):
        rows=app[len(phases)*8:(len(phases)+1)*8];bounds=[]
        for ordinal,row in enumerate(rows,1):
            exact(row,APP_KEYS)
            if row['phase']!=phase or type(row['ordinal']) is not int or row['ordinal']!=ordinal or type(row['requestID']) is not int or row['requestID']!=first_id+ordinal-1:
                raise ValueError('original clock command inventory')
            before=clock.integer(row['hostBeforeNs'],'app host before');after=clock.integer(row['hostAfterNs'],'app host after')
            if after<before or (last is not None and before<last):raise ValueError('app exchange chronology')
            receive=uptime(row['appReceive']);send=uptime(row['appSend'])
            if row['appSend']<row['appReceive'] or (last_app_send is not None and row['appReceive']<last_app_send):raise ValueError('app response clock reversal')
            last_app_send=row['appSend']
            bounds.append(clock.interval(send[0]-after,receive[1]-before));last=after
        phases[phase]=clock.intersection(bounds)
    for row in mach:exact(row,MACH_KEYS)
    host_phases,_=clock.phase_bridge(mach)
    combined,common=clock.combine(phases,host_phases)
    return {'appHostPhases':phases,'hostMachPhases':host_phases,'combinedPhases':combined,
            'commonAppMinusMach':common,'model':document['model'],
            'scenarioBoundaryMappingConditional':True,'unsampledDriftExcluded':False,
            'admissionEligible':False}
