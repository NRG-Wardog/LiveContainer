"""Bounded original ZIP and raw-byte replay. Never extracts or executes evidence."""
import collections.abc
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import zipfile

MAX_ARCHIVE = 8 * 1024**3
MAX_EXPANDED = MAX_ARCHIVE + 128 * 1024**2
MAX_MEMBER = 512 * 1024**2
MAX_MEMBERS = 140000
MAX_JSON = 64 * 1024**2

def require(value, message):
    if not value:
        raise ValueError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def object_id(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result

def parse(raw):
    require(isinstance(raw, bytes) and len(raw) <= MAX_JSON, 'bounded original JSON required')
    def invalid(_):
        raise ValueError('nonfinite JSON number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)

def safe_path(name, empty=False):
    require(isinstance(name,str) and (empty and name == '' or name and '\\' not in name and '\0' not in name and ':' not in name and all(p not in ('','.','..') for p in name.split('/'))), 'unsafe retained path')
    require(len(name.encode('utf-8')) <= 4096 and len(name.split('/')) <= 128, 'retained path exceeds bound')
    return name

def filesystem_metadata_path(name):
    """Literal POSIX tree metadata only; never an archive, Git, blob or output path."""
    require(isinstance(name,str) and all(ord(char)>=32 and not 127<=ord(char)<=159 for char in name),'control byte in retained filesystem path')
    require(name=='' or (not name.startswith('/') and '\\' not in name and all(part not in ('','.','..') for part in name.split('/'))),'unsafe retained filesystem path')
    require(re.match(r'^[A-Za-z]:',name) is None,'drive-like retained filesystem path')
    require(len(name.encode('utf-8'))<=4096 and len(name.split('/'))<=128,'retained filesystem path exceeds bound')
    return name


def _stat(info):
    return info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns

class ArchiveFiles(collections.abc.Mapping):
    """One no-follow descriptor, streaming SHA256, bounded lazy original members."""
    def __init__(self,path):
        import retrieve_prior
        self.path=Path(path)
        parts=retrieve_prior._parts(self.path)
        parent=retrieve_prior._directory_fd(parts[:-1])
        try: fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        finally: os.close(parent)
        self.file=os.fdopen(fd,'rb')
        try:
            self.before=os.fstat(fd)
            require(stat.S_ISREG(self.before.st_mode) and 0<self.before.st_size<=MAX_ARCHIVE,'ordinary bounded ZIP required')
            h=hashlib.sha256();count=0
            for chunk in iter(lambda:self.file.read(1024**2),b''):
                count+=len(chunk);require(count<=MAX_ARCHIVE,'archive grew beyond limit');h.update(chunk)
            require(count==self.before.st_size,'archive changed length')
            self.identity={'sha256':h.hexdigest(),'bytes':count}
            end=zipfile._EndRecData(self.file)
            require(end is not None and 0<end[zipfile._ECD_ENTRIES_TOTAL]<=MAX_MEMBERS and end[zipfile._ECD_SIZE]<=128*1024**2,'ZIP central directory bound exceeded')
            require(end[zipfile._ECD_DISK_NUMBER]==end[zipfile._ECD_DISK_START]==0 and end[zipfile._ECD_ENTRIES_THIS_DISK]==end[zipfile._ECD_ENTRIES_TOTAL],'multi-volume ZIP forbidden')
            self.file.seek(0);self.zip=zipfile.ZipFile(self.file)
            rows=self.zip.infolist();require(0<len(rows)<=MAX_MEMBERS,'ZIP entry bound exceeded')
            raw={};seen=set();total=0
            for item in rows:
                require(item.orig_filename==item.filename,'NUL-truncated ZIP name')
                name=item.filename.removesuffix('/') if item.is_dir() else item.filename
                safe_path(name);key=name.casefold()
                require(key not in seen,'duplicate or case-alias ZIP name');seen.add(key)
                require(not item.flag_bits&1 and item.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED),'unsupported ZIP encoding')
                kind=stat.S_IFMT(item.external_attr>>16)
                require(kind in ((0,stat.S_IFDIR) if item.is_dir() else (0,stat.S_IFREG)),'ZIP links or special files forbidden')
                require(item.file_size<=MAX_MEMBER,'ZIP member too large')
                require(item.file_size<=max(item.compress_size,1)*2000,'ZIP compression ratio exceeded')
                total+=item.file_size;require(total<=MAX_EXPANDED,'ZIP expansion bound exceeded')
                if not item.is_dir():raw[name]=item
            prefix='' if 'evidence-index.json' in raw else 'p0defensive-evidence/'
            require(raw and all(n.startswith(prefix) for n in raw),'unexpected artifact root')
            self.members={n[len(prefix):]:i for n,i in raw.items()}
            require('evidence-index.json' in self.members,'missing original evidence index')
            for name in self.members:
                require(not any('/'.join(name.split('/')[:n]) in self.members for n in range(1,len(name.split('/')))),'file/directory ZIP collision')
                require(name=='evidence-index.json' or name.split('/')[-1]!='evidence-index.json','nested alternate evidence index')
            self.identity.update(files=len(self.members),stripped_prefix=prefix)
            self.check_unchanged()
        except BaseException:
            self.file.close();raise
    def __getitem__(self,key):
        item=self.members[key];raw=self.zip.read(item)
        require(len(raw)==item.file_size,'ZIP member length changed')
        self.check_unchanged();return raw
    def __iter__(self):return iter(self.members)
    def __len__(self):return len(self.members)
    def check_unchanged(self):
        require(_stat(os.fstat(self.file.fileno()))==_stat(self.before),'original ZIP mutated during replay')
    def close(self):
        self.check_unchanged();self.zip.close();self.file.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

def tree_object(entries):
    """Reconstruct all recursive Git tree objects without invoking Git."""
    root={}
    for path,(mode,kind,oid) in entries.items():
        safe_path(path);require(mode in ('100644','100755','120000','160000'),'unexpected Git mode')
        require(kind==('commit' if mode=='160000' else 'blob'),'Git mode/type mismatch')
        require(re.fullmatch('[0-9a-f]{40}',oid),'invalid Git object ID')
        node=root;parts=path.split('/')
        for part in parts[:-1]:
            node=node.setdefault(part,{})
            require(isinstance(node,dict),'Git file/directory collision')
        require(parts[-1] not in node,'duplicate Git path');node[parts[-1]]=(mode,oid)
    directories={}
    def encode(node,prefix=''):
        rows=[]
        for name,value in node.items():
            rawname=os.fsencode(name)
            if isinstance(value,dict):
                oid=encode(value,prefix+name+'/');mode='40000';sort=rawname+b'/';directories[(prefix+name)]=oid
            else:mode,oid=value;sort=rawname
            rows.append((sort,mode.encode()+b' '+rawname+b'\0'+bytes.fromhex(oid)))
        return object_id('tree',b''.join(row for _,row in sorted(rows)))
    return encode(root),directories

class RawReplay:
    def __init__(self,files,bounds):
        self.files=files;self.bounds=bounds;self.references=set();self.checked={};self.tree_count=0
    def raw_record(self,record,namespace=''):
        require(isinstance(record,dict),'raw byte record required')
        digest=record.get('sha256');require(isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest),'raw SHA256 required')
        expected='blobs/sha256/'+digest[:2]+'/'+digest
        require(record.get('blob_path')==expected,'noncanonical raw blob path')
        length=record.get('length');require(type(length) is int and 0<=length<=self.bounds['file_bytes'],'raw byte length bound')
        name=(namespace+'/' if namespace else '')+expected
        safe_path(name);require(name in self.files,'referenced original raw blob absent: '+name)
        raw=self.files[name];require(len(raw)==length and sha(raw)==digest,'raw retained bytes differ')
        git_raw=b'blob '+str(length).encode()+b'\0'+raw
        require(record.get('git_blob_sha1')==hashlib.sha1(git_raw).hexdigest() and record.get('git_blob_sha256')==hashlib.sha256(git_raw).hexdigest(),'retained raw Git blob identity differs')
        if 'git_blob_oid' in record:require(object_id('blob',raw)==record['git_blob_oid'],'retained Git blob differs')
        mode=record.get('mode')
        if mode is not None:require(isinstance(mode,str) and re.fullmatch('[0-7]{4}|100644|100755|120000',mode),'raw mode invalid')
        if record.get('kind')=='symlink' and 'target' in record:require(os.fsencode(record['target'])==raw,'literal retained link differs')
        self.references.add(name);self.checked[name]=(length,digest)
        return raw
    def tree(self,record,namespace=''):
        require(record.get('kind') in ('filesystem-tree','git-tree'),'retained tree kind required')
        rows=record.get('entries');require(isinstance(rows,list) and len(rows)<=self.bounds['files']+self.bounds['directories'],'retained tree entries bound')
        seen=set();entries={};directory_names=set();links=[]
        for row in rows:
            require(isinstance(row,dict),'retained tree row required');name=filesystem_metadata_path(row.get('path')) if record['kind']=='filesystem-tree' else safe_path(row.get('path'))
            require(name not in seen,'duplicate retained tree path');seen.add(name)
            kind=row.get('kind')
            if kind=='directory':
                require(record['kind']=='filesystem-tree' and re.fullmatch('[0-7]{4}',row.get('mode','')),'directory mode invalid');directory_names.add(name);continue
            require(kind in ('file','symlink'),'unexpected retained member kind')
            self.raw_record(row,namespace)
            require(row.get('source_path')==record['source_path'].rstrip('/')+'/'+name,'retained member source path differs')
            if record['kind']=='git-tree':
                mode=row.get('git_mode');require(mode==row.get('mode') and mode in ('100644','100755','120000'),'retained Git mode mismatch')
                require(kind==('symlink' if mode=='120000' else 'file') and row.get('byte_source')=='committed-git-object','retained Git content source differs')
                entries[name]=(mode,'blob',row['git_blob_oid'])
            elif kind=='symlink':links.append(row)
        if record['kind']=='git-tree':
            tree,directories=tree_object(entries);require(tree==record['tree'],'reconstructed original Git tree differs')
            expected=[{'path':p,'git_mode':'040000','git_tree_oid':oid} for p,oid in sorted(directories.items(),key=lambda x:os.fsencode(x[0]))]
            actual=record.get('directories');require(isinstance(actual,list) and len(actual)==len(expected) and sorted(actual,key=lambda x:os.fsencode(x['path']))==expected,'retained Git directory inventory differs')
        else:
            require('' in directory_names,'retained filesystem root missing')
            for name in seen:
                for count in range(1,len(name.split('/'))):require('/'.join(name.split('/')[:count]) in directory_names,'missing retained ancestor directory')
            for link in links:self._link(link,rows)
        self.tree_count+=1
        return entries if record['kind']=='git-tree' else {r['path']:r for r in rows}
    def _link(self,link,rows):
        index={r['path']:r for r in rows};current=link['path'].split('/')[:-1];pending=collections.deque(link['target'].split('/'));hops=0
        require(link['target'] and not link['target'].startswith('/'),'absolute/empty retained tree link')
        while pending:
            part=pending.popleft()
            if part in ('','.'):continue
            if part=='..':require(current,'retained link escapes tree');current.pop();continue
            name='/'.join(current+[part]);require(name in index,'dangling retained link')
            row=index[name]
            if row['kind']=='symlink':
                hops+=1;require(hops<=self.bounds['symlink_hops'],'retained link cycle')
                target=row['target'];require(target and not target.startswith('/'),'absolute/empty retained link');pending.extendleft(reversed(target.split('/')))
            else:
                if pending:require(row['kind']=='directory','retained link traverses file')
                current.append(part)
    def scan(self,value,namespace=''):
        if isinstance(value,dict):
            if 'blob_path' in value:self.raw_record(value,namespace)
            if value.get('kind') in ('git-tree','filesystem-tree'):
                self.tree(value,namespace);return
            for child in value.values():self.scan(child,namespace)
        elif isinstance(value,list):
            for child in value:self.scan(child,namespace)
    def finish(self):
        present={name for name in self.files if re.fullmatch(r'(?:host-tests/[^/]+/)?blobs/sha256/[0-9a-f]{2}/[0-9a-f]{64}',name)}
        require(present==self.references,'unreferenced or missing original raw blob')
        require(sum(length for length,_ in self.checked.values())<=self.bounds['total_bytes'],'aggregate original raw bytes exceed retention limit')
        return {'unique_raw_blobs':len(self.references),'unique_raw_bytes':sum(n for n,_ in self.checked.values()),'replayed_trees':self.tree_count}
