# Patch-to-maintained-source map

Frozen integration: `141776ba6ba38fc04a5e77f68b0cfc4e6c8842ee`.

This map combines observed OLD replay writes with static helper ownership. A patch name is provenance, not the new unit of maintenance. Each destination is owned and committed by subsystem; no script listed here is a build dependency of the maintained source.

## patch_app_layout.py

- `.lc-app-layout.json`: archived preparation metadata only
- `LiveContainerSwiftUI/Models/AppLayoutStyle.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/Views/AppList/LCAppBanner/LCAppBanner.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/Views/AppList/LCAppBanner/LCAppBannerView.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/Views/AppList/LCAppBanner/LCAppBannerViewController.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/Views/AppList/LCAppListView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/AppList/LCGridAppCell.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/Views/Settings/LCSettingsView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)

## patch_cf_bundle_scan.py

- `LiveContainer/LCBootstrap.m`: embedded service lifecycle (`311577423c3b`), guest and process lifecycle (`93b29c03ebca`), unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)

## patch_combined_service_startup.py

- `.combined-service-startup.json`: archived preparation metadata only
- `LiveContainer/LCBootstrap.m`: embedded service lifecycle (`311577423c3b`), guest and process lifecycle (`93b29c03ebca`), unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainer/LCContainerStorage.h`: embedded service lifecycle (`311577423c3b`)
- `LiveContainerSwiftUI/Views/Settings/LCSettingsView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `SideStoreSupport/SideStore.swift`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/SideStoreClient.swift`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/XPCServer.h`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/XPCServer.m`: XPC and refresh result bridge (`c894d8e88f22`)

## patch_dead10cc_fix.py

- `LiveContainer/Tweaks/Dead10ccFix.m`: guest and process lifecycle (`93b29c03ebca`)

## patch_embedded_sidestore_startup.py

- `LiveContainer/LCBootstrap.m`: embedded service lifecycle (`311577423c3b`), guest and process lifecycle (`93b29c03ebca`), unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `SideStoreSupport/SideStoreHooks.m`: embedded service lifecycle (`311577423c3b`)

## patch_guest_return.py

- `LiveContainer/LCBootstrap.m`: embedded service lifecycle (`311577423c3b`), guest and process lifecycle (`93b29c03ebca`), unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Models/LCAppModel.swift`: guest and process lifecycle (`93b29c03ebca`)
- `LiveContainerSwiftUI/Views/LCTabView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/Settings/LCSettingsView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `MultitaskSupport/AppSceneViewController.h`: guest and process lifecycle (`93b29c03ebca`)
- `MultitaskSupport/AppSceneViewController.m`: guest and process lifecycle (`93b29c03ebca`)
- `MultitaskSupport/DecoratedAppSceneViewController.m`: guest and process lifecycle (`93b29c03ebca`)
- `MultitaskSupport/MultitaskAppWindow.swift`: guest and process lifecycle (`93b29c03ebca`)
- `MultitaskSupport/MultitaskDockView.swift`: guest and process lifecycle (`93b29c03ebca`)
- `SideStoreSupport/SideStoreHooks.m`: embedded service lifecycle (`311577423c3b`)

## patch_lc_certificate_observation.py

- `LiveContainerSwiftUI/Utilities/LCUtils.h`: certificate readiness observation (`e9d09118d075`)
- `LiveContainerSwiftUI/Utilities/LCUtils.m`: certificate readiness observation (`e9d09118d075`)
- `ZSign/zsign.mm`: certificate readiness observation (`e9d09118d075`)
- `ZSign/zsigner.h`: certificate readiness observation (`e9d09118d075`)

## patch_livecontainer_autorefresh.py

- `LiveContainer.xcodeproj/project.pbxproj`: unified host shell and UI (`523b623542fc`)
- `LiveContainer/Info.plist`: refresh scheduling and settings (`3cc5652cd324`)
- `LiveContainerSwiftUI/App/AppDelegate.swift`: refresh scheduling and settings (`3cc5652cd324`)
- `LiveContainerSwiftUI/App/LiveContainerAutoRefreshAlarm.swift`: refresh scheduling and settings (`3cc5652cd324`)
- `LiveContainerSwiftUI/Utilities/V3SharedAppGroup.swift`: App Group runtime identity (`1c73e8df77bd`)
- `LiveContainerSwiftUI/Views/Settings/LCEmbeddedSideStoreRefreshView.swift`: refresh scheduling and settings (`3cc5652cd324`)
- `LiveContainerSwiftUI/Views/Settings/LCSettingsView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `SideStoreSupport/SideStore.swift`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/SideStoreClient.swift`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/XPCClient.m`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/XPCServer.h`: XPC and refresh result bridge (`c894d8e88f22`)

## patch_multitask_dock.py

- `LiveContainerSwiftUI/Views/Settings/LCMultitaskSettingView.swift`: guest and process lifecycle (`93b29c03ebca`)
- `MultitaskSupport/MultitaskDockView.swift`: guest and process lifecycle (`93b29c03ebca`)

## patch_native_error_presenters.py

- `LiveContainerSwiftUI/Utilities/ViewExtensions.swift`: diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/AppList/AppSettings/LCAppSettingsView.swift`: diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/AppList/AppSettings/LCContainerView.swift`: diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/AppList/LCAppListView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/AppList/LCWebView.swift`: diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/LCAltStoreSourcesView.swift`: diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/LCTabView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/LCTweaksView.swift`: diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/Settings/DataManagement/LCDataManagementView.swift`: diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/Settings/DataManagement/LCStorageManagementSections.swift`: diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/Settings/LCJITLessDiagnoseView.swift`: diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/Settings/LCSettingsView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `TweakLoader/TweakLoader.m`: diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)

## patch_refresh_result_bridge.py

- `SideStoreSupport/SideStore.swift`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/SideStoreClient.swift`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/XPCClient.m`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/XPCServer.h`: XPC and refresh result bridge (`c894d8e88f22`)

## patch_v3_service.py

- `.v3-command-patch.json`: archived preparation metadata only
- `LaunchAppExtension/LaunchAppExtension.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainer/LCAppGroupIdentityRules.h`: App Group runtime identity (`1c73e8df77bd`)
- `LiveContainer/LCAppGroupSelectionPolicy.h`: App Group runtime identity (`1c73e8df77bd`)
- `LiveContainer/LCBootstrap.m`: embedded service lifecycle (`311577423c3b`), guest and process lifecycle (`93b29c03ebca`), unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainer/LCSharedUtils.m`: App Group runtime identity (`1c73e8df77bd`)
- `LiveContainerSwiftUI/App/AppDelegate.swift`: refresh scheduling and settings (`3cc5652cd324`)
- `LiveContainerSwiftUI/Utilities/LCUtilsExtensions.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/Views/AppList/LCAppListView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/LCTabView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/Settings/LCEmbeddedSideStoreRefreshView.swift`: refresh scheduling and settings (`3cc5652cd324`)
- `LiveContainerSwiftUI/Views/Settings/LCMultiLCManagementView.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/Views/Settings/LCSettingsView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveProcess/main.m`: App Group runtime identity (`1c73e8df77bd`)
- `MultitaskSupport/AppSceneViewController.h`: guest and process lifecycle (`93b29c03ebca`)
- `MultitaskSupport/AppSceneViewController.m`: guest and process lifecycle (`93b29c03ebca`)
- `ShareExtension/ShareExtensionViewModel.swift`: unified host shell and UI (`523b623542fc`)
- `SideStoreSupport/SideStore.swift`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/XPCClient.m`: XPC and refresh result bridge (`c894d8e88f22`)
- `SideStoreSupport/XPCServer.h`: XPC and refresh result bridge (`c894d8e88f22`)

## patch_v3_unified_shell.py

- `LiveContainer.xcodeproj/project.pbxproj`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/App/LiveContainerSwiftUIApp.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/App/V3SetupAssistantIntent.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/Utilities/Shared.swift`: unified host shell and UI (`523b623542fc`)
- `LiveContainerSwiftUI/Views/AppList/LCAppListView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/Settings/LCSettingsView.swift`: unified host shell and UI (`523b623542fc`), diagnostic presenters and bounded bootstrap (`7d9786afb7ff`)
- `LiveContainerSwiftUI/Views/V3UnifiedShell.swift`: unified host shell and UI (`523b623542fc`)

## Interpretation

- Some wrappers call helper mutators. `patch_cf_bundle_scan.py` and `patch_refresh_result_bridge.py` are represented even when they are not independent steps in the 19-stage active replay.
- Exact template source boundaries are in `source-components.json`; other changes are ordinary upstream source diffs applied as subsystem-owned source.
- The complete per-file old/new hash and mode mapping is in `source-parity.json`.
- Source-unit coupling is documented in `RUNTIME_SOURCE_MIGRATION.md`. No claim is made that every intermediate subsystem commit independently builds before the complete migration series.
- The three archived metadata files contain OLD generator bookkeeping. Their root paths are intentionally absent from the maintained product tree.
