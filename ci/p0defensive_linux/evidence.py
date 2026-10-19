"""Fail-closed complete evidence walk; only the ordinary root index is exempt."""
import os,stat
from pathlib import Path
from inventory import require,sha,dump,parse,ordinary

def safe_index(root):
    # Descriptor-anchored traversal cannot follow a raced directory or file link.
    import hashlib
    from retention import _directory, _identity, _snapshot, MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_FILES, MAX_DIRECTORIES, MAX_DEPTH
    files={};directories=[];total=0
    def visit(fd,prefix='',depth=0):
        nonlocal total
        require(depth<=MAX_DEPTH,'evidence depth bound exceeded')
        initial=os.fstat(fd)
        names=sorted(os.listdir(fd))
        for name in names:
            require(name not in ('.','..') and '/' not in name,'unsafe evidence name')
            relative=prefix+name;s=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if stat.S_ISDIR(s.st_mode):
                require(len(directories)<MAX_DIRECTORIES,'evidence directory bound exceeded');directories.append(relative)
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                try:
                    require(_identity(s)==_identity(os.fstat(child)),'evidence directory substituted');visit(child,relative+'/',depth+1)
                finally:os.close(child)
                require(_identity(s)==_identity(os.stat(name,dir_fd=fd,follow_symlinks=False)),'evidence directory replaced')
            else:
                require(stat.S_ISREG(s.st_mode) and s.st_nlink==1,'linked, hardlinked or special evidence entry')
                require(0<=s.st_size<=MAX_FILE_BYTES,'evidence file bound exceeded')
                # Validate type first; never exempt a FIFO, link, or directory.
                if relative=='evidence-index.json':continue
                require(len(files)<MAX_FILES,'evidence file count bound exceeded');total+=s.st_size;require(total<=MAX_TOTAL_BYTES,'evidence total bound exceeded')
                child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                try:
                    require(_snapshot(s)==_snapshot(os.fstat(child)),'evidence file substituted before read');digest=hashlib.sha256();length=0
                    while True:
                        raw=os.read(child,1024*1024)
                        if not raw:break
                        length+=len(raw);require(length<=s.st_size,'evidence grew during read');digest.update(raw)
                    require(length==s.st_size and _snapshot(s)==_snapshot(os.fstat(child)),'evidence changed during read')
                finally:os.close(child)
                require(_snapshot(s)==_snapshot(os.stat(name,dir_fd=fd,follow_symlinks=False)),'evidence path replaced')
                files[relative]=digest.hexdigest()
        require(names==sorted(os.listdir(fd)) and _snapshot(initial)==_snapshot(os.fstat(fd)),'evidence directory changed during indexing')
    try:
        with _directory(root) as fd:visit(fd)
    except OSError as error:raise ValueError('unsafe evidence entry: '+str(error)) from error
    return {'files':dict(sorted(files.items())),'directories':sorted(directories)}
def settled(groups):
    return isinstance(groups,list) and bool(groups) and all(row.get('quiescent') is True and row.get('pipesJoined') is True and row.get('leaderReaped') is True and row.get('errors')==[] for row in groups)
def verify_transport(root):
    require(root is not None,'evidence path required')
    index=parse(ordinary(root,'evidence-index.json').read_bytes())
    require(index==safe_index(root),'complete evidence index changed')
    state=parse(ordinary(root,'provenance/result.json').read_bytes());groups=parse(ordinary(root,'provenance/owned-command-groups.json').read_bytes())
    require(state.get('writers_quiescent') is True and state.get('retention_errors')==[] and settled(groups),'evidence writers/retention incomplete')
    return {'status':'QUIESCENT_INDEX_VERIFIED','indexed_files':len(index['files']),'directories':len(index['directories']),'capture_status':state['status'],'authenticated_capture':state['authenticated_capture']}
