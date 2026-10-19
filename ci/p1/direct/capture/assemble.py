"""Assemble the local Swift draft; this does not compile or execute it."""
from pathlib import Path
import hashlib,json
from build_sink import SOURCE,build as sink_build
from build_main import build as main_build

HERE=Path(__file__).parent
READER_SOURCE=SOURCE.with_name('runner_ui_tests.swift')
READER_SHA256='0e6504ffd4b964822f2b87a4cb5be89e99e1565882d5935a8dd18ae078efd131'

def sha(data):return hashlib.sha256(data).hexdigest()

def assemble():
    source=SOURCE.read_text();expected=(HERE/'source-sha256.txt').read_text().strip()
    if sha(source.encode())!=expected:raise ValueError('reviewed native source drift')
    reader=READER_SOURCE.read_text()
    if sha(reader.encode())!=READER_SHA256:raise ValueError('reviewed reader source drift')
    a=reader.index('// P1_REQUEST_READER_BEGIN');b=reader.index('// P1_REQUEST_READER_END')+len('// P1_REQUEST_READER_END')
    transport=reader[a:b]
    prefix=source[:source.index('final class Sink:')]
    pieces=[prefix,transport,(HERE/'roi_capture.swift').read_text(),(HERE/'session_io.swift').read_text(),(HERE/'window_resize.swift').read_text(),sink_build(source,expected),main_build(source,expected)]
    output='\n\n'.join(pieces)
    (HERE/'direct_capture.swift').write_text(output)
    (HERE/'assembly-binding.json').write_text(json.dumps({'schema':'p1-direct-capture-local-assembly-v1',
        'nativeSourceSHA256':expected,'readerSourceSHA256':sha(reader.encode()),'readerBlockSHA256':sha(transport.encode()),
        'assembledSHA256':sha(output.encode()),'nativeCompiled':False,'nativeExecuted':False,'admissionEligible':False},sort_keys=True,indent=2)+'\n')
    return output

if __name__=='__main__':assemble()
