//
//  TabView.swift
//  LiveContainerSwiftUI
//
//  Created by s s on 2024/8/21.
//

import Foundation
import SwiftUI

struct V3ApplicationRoot<Content: View>: View {
    @Environment(\.locale) private var selectedDisplayLocale
    let content: Content
    @State var errorShow = false
    @State var crashReportShow = false
    @State var errorDisplay = V3DisplayMessage.raw("")
    var errorInfo: String {
        get { errorDisplay.original }
        nonmutating set { errorDisplay = .raw(newValue) }
    }
    
    @EnvironmentObject var sharedModel : SharedModel
    @EnvironmentObject var sceneDelegate: SceneDelegate
    @State var shouldToggleMainWindowOpen = false
    @Environment(\.scenePhase) var scenePhase
    @StateObject var downloadHelper = DownloadHelper()

    let pub = NotificationCenter.default.publisher(for: UIScene.didDisconnectNotification)
    
    var body: some View {
        let _ = selectedDisplayLocale.identifier
        content
        .downloadAlert(helper: downloadHelper)
        .environmentObject(downloadHelper)
        .alert("lc.common.error".loc, isPresented: $errorShow){
            Button("lc.common.ok".loc, action: {
            })
            Button("lc.common.copy".loc, action: {
                UIPasteboard.general.string = LCNativeErrorPresentation.details(errorInfo, site: .root)
            })
        } message: {
            V3LocalizedText(errorDisplay.appendingDiagnostic(LCNativeErrorSite.root.rawValue))
        }
        .sheet(isPresented: $crashReportShow) {
            NavigationView {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        V3LocalizedText(errorDisplay)
                        DisclosureGroup("Technical details") {
                            Text(verbatim: errorInfo)
                                .environment(\.layoutDirection, .leftToRight)
                                .font(.system(size: 12).monospaced())
                                .fixedSize(horizontal: false, vertical: false)
                                .textSelection(.enabled)
                        }
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.horizontal)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button("lc.common.copy".loc, action: {
                            copyError()
                        })
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("lc.common.ok".loc, action: {
                            crashReportShow = false
                        })
                    }
                }
                .navigationTitle("lc.common.error".loc)
                .navigationBarTitleDisplayMode(.inline)
            }
        }
        .task {
            closeDuplicatedWindow()
            checkLastLaunchError()
            checkTeamId()
            checkAndSaveBundleId()
            checkGetTaskAllow()
            checkPrivateContainerBookmark()
        }
        .onReceive(pub) { out in
            if let scene1 = sceneDelegate.window?.windowScene, let scene2 = out.object as? UIWindowScene, scene1 == scene2 {
                if shouldToggleMainWindowOpen {
                    DataManager.shared.model.mainWindowOpened = false
                    if #available(iOS 16.1, *), MultitaskWindowManager.mainSceneSession?.persistentIdentifier == scene1.session.persistentIdentifier {
                        MultitaskWindowManager.mainSceneSession = nil
                    }
                }
            }
        }
        // V3_HEADLESS_LC_TAB_ROUTING_REMOVED_V1: URL routing belongs to V3UnifiedShell.
    }
    

    
    func closeDuplicatedWindow() {
        if let session = sceneDelegate.window?.windowScene?.session, DataManager.shared.model.mainWindowOpened {
            UIApplication.shared.requestSceneSessionDestruction(session, options: nil) { e in
                print(e)
            }
        } else {
            shouldToggleMainWindowOpen = true
            if #available(iOS 16.1, *) {
                MultitaskWindowManager.mainSceneSession = sceneDelegate.window?.windowScene?.session
            }
        }
        DataManager.shared.model.mainWindowOpened = true
    }
    
    func checkLastLaunchError() {
        var launchError = UserDefaults.standard.string(forKey: "error").map { V3DisplayMessage.raw($0) }
        
        if launchError == nil && UserDefaults.standard.bool(forKey: "SigningInProgress") {
            launchError = .localized("lc.signer.crashDuringSignErr")
            UserDefaults.standard.removeObject(forKey: "SigningInProgress")
        }
        
        guard let launchError else {
            return
        }
        UserDefaults.standard.removeObject(forKey: "error")
        errorDisplay = launchError
        crashReportShow = true
    }
    
    func copyError() {
        UIPasteboard.general.string = errorInfo
    }
    
    func checkTeamId() {
        if let certificateTeamId = UserDefaults.standard.string(forKey: "LCCertificateTeamId") {
            if DataManager.shared.model.multiLCStatus != 2 {
                return
            }
            
            guard let primaryLCTeamId = Bundle.main.infoDictionary?["PrimaryLiveContainerTeamId"] as? String else {
                print("Unable to find PrimaryLiveContainerTeamId")
                return
            }
            if certificateTeamId != primaryLCTeamId {
                errorDisplay = .localized("lc.settings.multiLC.teamIdMismatch")
                errorShow = true
                return
            }
            return
        }
        
        guard let currentTeamId = LCSharedUtils.teamIdentifier() else {
            print("Failed to determine team id.")
            return
        }
        
        if DataManager.shared.model.multiLCStatus == 2 {
            guard let primaryLCTeamId = Bundle.main.infoDictionary?["PrimaryLiveContainerTeamId"] as? String else {
                print("Unable to find PrimaryLiveContainerTeamId")
                return
            }
            if currentTeamId != primaryLCTeamId {
                errorDisplay = .localized("lc.settings.multiLC.teamIdMismatch")
                errorShow = true
                return
            }
        }
        UserDefaults.standard.set(currentTeamId, forKey: "LCCertificateTeamId")
    }
    
    func checkAndSaveBundleId() {
        if DataManager.shared.model.multiLCStatus == 2 {
            let scheme = UserDefaults.lcAppUrlScheme() ?? ""
            LCUtils.appGroupUserDefault.set(Bundle.main.bundleIdentifier, forKey: "LCBundleID.\(scheme)")
        }
        
        if UserDefaults.standard.bool(forKey: "LCBundleIdChecked") {
            return
        }
        
        let task = SecTaskCreateFromSelf(nil)
        guard let value = SecTaskCopyValueForEntitlement(task, "application-identifier" as CFString, nil), let appIdentifier = value.takeRetainedValue() as? String else {
            errorInfo = "Unable to determine application-identifier"
            errorShow = true
            return
        }
        
        guard let bundleId = Bundle.main.bundleIdentifier else {
            return
        }
        
        var correctBundleId = ""
        if appIdentifier.count > 11 {
            let startIndex = appIdentifier.index(appIdentifier.startIndex, offsetBy: 11)
            correctBundleId = String(appIdentifier[startIndex...])
        }
        
        if(bundleId != correctBundleId) {
            errorDisplay = .localized("lc.settings.bundleIdMismatch %@ %@", bundleId, correctBundleId)
            errorShow = true
        }
        UserDefaults.standard.set(true, forKey: "LCBundleIdChecked")
    }
    
    func checkGetTaskAllow() {
        let task = SecTaskCreateFromSelf(nil)
        guard let value = SecTaskCopyValueForEntitlement(task, "get-task-allow" as CFString, nil), (value.takeRetainedValue() as? NSNumber)?.boolValue ?? false else {
            errorDisplay = .localized("lc.settings.notDevCert")
            errorShow = true
            return
        }
    }
    
    func checkPrivateContainerBookmark() {
        if sharedModel.multiLCStatus == 2 {
            return
        }
        if LCUtils.appGroupUserDefault.object(forKey: "LCLaunchExtensionPrivateDocBookmark") != nil {
            return
        }
        
        guard let bookmark = LCUtils.bookmark(for: LCPath.docPath) else {
            errorInfo = "Failed to create bookmark for Documents folder?"
            errorShow = true
            return
        }
        LCUtils.appGroupUserDefault.set(bookmark, forKey: "LCLaunchExtensionPrivateDocBookmark")
    }
}

// LC_NATIVE_ERROR_PRESENTERS_V1
