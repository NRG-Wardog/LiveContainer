"""Inclusive uncompressed one-case storage bounds, never optimistic compression."""
from pathlib import Path
import os,stat,shutil
from fixture_channel import require
GIB=1024**3;MIB=1024**2
MAX_FILES=65536;MAX_PATH_BYTES=512;ARCHIVE_OVERHEAD=128*MIB
MAX_EVIDENCE=4*GIB-ARCHIVE_OVERHEAD

def preflight(root):
    # Every frame's six ROIs together, not six independent1MiB allowances.
    raw_limit=3*GIB;raw=min(6000*MIB,raw_limit);metadata=6000*8192;context=64*MIB;journal=64*MIB;ancillary=512*MIB
    evidence=raw+metadata+context+journal+ancillary;archive=evidence+ARCHIVE_OVERHEAD
    peak=evidence+2*archive+512*MIB
    require(archive<=4*GIB,'declared evidence does not fit16 uncompressed parts')
    free=shutil.disk_usage(root).free;require(free>=peak,'insufficient conservative evidence/archive/parts/temp disk')
    return dict(schema='p1-direct-inclusive-storage-plan-v1',maxRecords=6000,combinedROIPerRecord=MIB,rawByteLimit=raw_limit,plannedRawBytes=raw,
                metadataPerRecord=8192,contextBytes=context,journalBytes=journal,ancillaryBytes=ancillary,
                archiveOverheadBytes=ARCHIVE_OVERHEAD,maxEvidenceBytes=MAX_EVIDENCE,
                plannedEvidenceBytes=evidence,plannedArchiveBytes=archive,plannedPeakAdditionalBytes=peak,
                observedFreeBytes=free,maxFiles=MAX_FILES,maxPathBytes=MAX_PATH_BYTES,admissionEligible=False)

def inventory(root):
    root=Path(root);require(root.is_dir() and root.resolve()==root and not root.is_symlink(),'ordinary evidence root')
    count=total=0
    for directory,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            path=Path(directory)/name;info=path.lstat()
            require(not stat.S_ISLNK(info.st_mode),'linked evidence member')
            relative=str(path.relative_to(root));require(len(relative.encode())<=MAX_PATH_BYTES,'bounded archive path')
            if stat.S_ISDIR(info.st_mode):continue
            require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,'ordinary single-link evidence file')
            count+=1;total+=info.st_size
            require(count<=MAX_FILES and total<=MAX_EVIDENCE,'inclusive evidence budget exceeded')
    return dict(schema='p1-direct-inclusive-storage-inventory-v1',files=count,evidenceBytes=total,
                archiveUpperBoundBytes=total+ARCHIVE_OVERHEAD,archiveLimitBytes=4*GIB,
                includesEveryEvidenceFile=True,admissionEligible=False)
