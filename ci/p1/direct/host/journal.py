"""Bounded immutable event-prefix reader for the maintained fixture journal."""
import os,re,time
from hashlib import sha256
from fixture_channel import parse,require

EVENT=re.compile(r'event-([0-9]{3})\.json\Z')
STRIP=re.compile(r'strip-([0-9]{4})\.json\Z')

class Journal:
    def __init__(self,directory,*,checkpoint,remaining,retain,now=time.monotonic,sleep=time.sleep):
        self.directory=directory;self.checkpoint=checkpoint;self.remaining=remaining;self.retain=retain
        self.now=now;self.sleep=sleep;self.raw=[];self.rows=[];self.failed=False
    def events(self):
        require(not self.failed,'prior journal failure')
        try:
            self.directory.check();names=os.listdir(self.directory.fd)
            require(len(names)<=805,'journal member bound')
            require(self.directory.read('journal-error.txt') is None,'journal reported failure')
            files=sorted(name for name in names if name.startswith('event-'))
            require(len(files)<=200 and all(EVENT.fullmatch(name) for name in files),'bounded event filenames')
            require(files==[f'event-{n:03d}.json' for n in range(1,len(files)+1)],'event sequence gap')
            require(len(files)>=len(self.raw),'retained event removed')
            for i,name in enumerate(files):
                raw=self.directory.read(name,256*1024);require(raw is not None,'event disappeared')
                if i<len(self.raw):require(raw==self.raw[i],'immutable event changed');continue
                row=parse(raw);require(type(row) is dict and type(row.get('type')) is str,'event object/type')
                require('error' not in row and row['type']!='direct-anchor-error','fixture event error')
                self.retain({'file':name,'sha256':sha256(raw).hexdigest(),'bytes':raw})
                self.raw.append(raw);self.rows.append(row)
            return list(self.rows)
        except BaseException:self.failed=True;raise
    def await_event(self,kind,timeout):
        require(type(kind) is str and kind in ('start','baseline-ready','window-end','post-ready'),'known awaited event')
        allowance=self.remaining(timeout);require(0<allowance<=timeout,'bounded journal wait')
        deadline=self.now()+allowance
        try:
            while self.now()<deadline:
                self.checkpoint();rows=[r for r in self.events() if r['type']==kind]
                require(len(rows)<=1,'duplicate protocol event')
                if rows:
                    require(self.now()<=deadline,'late event observation')
                    return rows[0]
                self.sleep(.05)
            raise ValueError('fixture event deadline')
        except BaseException:self.failed=True;raise
    def finalized(self):
        """Call only after owned native writers are settled and method completed."""
        self.events();names=os.listdir(self.directory.fd)
        allowed={'request.json','response.json','strip-complete.json'}|{f'event-{n:03d}.json' for n in range(1,len(self.raw)+1)}
        require(all(name in allowed or STRIP.fullmatch(name) for name in names),'unexpected final journal member')
        complete_raw=self.directory.read('strip-complete.json',256*1024);require(complete_raw is not None,'strip completion absent')
        complete=parse(complete_raw);require(type(complete) is dict and complete.get('schema')=='p1-strip-complete-v1' and complete.get('admissionEligible') is False,'strip completion schema')
        batches=complete.get('batches');require(type(batches) is int and 1<=batches<=600,'strip batch bound')
        files=sorted(name for name in names if STRIP.fullmatch(name))
        require(files==[f'strip-{i:04d}.json' for i in range(1,batches+1)],'strip sequence/count')
        draws=[];retained=[]
        for n,name in enumerate(files,1):
            raw=self.directory.read(name,256*1024);require(raw is not None,'strip disappeared')
            row=parse(raw)
            require(type(row) is dict and row.get('schema')=='p1-strip-batch-v1' and type(row.get('batch')) is int and row['batch']==n,'strip batch identity')
            items=row.get('draws');require(type(items) is list and 1<=len(items)<=30 and (n==batches or len(items)==30),'strip interior count')
            draws.extend(items);retained.append({'file':name,'sha256':sha256(raw).hexdigest(),'bytes':raw})
        require(type(complete.get('drawCount')) is int and complete['drawCount']==len(draws),'strip draw inventory')
        for row in retained:self.retain(row)
        self.retain({'file':'strip-complete.json','sha256':sha256(complete_raw).hexdigest(),'bytes':complete_raw})
        return {'events':list(self.rows),'eventBytes':tuple(self.raw),'strip':{'complete':complete,'draws':draws}}
