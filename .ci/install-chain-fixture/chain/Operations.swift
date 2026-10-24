// Inert operations enforce contracts; they never sign, call Apple, or install on a device.
final class DownloadAppOperation: OperationLogging {
 let context: InstallAppOperationContext; let app: AppProtocol; let destinationURL: URL
 init(app: AppProtocol, destinationURL: URL, context: InstallAppOperationContext) throws { self.app=app;self.destinationURL=destinationURL;self.context=context }
 func execute(parentProgress: Progress?) async throws -> ALTApplication {
  try Probe.enter(.downloadApp,context)
  try Probe.require(app.url == Probe.input,"input URL")
  try Probe.require(destinationURL == context.temporaryDirectory.appendingPathComponent("App.app"),"owned destination")
  context.ipaURL=context.temporaryDirectory.appendingPathComponent("App.ipa")
  return ALTApplication(url:destinationURL,id:app.bundleIdentifier)
 }
}
final class VerifyAppOperation: OperationLogging {
 let context: InstallAppOperationContext; let mode: PermissionReviewMode
 init(permissionsMode: PermissionReviewMode, context: InstallAppOperationContext) throws { mode=permissionsMode;self.context=context }
 func execute(parentProgress: Progress?) async throws -> Bool { try Probe.enter(.verifyApp,context);try Probe.require(mode == .none,"default permission mode");return false }
}
final class VerifyCertificateOperation: OperationLogging {
 let context: InstallAppOperationContext; let willResign: Bool
 init(context: InstallAppOperationContext, willResign: Bool) throws { self.context=context;self.willResign=willResign }
 func execute(parentProgress: Progress?) async throws -> Bool { try Probe.enter(.verifyCertificate,context);try Probe.require(willResign && context.targetSigningCertificate != nil,"full-sign install certificate");return true }
}
final class FetchProvisioningProfilesOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws -> [String:ALTProvisioningProfile] { try Probe.enter(.fetchProvisioningProfiles,context);return [context.targetBundleIdentifier:ALTProvisioningProfile()] }
}
final class ResignAppOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws -> ALTApplication { try Probe.enter(.resignApp,context);try Probe.require(context.provisioningProfiles?[context.targetBundleIdentifier] != nil,"profile handoff");return context.targetAppBundle! }
}
final class CreateIpaOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws -> URL { try Probe.enter(.createIPA,context);try Probe.require(context.resignedAppBundle != nil,"resigned bundle");return context.temporaryDirectory.appendingPathComponent("Signed.ipa") }
}
final class InstallAppOperation: OperationLogging {
 let context: InstallAppOperationContext; let app: AppProtocol
 init(context: InstallAppOperationContext, app: AppProtocol) throws { self.context=context;self.app=app }
 func execute(parentProgress: Progress?) async throws -> InstalledApp { try Probe.enter(.installApp,context);try Probe.require(context.ipaURL?.lastPathComponent == "Signed.ipa","signed IPA");Probe.nativeInstallObserved=true;return InstalledApp(app.bundleIdentifier) }
}
final class CacheAppOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.cacheApp,context); }
}
final class StageAppOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.stageApp,context); }
}
final class UserCustomizationOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.userCustomization,context); }
}
final class UpdateAppCertificateOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.updateAppCertificate,context); }
}
final class ChangeAppIconOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.changeAppIcon,context); }
}
final class RemoveAppExtensionsOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext, localAppExtensions: Set<ALTApplication>?) throws { self.context=context;try Probe.require(localAppExtensions == nil,"AnyApp has no local extension override") }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.removeAppExtensions,context); }
}
final class PrepareAppExtensionBundleIDsOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.prepareAppExtensionBundleIDs,context);try Probe.require(context.provisioningProfiles?[context.targetBundleIdentifier] != nil,"profiles before extension identifiers") }
}
final class EmbedSigningCertOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.embedSigningCert,context); }
}
final class ExportResignedIpaOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.exportResignedIPA,context); }
}
final class SendAppOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.sendApp,context);try Probe.require(context.ipaURL?.lastPathComponent == "Signed.ipa" && context.resignedAppBundle != nil,"signed archive before transfer") }
}
final class CacheSigningCertOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.cacheSigningCert,context);try Probe.require(context.installedApp != nil,"installed result before post-install cache") }
}
final class CacheResignedMetadataOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.cacheResignedMetadata,context);try Probe.require(context.installedApp != nil,"installed result before post-install cache") }
}
final class CleanStagedAppOperation: OperationLogging {
 let context: InstallAppOperationContext
 init(context: InstallAppOperationContext) throws { self.context=context }
 func execute(parentProgress: Progress?) async throws { try Probe.enter(.cleanStagedApp,context);try Probe.require(context.installedApp != nil,"installed result before cleanup");Probe.cleaned=true }
}
