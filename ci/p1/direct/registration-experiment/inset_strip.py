"""Retained pre-promotion 40% rule for the synthetic comparison only."""
from fractions import Fraction

def _exact(value):
    if type(value) not in (int,Fraction):raise ValueError('exact coordinate required')
    return Fraction(value)


def cell_interiors(marker, x_region, y_region, crop):
    # marker=(left,top,width,height), crop=(x,y,width,height). Use middle40%
    # source-cell interiors, then intersect over every feasible transform.
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
        x0,x1=interior(left+width*(Fraction(cell)+Fraction(3,10))/24,
                      left+width*(Fraction(cell)+Fraction(7,10))/24,axes[0],crop[0])
        y0,y1=interior(top+height*Fraction(3,10),top+height*Fraction(7,10),axes[1],crop[1])
        if x0<0 or y0<0 or x1>crop[2] or y1>crop[3]:raise ValueError('cell clipped from retained crop')
        rows.append((x0,y0,x1,y1))
    return tuple(rows)

