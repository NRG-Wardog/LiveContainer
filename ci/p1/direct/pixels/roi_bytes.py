"""Lossless same-sample BGRA crop primitive; no identity/geometry admission."""
import hashlib
import re

ROLES = ('control', 'marker', 'anchor-1', 'anchor-2', 'anchor-3', 'anchor-4')


def extract(raw, width, height, stride, regions, *, session, record, max_bytes=512*1024):
    if type(raw) is not bytes:
        raise ValueError('immutable sample bytes required')
    if any(type(x) is not int for x in (width,height,stride,record,max_bytes)):
        raise ValueError('integer geometry required')
    if not 1<=width<=2048 or not 1<=height<=2048 or not width*4<=stride<=width*4+256 or stride%4:
        raise ValueError('bounded BGRA geometry required')
    if len(raw)!=height*stride or not 1<=record<=6000 or not 1<=max_bytes<=512*1024:
        raise ValueError('sample size/record/budget')
    if not isinstance(session,str) or re.fullmatch('[0-9a-f]{32}',session) is None:
        raise ValueError('session identifier')
    if not isinstance(regions,dict) or set(regions)!=set(ROLES):
        raise ValueError('complete declared ROI inventory required')
    bounds=[];total=0
    for role in ROLES:
        value=regions[role]
        if not isinstance(value,(tuple,list)) or len(value)!=4 or any(type(x) is not int for x in value):
            raise ValueError('integer outward ROI bounds required')
        x,y,w,h=value
        if x<0 or y<0 or w<=0 or h<=0 or x+w>width or y+h>height:
            raise ValueError('clipped or empty ROI')
        for _,ox,oy,ow,oh in bounds:
            if x<ox+ow and ox<x+w and y<oy+oh and oy<y+h:
                raise ValueError('overlapping declared ROIs')
        bounds.append((role,x,y,w,h));total+=w*h*4
    if total>max_bytes:
        raise ValueError('ROI byte ceiling exceeded')
    crops={};metadata=[]
    for role,x,y,w,h in bounds:
        data=b''.join(raw[row*stride+x*4:row*stride+(x+w)*4] for row in range(y,y+h))
        crops[role]=data
        metadata.append(dict(role=role,rect=[x,y,w,h],stride=w*4,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
    return crops,dict(schema='p1-direct-same-sample-roi-v1',session=session,record=record,
        sourceDimensions=[width,height],sourceStride=stride,
        sourceBufferSHA256=hashlib.sha256(raw).hexdigest(),sourceBufferRetained=False,
        crops=metadata,copiedBytes=total,scope='lossless-crop-bytes-only',admissionEligible=False)
