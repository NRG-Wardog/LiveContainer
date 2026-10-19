"""Decode all24 live-strip cells from guaranteed interiors, never ideal centers.

The transform must already be independently established and source-bound. This
module does not solve registration or supply missing coordinate uncertainty.
"""
from fractions import Fraction
import hashlib


def _exact(value):
    if type(value) not in (int,Fraction):raise ValueError('exact coordinate required')
    return Fraction(value)


def cell_interiors(marker, x_region, y_region, crop):
    # Whole-source-cell intersection; no chosen center or rendering-error bound.
    # Every retained unit pixel must fit every feasible transform.
    if len(marker)!=4 or len(crop)!=4:raise ValueError('rectangle shape')
    left,top,width,height=map(_exact,marker)
    if width<=0 or height<=0:raise ValueError('marker extent')
    if any(type(v) is not int for v in crop) or min(crop)<0 or crop[2]<=0 or crop[3]<=0:raise ValueError('crop extent')
    axes=[]
    for region in (x_region,y_region):
        if not region or len(region)>128:raise ValueError('bounded feasible transform required')
        values=[tuple(map(_exact,p)) for p in region]
        if any(len(p)!=2 or p[0]<=0 for p in values):raise ValueError('positive affine transform required')
        axes.append(values)
    def interior(low,high,region,origin):
        lo=max(s*low+t for s,t in region)-origin
        hi=min(s*high+t for s,t in region)-origin
        # Whole retained pixels must fit the guaranteed intersection, including
        # their complete unit support, rather than only their center.
        first=-((-lo.numerator)//lo.denominator)
        end=hi.numerator//hi.denominator
        if first>=end:raise ValueError('unresolved cell interior')
        return first,end
    rows=[]
    for cell in range(24):
        x0,x1=interior(left+width*(Fraction(cell)+Fraction(0))/24,
                      left+width*(Fraction(cell)+Fraction(1))/24,axes[0],crop[0])
        y0,y1=interior(top+height*Fraction(0),top+height*Fraction(1),axes[1],crop[1])
        if x0<0 or y0<0 or x1>crop[2] or y1>crop[3]:raise ValueError('cell clipped from retained crop')
        rows.append((x0,y0,x1,y1))
    return tuple(rows)


def decode(data,width,height,cells):
    if type(width) is not int or type(height) is not int or not 1<=width<=2048 or not 1<=height<=2048:
        raise ValueError('bounded strip geometry')
    if type(data) is not bytes or len(data)!=width*height*4 or len(data)>1024*1024:raise ValueError('retained immutable strip bytes')
    if type(cells) is not tuple or len(cells)!=24:raise ValueError('all24 cell interiors required')
    bits=[];prior=-1
    for rectangle in cells:
        if type(rectangle) is not tuple or len(rectangle)!=4 or any(type(v) is not int for v in rectangle):raise ValueError('integer cell geometry')
        x0,y0,x1,y1=rectangle
        if not (0<=x0<x1<=width and 0<=y0<y1<=height and x0>=prior):raise ValueError('cell containment or order')
        values=set()
        for y in range(y0,y1):
            for x in range(x0,x1):
                at=(y*width+x)*4;b,g,r,a=data[at:at+4]
                if a!=255:raise ValueError('transparent strip cell')
                if max(b,g,r)<50:values.add(False)
                elif min(b,g,r)>205:values.add(True)
                else:raise ValueError('unknown strip cell')
        if len(values)!=1:raise ValueError('nonuniform strip cell')
        bits.append(values.pop());prior=x1
    if bits[:4]!=[False,True,False,True] or bits[20:]!=[True,False,True,False]:raise ValueError('strip registration bits')
    marker=sum(int(bits[i+4])<<i for i in range(16))
    if not 1<=marker<18000:raise ValueError('strip marker outside maintained inventory')
    return {'schema':'p1-direct-retained-strip-v1','marker':marker,'sha256':hashlib.sha256(data).hexdigest(),
            'sampledCells':[list(r) for r in cells],'admissionEligible':False}
