"""Exact retained-byte joins. Execution/source ownership remains mandatory upstream."""
from hashlib import sha256
from pathlib import Path
import importlib.util
import json
import re
import struct
import zlib

VIDEO=Path(__file__).resolve().parents[2]/'window-capture-candidate/ci/p1/video'
EXPORTS_SHA='514800f4b2031fca32030e94b3853dd6d0e3aa0e125d60df1fde94d7cd5c891b'
source=VIDEO/'exports.py'
if sha256(source.read_bytes()).hexdigest()!=EXPORTS_SHA:raise ValueError('maintained export source drift')
spec=importlib.util.spec_from_file_location('direct_evidence_exports',source)
exports=importlib.util.module_from_spec(spec);spec.loader.exec_module(exports)
PNG_MAGIC=b'\x89PNG\r\n\x1a\n'


def require(ok,message):
    if not ok:raise ValueError(message)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def parse(raw):
    require(type(raw) is bytes and 0<len(raw)<=8*1024*1024,'bounded retained JSON')
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'duplicate JSON key');result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


# Exact maintained bounded PNG validator, including CRC and decoded scanlines.
def valid_png(data: bytes) -> bool:
    """Check screenshot chunks AND bounded decoded pixel scanlines (including Adam7)."""
    if not data.startswith(PNG_MAGIC):
        return False
    offset = 8
    header = None
    compressed = bytearray()
    palette = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            return False
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[end - 4:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            return False
        if header is None:
            if kind != b"IHDR" or length != 13:
                return False
            header = struct.unpack(">IIBBBBB", payload)
            width, height, depth, color, compression, filtering, interlace = header
            allowed = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if (not 100 <= width <= 8192 or not 100 <= height <= 8192 or
                    depth not in allowed.get(color, set()) or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                return False
        elif kind == b"IHDR":
            return False
        if kind == b"PLTE":
            palette = 0 < length <= 768 and length % 3 == 0
        if kind == b"IDAT":
            compressed.extend(payload)
        if kind == b"IEND":
            if not header or not compressed or length != 0 or end != len(data):
                return False
            width, height, depth, color, _, _, interlace = header
            if color == 3 and not palette:
                return False
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
            passes = [(0, 0, 1, 1)] if interlace == 0 else [
                (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
                (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
            rows = []
            for x, y, dx, dy in passes:
                pass_width = max(0, (width - x + dx - 1) // dx)
                pass_height = max(0, (height - y + dy - 1) // dy)
                if pass_width and pass_height:
                    rows.extend([1 + (pass_width * channels * depth + 7) // 8] * pass_height)
            expected = sum(rows)
            if expected > 128 * 1024 * 1024:
                return False
            try:
                decoder = zlib.decompressobj()
                pixels = decoder.decompress(compressed, expected + 1)
                if (len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
                    return False
            except zlib.error:
                return False
            position = 0
            for row_bytes in rows:
                if pixels[position] > 4:
                    return False
                position += row_bytes
            return True
        offset = end
    return False

def ocr_manifest(records,session):
    """Identical wire manifest to packed_frames.ocr_input, from verified rows.

    Caller must have obtained all rows from packed_frames.inspect with the final
    stream identity. This function does not replace that raw-byte validation.
    """
    require(type(session) is str and re.fullmatch('[0-9a-f]{32}',session),'OCR session')
    frames=[]
    for row in records:
        if not row['newFrame']:continue
        control=row['regions'][0]
        require(control.get('role')=='control' and type(control.get('offset')) is int and control['offset']==0,'fixed first control ROI')
        rect=control['rectangle']
        require(type(rect) is list and len(rect)==4 and all(type(v) is int for v in rect) and min(rect)>=0 and min(rect[2:])>0,'control rectangle')
        require(type(row['index']) is int and row['packedPixels']==f"frame-{row['index']:05d}.rois.bgra",'native OCR frame identity')
        frames.append({'record':row['index']+1,'file':row['packedPixels'],
                       'packedSHA256':row['packedSHA256'],'offset':control['offset'],
                       'width':rect[2],'height':rect[3],'controlSHA256':control['sha256']})
    require(2<=len(frames)<=6000,'OCR complete inventory')
    return canonical({'schema':'p1-direct-control-ocr-input-v1','session':session,'frames':frames})


def screenshot_exports(evidence,device,input_receipt):
    """Recheck exact XCTest association, actual PNG bytes, and runner ordering.

    The runner uptime is compared only to its own input/screenshot receipts.
    No runner/app/host clock equivalence or screenshot presentation time exists.
    Returned PNG hashes must be joined to the retained decoder output by caller.
    """
    require(type(evidence) is dict and set(evidence)=={'summaryBytes','testsBytes','manifestBytes','files'},'raw screenshot export evidence')
    files=evidence['files']
    require(type(files) is dict and 1<=len(files)<=64 and 'manifest.json' not in files,'bounded attachment inventory')
    for name,raw in files.items():
        require(type(name) is str and name not in ('','.','..') and '/' not in name and '\\' not in name and '\x00' not in name,'attachment leaf')
        require(type(raw) is bytes and 0<len(raw)<=32*1024*1024,'bounded attachment bytes')
    require(sum(map(len,files.values()))<=128*1024*1024,'bounded attachment aggregate')
    manifest=parse(evidence['manifestBytes'])
    require(type(manifest) is list and len(manifest)==1 and type(manifest[0].get('attachments')) is list,'one attachment manifest')
    require({r.get('exportedFileName') for r in manifest[0]['attachments']}==set(files),'complete exported attachment bytes')
    class Retained:
        def __init__(self,name,raw):self.name=name;self.raw=raw
        def read_bytes(self):return self.raw
        def __str__(self):return self.name
    def ordinary(root,name):
        if name=='manifest.json':return Retained(name,evidence['manifestBytes'])
        require(name in files,'missing retained attachment');return Retained(name,files[name])
    controls,inputs,paths=exports.verify(None,parse(evidence['summaryBytes']),parse(evidence['testsBytes']),
                                       'timeout',device,lambda file:parse(file.read_bytes()),ordinary,valid_png)
    require(canonical(inputs)==canonical(input_receipt),'exported input receipt differs')
    rows=manifest[0]['attachments']
    def attached(name):
        matching=[r for r in rows if (r.get('suggestedHumanReadableName',r.get('attachmentName'))==name or
                  r.get('suggestedHumanReadableName',r.get('attachmentName','')).startswith(name+'_'))]
        require(len(matching)==1,'missing/duplicate screenshot clock attachment')
        return parse(files[matching[0]['exportedFileName']])
    clocks={}
    for phase in ('before','after'):
        name='video-timeout-'+phase
        row=attached(name+'-clock')
        require(set(row)=={'name','beforeUptime','afterUptime','clock'} and row['name']==name and
                row['clock']=='XCTest-process-systemUptime; not assumed equal to app clock','screenshot clock identity')
        lo,hi=row['beforeUptime'],row['afterUptime']
        require(exports.finite(lo) and exports.finite(hi) and 0<lo<=hi,'screenshot runner clock')
        clocks[phase]=(lo,hi)
    require(clocks['before'][1]<=inputs['baselineBefore'] and inputs['firstAfter']<=clocks['after'][0],'screenshot/input runner ordering')
    require(files[paths['before']]!=files[paths['after']],'reused independent PNG bytes')
    return {phase:{'exportedFileName':name,'pngSHA256':sha256(files[name]).hexdigest(),
                   'pixelSize':list(struct.unpack('>II',files[name][16:24]))}
            for phase,name in paths.items()}
