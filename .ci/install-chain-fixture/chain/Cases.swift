@main struct InstallChainCases {
 static func main() async {
  var results: [[String:Any]]=[]
  func record(_ name:String,_ body:() async throws -> Bool) async {
   Probe.reset()
   let passed:Bool
   do { passed=try await body() } catch { passed=false }
   results.append(["name":name,"passed":passed])
  }
  defer { try? FileManager.default.removeItem(at:Probe.root) }
  try? FileManager.default.createDirectory(at:Probe.root,withIntermediateDirectories:true)
  await record("input_owned_url_and_identity") {
   let app=try await InputResolver().resolve(Probe.token)
   return app.name == "Synthetic" && app.bundleIdentifier == "com.fixture.synthetic" && app.url == Probe.input && app.storeApp == nil
  }
  await record("input_rejects_noncanonical_token") {
   do { _=try await InputResolver().resolve("../outside.ipa");return false }
   catch let error as CombinedIPAFileError { return error.reason == .invalidToken }
   catch { return false }
  }
  await record("context_default_values") {
   let context=InstallAppOperationContext(pipelineSteps:PipelineStepDefinition.install,bundleIdentifier:"com.fixture.synthetic",
       dbBackgroundContext:NSManagedObjectContext(),sharedContext:SharedPipelineContext(),handler:ProbeHandler())
   return context.customBundleIdentifier == nil && context.targetBundleIdentifier == context.bundleIdentifier && context.appendTeamID && !context.useMainProfile && context.targetAppBundle == nil && context.ipaURL == nil && context.appVersion == nil && context.installedApp == nil && context.provisioningProfiles == nil && !context.isStoreUpdate
  }
  await record("install_sequence_and_weights") {
   let expected:[PipelineStep]=[.downloadApp,.verifyApp,.cacheApp,.stageApp,.userCustomization,.updateAppCertificate,.verifyCertificate,.changeAppIcon,.removeAppExtensions,.fetchProvisioningProfiles,.prepareAppExtensionBundleIDs,.embedSigningCert,.resignApp,.createIPA,.exportResignedIPA,.sendApp,.installApp,.cacheSigningCert,.cacheResignedMetadata,.cleanStagedApp]
   let steps=PipelineStepDefinition.steps(for:.install(AnyApp(name:"Synthetic",bundleIdentifier:"com.fixture.synthetic",url:Probe.input,storeApp:nil)))
   return steps.map(\.step)==expected && steps.allSatisfy{$0.weight>0} && Set(steps.map(\.step)).count==20
  }
  await record("default_chain_contract") {
   let app=try await InputResolver().resolve(Probe.token)
   let result=try await FixtureRunner().run(app)
   guard let context=Probe.lastContext else{return false}
   return Probe.trace == PipelineStepDefinition.install.map(\.step) && Probe.weights == PipelineStepDefinition.install.map(\.weight) && result === context.installedApp && result.bundleIdentifier == app.bundleIdentifier && Probe.cleaned && Probe.nativeInstallObserved && context.ipaURL?.lastPathComponent == "Signed.ipa" && context.resignedAppBundle != nil && context.provisioningProfiles?[context.targetBundleIdentifier] != nil && context.additionalEntitlements[.fixture] as? Bool == true
  }
  await record("failure_stops_before_next_step") {
   Probe.failAt = .cacheApp
   do { let app=try await InputResolver().resolve(Probe.token);_=try await FixtureRunner().run(app);return false }
   catch ProbeFailure.injected(let step) { return step == .cacheApp && Probe.trace == [.downloadApp,.verifyApp,.cacheApp] && !Probe.nativeInstallObserved && !Probe.cleaned }
   catch { return false }
  }
  await record("post_install_failure_remains_failure") {
   Probe.failAt = .cacheSigningCert
   do { let app=try await InputResolver().resolve(Probe.token);_=try await FixtureRunner().run(app);return false }
   catch ProbeFailure.injected(let step) {
    return step == .cacheSigningCert && Probe.trace == Array(PipelineStepDefinition.install.map(\.step).prefix(18)) && Probe.nativeInstallObserved && Probe.lastContext?.installedApp != nil && !Probe.cleaned
   } catch { return false }
  }
  let passed=results.allSatisfy{($0["passed"] as? Bool)==true}
  let receipt:[String:Any]=["schema":"install-chain-runtime-v1","group":"chain","cases":results,"passed":passed,"native_signing_device_executed":false]
  if let data=try? JSONSerialization.data(withJSONObject:receipt,options:[.sortedKeys]),let text=String(data:data,encoding:.utf8){print(text)}
  exit(passed ? 0 : 1)
 }
}
