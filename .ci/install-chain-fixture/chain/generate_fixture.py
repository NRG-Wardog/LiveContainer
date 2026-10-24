#!/usr/bin/env python3
"""Actual delivered source projection; no Swift/native execution in this generator."""
from pathlib import Path
import argparse, hashlib, json, re
HERE=Path(__file__).parent
CASES=['input_owned_url_and_identity','input_rejects_noncanonical_token','context_default_values','install_sequence_and_weights','default_chain_contract','failure_stops_before_next_step','post_install_failure_remains_failure']
def block(s,a):
 assert s.count(a)==1,(a,s.count(a))
 start=s.index(a);i=s.index('{',start);depth=1;j=i+1
 while depth:
  depth+=(s[j]=='{')-(s[j]=='}');j+=1
 return s[start:j]
def generate(root,out):
 paths={
 'service':root/'SideStore/AltStore/AppDelegate.swift',
 'app_protocol':root/'SideStore/AltStore/Core/Protocols/AppProtocol.swift',
 'app_operation':root/'SideStore/SideStore/Core/Operations/AppOperation.swift',
 'context':root/'SideStore/SideStore/Core/Operations/OperationContexts.swift',
 'definition':root/'SideStore/SideStore/Core/Operations/OperationStepDefinition.swift',
 'steps':root/'SideStore/SideStore/Core/Operations/OperationStep.swift',
 'runner':root/'SideStore/SideStore/Core/Operations/PipelineRunner.swift',
 'executor':root/'SideStore/SideStore/Core/Operations/PipelineExecutor.swift'}
 s={k:p.read_text() for k,p in paths.items()}
 install=re.search(r'static let install: \[PipelineExecutionStep\] = \[(.*?)\n    \]',s['definition'],re.S)[1]
 names=re.findall(r'PipelineExecutionStep\(\.(\w+)',install);assert len(names)==len(set(names))==20
 step=block(s['steps'],'enum PipelineStep:').split('    fileprivate static let stepMap:',1)[0]+'}\n'
 op=block(s['app_operation'],'enum AppOperation:')
 protocol=block(s['app_protocol'],'public protocol AppProtocol')+'\n'+block(s['app_protocol'],'public struct AnyApp:')
 context='\n'.join(block(s['context'],a) for a in ['enum AlternateIconMode {','fileprivate struct OperationStepItem {','protocol WeightedOperationContext:','class OperationContext:','class PipelineOperationContext:','class InstallAppOperationContext:'])
 definition=block(s['definition'],'struct PipelineExecutionStep:')+'\n'+block(s['definition'],'struct PipelineStepDefinition {')
 # Preserve complete runner preparation and loop. Noninstall operation arms are excluded
 # only from executeStep; diagnostics catch/log/phase reporting are outside this contract.
 run=block(s['runner'],'    private func performPipeline(')
 loop=block(s['executor'],'    func executePipeline(')
 switch=s['executor'].split('            switch step {',1)[1].split('\n        } catch {',1)[0]
 boundaries=list(re.finditer(r'^            case \.(\w+):',switch,re.M))
 arms={}
 for i,m in enumerate(boundaries):
  end=boundaries[i+1].start() if i+1<len(boundaries) else switch.rfind('            }')
  arms[m[1]]=switch[m.start():end]
 assert all(n in arms for n in names)
 excluded=[n for n in arms if n not in names];assert len(excluded)==11
 projected='''    private func executeStep(_ step: PipelineStep, context: InstallAppOperationContext,
        appOperation: AppOperation, group: RefreshGroup, downloadingApp: AppProtocol,
        permissionsMode: PermissionReviewMode, progress: Progress?) async throws -> InstalledApp? {
        var result: Any? = "()"
        var loggerType: any OperationLogging.Type
        switch step {
'''+''.join(arms[n] for n in names)+'''        default: throw ProbeFailure.excludedStep
        }
    }
'''
 # Actual resolver including catalog/remote rejection boundary doubles.
 resolve=block(s['service'],'    private func resolveInstallTarget(')
 parity=block(s['service'],'enum V3InstallInputRoute:')+'\n'+block(s['service'],'enum V3InstallPipelineParity {')
 canonical=block(s['service'],'    static func canonicalToken(_ token: String) throws -> String {')
 source=(HERE/'Doubles.swift').read_text()+'\n'+protocol+'\n'+op+'\nprotocol OperationStep: Equatable, Hashable {}\n'+step+'\n'+definition+'\n'+context+'\n'+parity
 source+='\nextension V3IPAStaging {\n'+canonical+'\n}\n'
 source+='\nfinal class InputResolver {\n'+resolve+'\nfunc resolve(_ token: String) async throws -> AppProtocol {\nlet resolved = try await resolveInstallTarget(id: "fixture", kind: "installSharedIPA", target: token)\nif case .app(let app) = resolved { return app }; throw ProbeFailure.excludedStep\n}\nfunc ipaTarget(url: URL, scoped: Bool, sessionID: String) async throws -> InstallTarget { throw ProbeFailure.excludedStep }\n}\n'
 source+='\nfinal class PipelineExecutor { static let shared = PipelineExecutor()\n'+loop+'\n'+projected+'\n}\n'
 source+='\nfinal class FixtureRunner {\nlet progress = PipelineProgress()\nlet defaultEntitlements: [ALTEntitlement: any Sendable] = [.fixture: true]\n'+run+'\nfunc run(_ app: AppProtocol) async throws -> InstalledApp {\nlet built = V3InstallPipelineParity.makeOperation(route: .localIPA, app) { AppOperation.install($0) }\nreturn try await performPipeline(for: built.operation, handler: ProbeHandler(), group: RefreshGroup())\n}\n}\n'
 source+=(HERE/'Operations.swift').read_text()+'\n'+(HERE/'Cases.swift').read_text()
 variants=[{'file':'InstallChain.swift','group':'chain','case_names':CASES,'expected_failed_names':[]}]
 mutations=[('MissingTarget.swift','context.targetAppBundle = downloadedAppBundle','// negative: target assignment removed',['default_chain_contract','failure_stops_before_next_step','post_install_failure_remains_failure']),
 ('MissingProfiles.swift','context.provisioningProfiles = profiles','// negative: profile assignment removed',['default_chain_contract','post_install_failure_remains_failure']),
 ('MissingInputURL.swift','url: file, storeApp: nil)','url: nil, storeApp: nil)',['input_owned_url_and_identity','default_chain_contract','failure_stops_before_next_step','post_install_failure_remains_failure']),
 ]
 array=re.search(r'    static let install: \[PipelineExecutionStep\] = \[(.*?)\n    \]',source,re.S)[0]
 omitted=re.sub(r'^        PipelineExecutionStep\(\.installApp,.*\n','',array,flags=re.M)
 assert omitted!=array
 mutations.append(('OmittedInstallStep.swift',array,omitted,['install_sequence_and_weights','default_chain_contract','post_install_failure_remains_failure']))
 out.mkdir(parents=True,exist_ok=True);(out/'InstallChain.swift').write_text(source)
 for file,old,new,failures in mutations:
  assert source.count(old)==1,(old,source.count(old));(out/file).write_text(source.replace(old,new))
  variants.append({'file':file,'group':'chain','case_names':CASES,'expected_failed_names':failures})
 receipt={'schema':'install-chain-sources-v1','group':'chain','inputs':[{'path':str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths.values()],
 'support':[{'path':str(p.relative_to(HERE)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [Path(__file__),HERE/'Doubles.swift',HERE/'Operations.swift',HERE/'Cases.swift']],
 'variants':variants,'install_steps':names,'excluded_executor_arms':excluded,
 'projection_exclusions':['executor diagnostic catch/logging/phase observer','source acquisition and ZIP parsing are inert boundary doubles','Every concrete operation body, including DownloadAppOperation extraction, VerifyAppOperation, signing and InstallAppOperation native installation, is an inert boundary double; only runner/context/dispatch is real here'],
 'actual_source':['resolveInstallTarget','canonicalToken','AnyApp','AppOperation','V3InstallPipelineParity','PipelineStepDefinition','OperationContext','PipelineOperationContext','InstallAppOperationContext','PipelineRunner.performPipeline','PipelineExecutor.executePipeline','20 executeStep arms'],
 'swift_executed':False,'native_signing_device_executed':False}
 for v in variants:v['sha256']=hashlib.sha256((out/v['file']).read_bytes()).hexdigest()
 (out/'chain-sources.json').write_text(json.dumps(receipt,indent=2)+'\n');return receipt
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(generate(a.root,a.output)))
