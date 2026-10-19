"""Receipt-relative sampled-label predicates. Pixel provenance is external."""
SECOND = 1_000_000_000


def bounds(value):
    if not isinstance(value,(tuple,list)) or len(value)!=2 or any(type(x) is not int for x in value) or value[0]>value[1]:
        raise ValueError('integer conservative bounds required')
    return value


def lifetime(observations,event,old_event=None):
    event=bounds(event)
    target=event[1]+1_500_000_000
    if old_event is not None:target=max(target,bounds(old_event)[1]+2_250_000_000)
    if any(row.get("label") not in ("Copied", "Copy Details", "expected-dismissal-absence") for row in observations):
        raise ValueError("unknown label observation")
    times=[bounds(row['appNs']) for row in observations]
    if any(right[0]<=left[0] or right[1]<=left[1] for left,right in zip(times,times[1:])):
        raise ValueError('unordered observations')
    copied=[i for i,(row,t) in enumerate(zip(observations,times)) if row['label']=='Copied' and t[0]>=event[1] and t[1]<event[0]+5*SECOND]
    if not copied:raise ValueError('no actual Copied observation')
    first=copied[0]
    witnesses=[i for i in copied if times[i][0]>=target]
    if not witnesses:raise ValueError('no conservative lifetime witness')
    witness=witnesses[0]
    if any(row['label']!='Copied' for row in observations[first:witness+1]):
        raise ValueError('non-Copied observation in claimed interval')
    reset=next((i for i in range(witness+1,len(observations)) if observations[i]['label']=='Copy Details' and times[i][0]>times[witness][1]),None)
    if reset is None or times[reset][1]-event[0]>=5*SECOND:
        raise ValueError('expiry not conservatively below five seconds')
    if any(row['label'] not in ('Copied','Copy Details') for row in observations[witness:reset+1]):
        raise ValueError('unknown or absent pixels before expiry')
    return dict(scope='sampled-receipt-relative-labels-only',first=first,witness=witness,reset=reset,
                minimumLifetimeNs=times[witness][0]-event[1],expiryUpperNs=times[reset][1]-event[0],admissionEligible=False)


def overlap(first,second,third):
    first,second,third=map(bounds,(first,second,third))
    spacing=(second[0]-first[1],second[1]-first[0])
    if spacing[0]<750_000_000 or spacing[1]>=2*SECOND:
        raise ValueError('actual receipt overlap not established')
    if third[0]-second[1]<5*SECOND:
        raise ValueError('ordinary third event not separated')
    return spacing


def reset_between(observations,after,before):
    after,before=bounds(after),bounds(before)
    return any(row['label']=='Copy Details' and bounds(row['appNs'])[0]>after[1]
               and bounds(row['appNs'])[1]<before[0] for row in observations)
