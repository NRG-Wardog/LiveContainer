"""One reviewed direct timeout case on an exact-owned isolated CI simulator.

The outer existing budget.py must invoke this collector. This file is a local
integration draft until its inventory, workflow and runtime adapters are sealed.
"""
from pathlib import Path
from hashlib import sha256
import argparse,importlib.util,json,os,shutil,sys,uuid

EXPECTED_BASE_ADAPTERS=frozenset(['ci/p0/inputs-sidestore.json', 'ci/p0/native_gate.py', 'ci/p0/source_primitives.py', 'ci/p1/native_gate.py', 'ci/p1/preflight/README.md', 'ci/p1/preflight/analyze_capability.py', 'ci/p1/preflight/app.swift', 'ci/p1/preflight/boot_diagnostic.py', 'ci/p1/preflight/budget.py', 'ci/p1/preflight/capture.py', 'ci/p1/preflight/capture_prerequisites.py', 'ci/p1/preflight/capture_prerequisites.swift', 'ci/p1/preflight/cleanup_gate.py', 'ci/p1/preflight/decode.swift', 'ci/p1/preflight/fresh_device.py', 'ci/p1/preflight/full-recovery-baseline.json', 'ci/p1/preflight/launch_gate.py', 'ci/p1/preflight/minimal_gate.py', 'ci/p1/preflight/probe_pair.py', 'ci/p1/preflight/process_scope.py', 'ci/p1/preflight/protocol.py', 'ci/p1/preflight/request_reader_gate.py', 'ci/p1/preflight/request_reader_regression.swift', 'ci/p1/preflight/runner_ui_tests.swift', 'ci/p1/preflight/simctl_capture.py', 'ci/p1/preflight/simulator_cleanup.py', 'ci/p1/preflight/stall_diagnostic.py', 'ci/p1/preflight/test_boot_diagnostic.py', 'ci/p1/preflight/test_calibration_discovery.py', 'ci/p1/preflight/test_capability.py', 'ci/p1/preflight/test_capture_prerequisites.py', 'ci/p1/preflight/test_cleanup_gate.py', 'ci/p1/preflight/test_fresh_ui.py', 'ci/p1/preflight/test_full_recovery.py', 'ci/p1/preflight/test_install_observation.py', 'ci/p1/preflight/test_observation_snapshot.py', 'ci/p1/preflight/test_process_lifecycle.py', 'ci/p1/preflight/test_query_reuse.py', 'ci/p1/preflight/test_request_reader_gate.py', 'ci/p1/preflight/test_runner_source.py', 'ci/p1/preflight/test_screen_calibration.py', 'ci/p1/preflight/test_simctl_capture.py', 'ci/p1/preflight/test_simulator_cleanup.py', 'ci/p1/preflight/test_stall_diagnostic.py', 'ci/p1/preflight/test_stall_fix.py', 'ci/p1/preflight/test_stall_fresh.py', 'ci/p1/preflight/test_stall_probes.py', 'ci/p1/preflight/test_stall_receipts.py', 'ci/p1/preflight/test_structural_tabs.py', 'ci/p1/preflight/test_tablet_profile.py', 'ci/p1/preflight/test_window_bgra.py', 'ci/p1/preflight/test_window_capture.py', 'ci/p1/preflight/test_window_fixture.py', 'ci/p1/preflight/window_bgra.py', 'ci/p1/preflight/window_capture.py', 'ci/p1/preflight/window_capture.swift', 'ci/p1/preflight/window_fixture.swift', 'ci/p1/preflight/window_fixture_route.py', 'ci/p1/preflight/window_packet.py', 'ci/p1/probe/capture.py', 'ci/p1/video/README.md', 'ci/p1/video/analyze.py', 'ci/p1/video/app.swift', 'ci/p1/video/capture.py', 'ci/p1/video/decode.swift', 'ci/p1/video/exports.py', 'ci/p1/video/extract.py', 'ci/p1/video/host_build.py', 'ci/p1/video/intervals.py', 'ci/p1/video/layout_exports.py', 'ci/p1/video/package_evidence.py', 'ci/p1/video/recovery.swift', 'ci/p1/video/recovery_ui_tests.swift', 'ci/p1/video/test_analyze.py', 'ci/p1/video/test_capture.py', 'ci/p1/video/test_exports.py', 'ci/p1/video/test_extract.py', 'ci/p1/video/test_host_build.py', 'ci/p1/video/test_intervals.py', 'ci/p1/video/test_layout_capabilities.py', 'ci/p1/video/test_layout_exports.py', 'ci/p1/video/test_layout_observer_source.py', 'ci/p1/video/test_package_evidence.py', 'ci/p1/video/test_recovery_layout_source.py', 'ci/p1/video/test_strip.py', 'ci/p1/video/test_transport.py', 'ci/p1/video/test_v3_signin_screen_cleanup.py', 'ci/p1/video/transport.py', 'ci/p1/video/ui_tests.swift', 'prepare_candidate_inventory.py'])
EXPECTED_SOURCE={'commit': 'bd5d9d87af76bfce0553d358bb3c6d45cbbc806a', 'repository': 'https://github.com/NRG-Wardog/LiveContainer.git', 'tree': '4a84f4115cb0d95aa71c0be97d9ce4fdfb553fbc'}
EXPECTED_BUILDER={'commit': '7e5062114f3ba8c1fe1990389ae9a008ce4d8c1f', 'repository': 'https://github.com/NRG-Wardog/sidestore-auto-refresh.git', 'tree': '70c4bc332a925dd608d37f39e8803a13451add33'}
EXPECTED_SOURCE_SHA='cee763b4190e50f324c666b99e5b117d6468f83de7b8026514968d09aec0e70c'
EXPECTED_DIRECT_ADAPTERS=frozenset(['ci/p1/direct/README.md', 'ci/p1/direct/analysis/README.md', 'ci/p1/direct/analysis/evidence_joins.py', 'ci/p1/direct/analysis/fixtures/maintained_valid_png.json', 'ci/p1/direct/analysis/fixtures/maintained_valid_png.py', 'ci/p1/direct/analysis/test_timeout_case.py', 'ci/p1/direct/analysis/timeout_case.py', 'ci/p1/direct/capture/README.md', 'ci/p1/direct/capture/assemble.py', 'ci/p1/direct/capture/assembly-binding.json', 'ci/p1/direct/capture/build_main.py', 'ci/p1/direct/capture/build_sink.py', 'ci/p1/direct/capture/direct_capture.swift', 'ci/p1/direct/capture/direct_main.swift', 'ci/p1/direct/capture/direct_sink.swift', 'ci/p1/direct/capture/roi_capture.swift', 'ci/p1/direct/capture/session_io.swift', 'ci/p1/direct/capture/source-sha256.txt', 'ci/p1/direct/capture/test_main_source.py', 'ci/p1/direct/capture/test_session_io_source.py', 'ci/p1/direct/capture/test_shared_budget.py', 'ci/p1/direct/capture/test_sink_source.py', 'ci/p1/direct/capture/test_startup_diagnostic.py', 'ci/p1/direct/capture/test_window_resize_source.py', 'ci/p1/direct/capture/window_resize.swift', 'ci/p1/direct/clock/bound_clocks.py', 'ci/p1/direct/clock/direct_clock.py', 'ci/p1/direct/clock/direct_coverage.py', 'ci/p1/direct/clock/test_bound_clocks.py', 'ci/p1/direct/clock/test_direct_clock.py', 'ci/p1/direct/clock/test_direct_coverage.py', 'ci/p1/direct/entry.py', 'ci/p1/direct/fixture/README.md', 'ci/p1/direct/fixture/app.swift', 'ci/p1/direct/fixture/draw_receipts.py', 'ci/p1/direct/fixture/native-layout-39262135354.json', 'ci/p1/direct/fixture/registration.swift', 'ci/p1/direct/fixture/render_fixture.py', 'ci/p1/direct/fixture/source-binding.json', 'ci/p1/direct/fixture/test_draw_receipts.py', 'ci/p1/direct/fixture/test_native_layout.py', 'ci/p1/direct/fixture/test_render_fixture.py', 'ci/p1/direct/geometry/README.md', 'ci/p1/direct/geometry/direct_geometry.py', 'ci/p1/direct/geometry/test_direct_geometry.py', 'ci/p1/direct/geometry/test_raster_promotion.py', 'ci/p1/direct/handoff/README.md', 'ci/p1/direct/handoff/build_candidate.py', 'ci/p1/direct/handoff/handoff_contract.py', 'ci/p1/direct/handoff/method-delta.patch', 'ci/p1/direct/handoff/observer.swift', 'ci/p1/direct/handoff/source-binding.json', 'ci/p1/direct/handoff/test_handoff_contract.py', 'ci/p1/direct/handoff/test_source_delta.py', 'ci/p1/direct/handoff/ui_tests.swift', 'ci/p1/direct/host/CAPTURE_HANDOFF.md', 'ci/p1/direct/host/OFFLINE_ANALYSIS.md', 'ci/p1/direct/host/PROJECT_SETUP.md', 'ci/p1/direct/host/README.md', 'ci/p1/direct/host/artifact_budget.py', 'ci/p1/direct/host/capture_handoff.py', 'ci/p1/direct/host/case_budget.py', 'ci/p1/direct/host/fixture_channel.py', 'ci/p1/direct/host/journal.py', 'ci/p1/direct/host/native_case.py', 'ci/p1/direct/host/native_channels.py', 'ci/p1/direct/host/native_process.py', 'ci/p1/direct/host/native_runtime.py', 'ci/p1/direct/host/offline_analysis.py', 'ci/p1/direct/host/project_setup.py', 'ci/p1/direct/host/protocol_driver.py', 'ci/p1/direct/host/runner_recipe.py', 'ci/p1/direct/host/test_artifact_budget.py', 'ci/p1/direct/host/test_capture_handoff.py', 'ci/p1/direct/host/test_case_budget.py', 'ci/p1/direct/host/test_entry_staging.py', 'ci/p1/direct/host/test_fixture_channel.py', 'ci/p1/direct/host/test_journal.py', 'ci/p1/direct/host/test_native_case.py', 'ci/p1/direct/host/test_native_channels.py', 'ci/p1/direct/host/test_native_prepare.py', 'ci/p1/direct/host/test_native_process.py', 'ci/p1/direct/host/test_native_runtime.py', 'ci/p1/direct/host/test_offline_analysis.py', 'ci/p1/direct/host/test_project_setup.py', 'ci/p1/direct/host/test_protocol_driver.py', 'ci/p1/direct/host/test_runner_recipe.py', 'ci/p1/direct/pixels/REGISTRATION_BRIDGE.md', 'ci/p1/direct/pixels/build_independent_ocr.py', 'ci/p1/direct/pixels/control_ocr.swift', 'ci/p1/direct/pixels/independent_ocr.swift', 'ci/p1/direct/pixels/live_strip.py', 'ci/p1/direct/pixels/magenta_components.py', 'ci/p1/direct/pixels/packed_frames.py', 'ci/p1/direct/pixels/registration.py', 'ci/p1/direct/pixels/registration_bridge.py', 'ci/p1/direct/pixels/roi_bytes.py', 'ci/p1/direct/pixels/test_control_ocr_source.py', 'ci/p1/direct/pixels/test_geometry_bundle.py', 'ci/p1/direct/pixels/test_live_strip.py', 'ci/p1/direct/pixels/test_packed_frames.py', 'ci/p1/direct/pixels/test_registration.py', 'ci/p1/direct/pixels/test_registration_bridge.py', 'ci/p1/direct/pixels/test_retention_contract.py', 'ci/p1/direct/pixels/test_roi_bytes.py', 'ci/p1/direct/pixels/test_support_association.py', 'ci/p1/direct/protocol/lifetime.py', 'ci/p1/direct/protocol/test_lifetime.py', 'ci/p1/direct/protocol/test_transitions.py', 'ci/p1/direct/protocol/transitions.py', 'ci/p1/direct/registration-experiment/README.md', 'ci/p1/direct/registration-experiment/explore.py', 'ci/p1/direct/registration-experiment/inset_strip.py', 'ci/p1/direct/registration-experiment/magenta_components.py', 'ci/p1/direct/registration-experiment/test_experiment.py', 'ci/p1/direct/registration-experiment/tiny_features.py', 'ci/p1/direct/registration-experiment/whole_strip.py'])

EXPECTED_DIRECT_ADAPTERS |= {'ci/p1/direct/host/helper_sample.py', 'ci/p1/direct/host/test_helper_sample.py', 'ci/p1/direct/host/HELPER_SAMPLE.md'}

def require(ok,message):
    if not ok:raise ValueError(message)

def startup_observation(command,result,name,*argv,historical):
    """One bounded startup observation; original allowance remains diagnostic."""
    row=command(*argv,timeout=30,receipt=True)
    result.setdefault('startupObservations',{})[name]=row
    timing=row.get('wait_timing') or {}
    start=timing.get('command_started');end=timing.get('wait_finished')
    require(type(start) in (int,float) and type(end) in (int,float) and 0<=start<=end<float('inf'),'startup timing absent')
    row['historicalAllowanceSeconds']=historical
    row['historicalAllowanceExceeded']=end>start+historical
    launch=row.get('launch_receipt') or {}
    require(row.get('exit_code')==0 and row.get('writer_settled') is True and
            row.get('failure_type') is None and row.get('primary_error') is None and not row.get('cleanup_errors') and
            launch.get('state')=='pre-exec-observed' and launch.get('closed') is True and launch.get('eof') is True and
            launch.get('exec_failure') is None,'startup command failed or execution unresolved')
    return row['stdout'].strip()

def bootstrap(host,inputs,approved):
    raw=inputs.read_bytes();require(sha256(raw).hexdigest()==approved,'approved input bytes differ')
    def pairs(items):
        value={}
        for key,item in items:
            require(key not in value,'duplicate input key');value[key]=item
        return value
    data=json.loads(raw,object_pairs_hook=pairs)
    require(set(data)=={'schema','scope','livecontainer','builder','source_sha256','adapter_files'},'exact input schema')
    require(data['schema']=='p1-short-capability-inputs-v1' and data['scope']=='direct-timeout-feedback-only-no-admission','one direct scope')
    require(data['livecontainer']==EXPECTED_SOURCE and data['builder']==EXPECTED_BUILDER and data['source_sha256']==EXPECTED_SOURCE_SHA,'fixed production pins')
    require(EXPECTED_DIRECT_ADAPTERS and set(data['adapter_files'])==EXPECTED_BASE_ADAPTERS|EXPECTED_DIRECT_ADAPTERS,'fixed complete adapter inventory')
    for relative,digest in data['adapter_files'].items():
        path=host/relative
        require(type(digest) is str and len(digest)==64 and path.is_file() and path.resolve()==path and not path.is_symlink(),'ordinary exact adapter')
        require(path.stat().st_size<=16*1024*1024 and sha256(path.read_bytes()).hexdigest()==digest,'adapter hash differs before import')
    return data

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value);return value

def stage(host,work,manifest):
    """Copy only authenticated adapter bytes into the reviewed relative layout."""
    root=work/'runtime-source';root.mkdir()
    copied=[]
    for relative,digest in manifest['adapter_files'].items():
        require(type(relative) is str and not Path(relative).is_absolute() and '..' not in Path(relative).parts,'safe adapter relative path')
        source=host/relative
        require(source.is_file() and not source.is_symlink() and source.resolve()==source,'ordinary sealed source')
        raw=source.read_bytes();require(sha256(raw).hexdigest()==digest,'source changed before staging')
        if relative.startswith('ci/p1/direct/'):
            destination=root/'direct-feedback-local'/relative.removeprefix('ci/p1/direct/')
        else:destination=root/'window-capture-candidate'/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open('xb') as f:f.write(raw)
        require(sha256(destination.read_bytes()).hexdigest()==digest,'staged source mismatch')
        copied.append({'source':relative,'target':str(destination.relative_to(root)),'sha256':digest})
    return root,copied

def execute(host,work,output,inputs,approved):
    require(host.is_absolute() and host.resolve()==host and not host.is_symlink(),'canonical repository')
    manifest=bootstrap(host,inputs,approved)
    # The fixed adapter inventory is checked by the sealed maintained validator,
    # whose explicit direct scope/inventory extension is reviewed at freeze.
    preflight=host/'ci/p1/preflight';sys.path.insert(0,str(preflight))
    capture=module('capture',preflight/'capture.py');capture.validate(host,inputs,approved)
    require(manifest['scope']=='direct-timeout-feedback-only-no-admission','exact one-case scope')
    require(not work.exists() and not output.exists(),'fresh work/evidence required');work.mkdir(parents=True);output.mkdir(parents=True)
    staged,inventory=stage(host,work,manifest)
    local=staged/'direct-feedback-local';preserved=staged/'window-capture-candidate/ci/p1'
    for name,loaded in list(sys.modules.items()):
        filename=getattr(loaded,'__file__',None)
        if name!='__main__' and filename and Path(filename).is_absolute() and Path(filename).is_relative_to(host):
            del sys.modules[name]
    sys.path[:]=[item for item in sys.path if not (item and Path(item).is_absolute() and Path(item).is_relative_to(host))]
    # Executable imports now come from byte-verified staging; all source-bound
    # sibling paths match the previously reviewed local builders.
    sys.path[:0]=[str(local/name) for name in ('host','analysis','clock','protocol','pixels','geometry','handoff','fixture')]
    sys.path[:0]=[str(preserved/'preflight'),str(preserved/'video')]
    capture=module('capture',preserved/'preflight/capture.py')
    process_scope=sys.modules['process_scope']
    fresh=module('fresh_device',preserved/'preflight/fresh_device.py')
    window=module('window_capture',preserved/'preflight/window_capture.py')
    import project_setup,capture_handoff,native_runtime,native_case,direct_clock,registration_bridge,handoff_contract,offline_analysis,artifact_budget
    scope=process_scope.Scope(output,phone_ui=True)
    logs=output/'setup-commands';logs.mkdir();command=process_scope.Commands(scope,logs)
    result={'schema':'p1-direct-timeout-result-v1','scope':'single-timeout-direct-feedback-conditional',
            'collection_complete':False,'capabilities_passed':False,'conditionalTimeoutEvidence':False,
            'feedback_lifetime_established':False,'input_overlap_established':False,'admissionEligible':False,'errors':[]}
    runtime=None;case=None
    try:
        capture.write(output/'staged-source-inventory.json',inventory);shutil.copy2(inputs,output/'approved-inputs.json')
        result['github']={k:os.environ.get(k) for k in ('GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REPOSITORY')}
        result['workflowSHA256']=capture.sha(host/'.github/workflows/p1-native-candidate.yml')
        require(os.environ.get('ImageVersion')=='20261013.0424.1','pinned image differs')
        version=startup_observation(command,result,'xcode-version','xcodebuild','-version',historical=5);require(version=='Xcode 26.4.1\nBuild version 17E202','pinned toolchain differs')
        result['xcodeVersion']=version
        sdk=startup_observation(command,result,'sdk-path','xcrun','--sdk','macosx','--show-sdk-path',historical=10)
        header=json.loads(command(sys.executable,'-B',preserved/'preflight/capture_prerequisites.py','--header-only',sdk,timeout=5))
        require(header['headerSHA256']=='025ce72289d842191571495dfc98ba1f5fec0c00b77ed598ab7cc765a649e9aa','pinned timestamp documentation differs');result['sdk']=header
        prerequisite=work/'capture-prerequisites'
        command('xcrun','swiftc',preserved/'preflight/capture_prerequisites.swift','-o',prerequisite,timeout=30)
        check=json.loads(startup_observation(command,result,'capture-prerequisites',prerequisite,historical=10))
        require(window.capture_prerequisites.validate_result(check) and check['screenCapturePreflight'] and
                check['simulatorProcessCount']==0 and check['simulatorOnScreenWindowCount']==0,'permission or GUI prerequisite absent')
        result['prerequisites']=check
        helper=work/'direct-capture';source=local/'capture/direct_capture.swift'
        host_sources=capture_handoff.source_hashes();capture.write(output/'helper-host-source-hashes.json',host_sources)
        receipt=command('xcrun','swiftc','-swift-version','5','-parse-as-library',source,'-o',helper,timeout=60,receipt=True)
        compiled=capture_handoff.bind_compilation(source,helper,json.dumps(receipt,sort_keys=True,separators=(',',':')).encode(),
                    scope=scope,expected_source_sha256=host_sources['direct-feedback-local/capture/direct_capture.swift'])
        capture.write(output/'helper-compile.json',receipt)
        accessibility=json.loads(startup_observation(command,result,'accessibility-prerequisite',helper,'--check-existing-accessibility',historical=10))
        capture.write(output/'accessibility-prerequisite.json',accessibility)
        result['accessibilityPrerequisite']=accessibility
        require(set(accessibility)=={'schema','existingAccessibilityTrust','permissionRequested','windowsEnumerated','pixelsCaptured','admissionEligible'} and
                accessibility['schema']=='p1-direct-accessibility-prerequisite-v1' and
                accessibility['existingAccessibilityTrust'] is True and
                all(accessibility[key] is False for key in ('permissionRequested','windowsEnumerated','pixelsCaptured','admissionEligible')),
                'existing accessibility trust required; permission was not requested')
        builder=work/'builder';live=work/'LiveContainer'
        capture.base.acquire(builder,capture.BUILDER,command);capture.base.acquire(live,capture.SOURCE,command)
        before={'LiveContainer':capture.base.checkout_proof(live,capture.SOURCE,command),'builder':capture.base.checkout_proof(builder,capture.BUILDER,command)}
        capture.write(output/'source-before.json',before)
        session=uuid.uuid4().hex
        runtime=native_runtime.Runtime(scope=scope,process_scope=process_scope,capture=capture,window_capture=window,
                    fresh_device=fresh,project_setup=project_setup,video=capture.video,local=local,work=work,output=output,
                    source=live/capture.base.SHELL,builder=builder,helper=helper,session=session,clock=direct_clock,
                    bridge=registration_bridge,handoff=handoff_contract)
        runtime.compiled=compiled;runtime.capture_module=capture_handoff
        runtime.prepare_sample()
        case=native_case.Case(session,runtime);result['case']=case.run()
        result['analysis']=offline_analysis.run(runtime,case.context)
        after={'LiveContainer':capture.base.checkout_proof(live,capture.SOURCE,command),'builder':capture.base.checkout_proof(builder,capture.BUILDER,command)}
        capture.write(output/'source-after.json',after);require(before==after,'production source changed')
        result['collection_complete']=True
        result['conditionalTimeoutEvidence']=result['analysis'].get('completed') is True and result['analysis'].get('conditionalTimeoutResult',{}).get('conditionalTimeoutEvidence') is True
    except Exception as error:result['errors'].append(process_scope.error_info(error))
    finally:
        # Case owns every acquired resource and its failure cleanup. Scope.close
        # and outer budget.py independently reject unresolved creation/writers.
        if runtime is not None:
            try:runtime.finish_sample(max(0,min(3,scope.cleanup_deadline-__import__('time').monotonic())))
            except Exception as error:result['errors'].append(process_scope.error_info(error))
        try:scope.close()
        except Exception as error:result['errors'].append(process_scope.error_info(error))
        if runtime is not None:
            try:runtime.finish_sample(max(0,min(3,scope.cleanup_deadline-__import__('time').monotonic())))
            except Exception as error:result['errors'].append(process_scope.error_info(error))
        if result['errors']:result['collection_complete']=False;result['conditionalTimeoutEvidence']=False
        capture.write(output/'capability-result.json',result)
        capture.write(output/'direct-timeout-result.json',result)
        try:
            storage=artifact_budget.inventory(output);capture.write(output/'inclusive-storage-final.json',storage)
            artifact_budget.inventory(output)
        except Exception as error:
            result['errors'].append(process_scope.error_info(error));result['collection_complete']=False;result['conditionalTimeoutEvidence']=False
            capture.write(output/'capability-result.json',result);capture.write(output/'direct-timeout-result.json',result)
    return result['collection_complete'] and result['conditionalTimeoutEvidence']

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--host-root',type=Path,required=True);parser.add_argument('--work',type=Path)
    parser.add_argument('--evidence',type=Path);parser.add_argument('--inputs',type=Path,required=True);parser.add_argument('--approved-inputs-sha256',required=True)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--verify-only',action='store_true');mode.add_argument('--stage-only',action='store_true')
    a=parser.parse_args();host=a.host_root.resolve()
    if a.verify_only:
        bootstrap(host,a.inputs,a.approved_inputs_sha256);raise SystemExit(0)
    if a.stage_only:
        require(a.work is not None and not a.work.exists(),'fresh staging work required')
        manifest=bootstrap(host,a.inputs,a.approved_inputs_sha256);a.work.mkdir(parents=True);stage(host,a.work,manifest);raise SystemExit(0)
    require(a.work is not None and a.evidence is not None,'collector work/evidence required')
    raise SystemExit(0 if execute(host,a.work,a.evidence,a.inputs,a.approved_inputs_sha256) else 1)
