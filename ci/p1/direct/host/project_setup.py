"""Concrete local project generation, reusing the sealed video prepare method.

No native execution or publication. Explicit paths support relocated staging;
source/checkout ownership and expected hash-map approval remain caller duties.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import sys

CAPTURE_SHA256 = '4f2d23438100bf2baa0805623fbb534e72588798d34d6c7245754786694b802d'
PREPARE_SHA256 = '86accb4a15c7ac1b9370eef2bdef2c20fdf10a3340a45cfc1588df27220fa584'
VIDEO_FILES = ('capture.py','extract.py','transport.py','analyze.py','exports.py','layout_exports.py','intervals.py',
               'app.swift','ui_tests.swift','recovery.swift','recovery_ui_tests.swift')
LOCAL_FILES = ('host/project_setup.py','fixture/render_fixture.py','fixture/registration.swift','fixture/app.swift',
               'fixture/source-binding.json','handoff/build_candidate.py','handoff/observer.swift',
               'handoff/ui_tests.swift','handoff/source-binding.json')
IMPORT_NAMES = ('extract','transport','analyze','exports','layout_exports','intervals')


def require(value, message):
    if not value: raise ValueError(message)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def ordinary(path, *, directory=False):
    path=Path(path)
    require(path.is_absolute() and path.resolve()==path and not path.is_symlink(), 'canonical unlinked input path required')
    require(path.is_dir() if directory else path.is_file(), 'missing source-bound input')
    return path


def source_hashes(source,builder,*,video_dir,preflight_dir,local_dir):
    source=ordinary(source);builder=ordinary(builder,directory=True)
    video=ordinary(video_dir,directory=True);preflight=ordinary(preflight_dir,directory=True);local=ordinary(local_dir,directory=True)
    require(ordinary(local/'host/project_setup.py')==Path(__file__).resolve(), 'running project adapter differs from supplied local source')
    files={**{'video/'+name:ordinary(video/name) for name in VIDEO_FILES},
           'probe/capture.py':ordinary(video.parent/'probe/capture.py'),
           'preflight/runner_ui_tests.swift':ordinary(preflight/'runner_ui_tests.swift'),
           'preflight/window_fixture.swift':ordinary(preflight/'window_fixture.swift'),
           **{'local/'+name:ordinary(local/name) for name in LOCAL_FILES},
           'production/V3UnifiedShell.swift':source}
    support=source.parents[2]/'SideStoreSupport/SideStore.swift'
    if support.exists():files['production/SideStore.swift']=ordinary(support)
    for relative in ('scripts/run_p0_signin_rendering.py','tests/fixtures/p0_signin_app.swift'):
        files['builder/'+relative]=ordinary(builder/relative)
    for relative in ('scripts/templates','tests/fixtures/p0_signin_project'):
        root=ordinary(builder/relative,directory=True)
        members=list(root.rglob('*'))
        require(len(members)<=512, 'bounded builder template/project inventory required')
        for path in members:
            require(not path.is_symlink(), 'linked builder member')
            if path.is_file():files['builder/'+str(path.relative_to(builder))]=ordinary(path)
    return {name:digest(path) for name,path in sorted(files.items())}


def _module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);bytecode=sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode=True;spec.loader.exec_module(module)
    finally:sys.dont_write_bytecode=bytecode
    return module


@contextmanager
def _video_module(video):
    # The original module imports short names. Isolate those names for this
    # serial setup operation, preventing accidental use of preloaded siblings.
    missing=object();saved={name:sys.modules.get(name,missing) for name in IMPORT_NAMES}
    path=list(sys.path);bytecode=sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode=True;sys.path.insert(0,str(video))
        for name in IMPORT_NAMES:sys.modules.pop(name,None)
        module=_module('p1_direct_preserved_video_capture',video/'capture.py')
        for name in IMPORT_NAMES:
            require(Path(sys.modules[name].__file__).resolve()==video/(name+'.py'), 'wrong imported video dependency')
        require(Path(module.base.__file__).resolve()==video.parent/'probe/capture.py', 'wrong preserved base module')
        yield module
    finally:
        sys.path[:]=path;sys.dont_write_bytecode=bytecode
        for name,value in saved.items():
            if value is missing:sys.modules.pop(name,None)
            else:sys.modules[name]=value


def _generated_fragments(video,preflight,local):
    fixture=_module('p1_direct_fixture_generator',local/'fixture/render_fixture.py')
    observer=_module('p1_direct_observer_generator',local/'handoff/build_candidate.py')
    original_app=(video/'app.swift').read_text();original_ui=(video/'ui_tests.swift').read_text()
    app=(local/'fixture/app.swift').read_text();ui=(local/'handoff/ui_tests.swift').read_text()
    require(app==fixture.render(original_app,(preflight/'window_fixture.swift').read_text(),
                                (local/'fixture/registration.swift').read_text()), 'generated fixture source differs')
    require(digest(video/'ui_tests.swift')==observer.ORIGINAL_SHA and
            digest(preflight/'runner_ui_tests.swift')==observer.PREFLIGHT_SHA, 'sealed observer source differs')
    preflight_text=(preflight/'runner_ui_tests.swift').read_text()
    primitives=preflight_text[preflight_text.index('private struct P1CapabilityError:'):
                             preflight_text.index('private struct P1CapabilityCommand:')]
    require(sha256(primitives.encode()).hexdigest()==observer.PRIMITIVES_SHA, 'reviewed observer primitive drift')
    text=ui
    for block in (observer.PRIMITIVES_BEGIN+primitives+observer.PRIMITIVES_END+'\n',
                  observer.OBSERVER_BEGIN+(local/'handoff/observer.swift').read_text()+observer.OBSERVER_END+'\n',
                  observer.IMPORTS,observer.START,observer.HOOK):
        require(text.count(block)==1, 'observer source reconstruction boundary differs')
        text=text.replace(block,'',1)
    require(text.count(observer.DIRECT_LAUNCH)==1, 'observer launch boundary differs')
    text=text.replace(observer.DIRECT_LAUNCH,observer.LAUNCH,1)
    require(text==original_ui and ui.split(observer.BASELINE,1)[1]==original_ui.split(observer.BASELINE,1)[1],
            'original production actions/delays/source do not reconstruct')
    for folder,candidate in (('fixture',app),('handoff',ui)):
        binding=json.loads((local/folder/'source-binding.json').read_text())
        require(binding['candidateSHA256']==sha256(candidate.encode()).hexdigest() and
                binding['nativeCompiled'] is False and binding['nativeExecuted'] is False and
                binding['admissionEligible'] is False, 'unbound generated candidate')
    return original_app,original_ui,app,ui


@dataclass(frozen=True)
class PreparedProject:
    project: Path
    renderer: object
    source_identity_bytes: bytes
    receipt_bytes: bytes


def prepare(source,builder,build,output,*,video_dir,preflight_dir,local_dir,expected_sources):
    """Generate once into fresh paths; no xcodebuild, simulator, Git, or network.

    Caller must serialize preparation: legacy video imports use short module
    names. Explicit video directory retains its original sibling probe directory.
    Neither preflight nor local directory is inferred from workspace ancestry.
    """
    source=Path(source);builder=Path(builder);build=Path(build);output=Path(output)
    video=Path(video_dir);preflight=Path(preflight_dir);local=Path(local_dir)
    observed=source_hashes(source,builder,video_dir=video,preflight_dir=preflight,local_dir=local)
    require(type(expected_sources) is dict and expected_sources==observed, 'owned expected source binding differs')
    require(observed['video/capture.py']==CAPTURE_SHA256, 'reviewed video capture source drift')
    for target in (build,output):
        require(target.is_absolute() and not target.exists() and not target.is_symlink() and
                target.parent.is_dir() and target.parent.resolve()==target.parent, 'fresh canonical preparation directory required')
    require(build!=output and build not in output.parents and output not in build.parents, 'preparation paths must be separate')
    original_app,original_ui,app_fragment,ui_fragment=_generated_fragments(video,preflight,local)
    output.mkdir()
    with _video_module(video) as legacy:
        import ast
        source_text=(video/'capture.py').read_text()
        node=next(n for n in ast.parse(source_text).body if isinstance(n,ast.FunctionDef) and n.name=='prepare')
        require(sha256(ast.get_source_segment(source_text,node).encode()).hexdigest()==PREPARE_SHA256,
                'exact reused video prepare method drift')
        project,renderer=legacy.prepare(source,builder,build,output)
        identity_path=output/'source-identity.json';original_identity=identity_path.read_bytes()
        (output/'preserved-source-identity.json').write_bytes(original_identity)
        identity=json.loads(original_identity)
        targets=build/'Sources';before={p.name:p.read_bytes() for p in targets.iterdir() if p.is_file()}
        require(set(before)==set(p.name for p in (output/'sources').iterdir() if p.is_file()), 'base source-copy inventory differs')
        for name,old,new in (('p0_signin_app.swift',original_app,app_fragment),('p0_signin_ui_tests.swift',original_ui,ui_fragment)):
            original=before[name].decode();require(original.count(old)==1,'original video fixture boundary differs')
            changed=original.replace(old,new,1)
            require(changed.count(new)==1 and changed.replace(new,old,1)==original, 'fixture replacement is not reversible')
            (targets/name).write_text(changed);(output/'sources'/name).write_text(changed)
        after={p.name:p.read_bytes() for p in targets.iterdir() if p.is_file()}
        require(set(before)==set(after), 'generated source inventory changed')
        require(all(before[name]==after[name] for name in before if name not in ('p0_signin_app.swift','p0_signin_ui_tests.swift')),
                'production extraction changed outside declared fixture fragments')
        require(all((output/'sources'/name).read_bytes()==data for name,data in after.items()), 'retained generated-source copy differs')
        # The complete recovery fragments are untouched, not renamed or dropped.
        require(after['p0_signin_ui_tests.swift'].decode().endswith('\n'+(video/'recovery_ui_tests.swift').read_text()),
                'preserved recovery test methods differ')
        identity.update(generated_sources_sha256={name:sha256(data).hexdigest() for name,data in after.items()},
                        preserved_source_identity_sha256=sha256(original_identity).hexdigest(),
                        base_instrumentation=identity['instrumentation'],
                        instrumentation='Test-only observer instrumentation: static four-packet/four-feature overlay, eight draw receipts, session launch argument and bounded pre-baseline XCTest handoff; production extracted code/actions/delays and recovery methods preserved',
                        observer_instrumented=True,production_source_instrumented=False,
                        scope='direct-feedback timeout preparation only; no native execution',
                        full_matrix_complete=False,nativeCompiled=False,nativeExecuted=False,admissionEligible=False)
        identity_bytes=canonical(identity);identity_path.write_bytes(identity_bytes)
    require(source_hashes(source,builder,video_dir=video,preflight_dir=preflight,local_dir=local)==observed,
            'input source changed during project preparation')
    receipt=dict(schema='p1-direct-project-preparation-v1',sourceHashes=observed,
                 originalVideoPrepareSHA256=PREPARE_SHA256,sourceIdentitySHA256=sha256(identity_bytes).hexdigest(),
                 replacedFragments=['video/app.swift','video/ui_tests.swift'],
                 productionExtractionPreserved=True,recoveryMethodsPreserved=True,
                 originalActionsAndDelaysPreserved=True,observerInstrumented=True,
                 nativeCompiled=False,nativeExecuted=False,admissionEligible=False)
    receipt_bytes=canonical(receipt);(output/'direct-project-preparation.json').write_bytes(receipt_bytes)
    return PreparedProject(project,renderer,identity_bytes,receipt_bytes)
