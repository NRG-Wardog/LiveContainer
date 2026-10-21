//
//  LCJITLessDiagnose.swift
//  LiveContainerSwiftUI
//
//  Created by s s on 2024/12/19.
//
import SwiftUI

struct LCEntitlementView : View {
    @Environment(\.locale) private var selectedDisplayLocale
    @State var isLiveProcess: Bool
    @State var loaded = false
    @State var entitlementReadSuccess = false
    @State private var hasEntitlementPayload = false
    
    @State var teamId : String?
    @State var getTaskAllow = false
    @State var keyChainAccessGroup = false
    @State var correctBundleId : String?
    @State var isBundleIdCorrect = false
    @State var appGroup = false
    
    @State var entitlementContent = "Failed to Load Entitlement."
    
    var body: some View {
        let _ = selectedDisplayLocale.identifier
        if loaded {
            Form {
                Section {
                    if !isLiveProcess {
                        HStack {
                            Text("lc.jitlessDiag.bundleId".loc)
                            Spacer()
                            Text(Bundle.main.bundleIdentifier ?? "lc.common.unknown".loc)
                                .foregroundStyle(entitlementReadSuccess && teamId != nil ? (isBundleIdCorrect ? .green : .red): .gray)
                                .textSelection(.enabled)
                        }
                    }
                    if entitlementReadSuccess {
                        if !isLiveProcess && !isBundleIdCorrect && teamId != nil {
                            HStack {
                                Text("lc.jitlessDiag.bundleIdExpected".loc)
                                Spacer()
                                Text(correctBundleId ?? "lc.common.unknown".loc)
                                    .foregroundStyle(.gray)
                            }
                        }
                        HStack {
                            Text("lc.jitlessDiag.teamId".loc)
                            Spacer()
                            Text(teamId ?? "lc.common.unknown".loc)
                                .foregroundStyle(.gray)
                        }
                        HStack {
                            Text("get-task-allow")
                            Spacer()
                            Text(getTaskAllow ? "lc.common.yes".loc : "lc.common.no".loc)
                                .foregroundStyle(getTaskAllow ? .green : .red)
                        }
                        HStack {
                            Text("com.apple.security.application-groups \("lc.common.correct".loc)")
                            Spacer()
                            Text(appGroup ? "lc.common.yes".loc : "lc.common.no".loc)
                                .foregroundStyle(appGroup ? .green : .red)
                        }
                        HStack {
                            Text("keychain-access-groups \("lc.common.correct".loc)")
                            Spacer()
                            Text(keyChainAccessGroup ? "lc.common.yes".loc : "lc.common.no".loc)
                                .foregroundStyle(keyChainAccessGroup ? .green : .red)
                        }

                    }
                }

                
                Section {
                    Button {
                        UIPasteboard.general.string = entitlementContent
                    } label: {
                        Text("lc.common.copy".loc)
                    }
                    Group {
                        if hasEntitlementPayload {
                            Text(verbatim: entitlementContent)
                        } else {
                            V3LocalizedText(entitlementContent)
                        }
                    }
                    .font(.system(.subheadline, design: .monospaced))
                }
            }
            .navigationTitle(V3Localization.prose(isLiveProcess ? "LiveProcess Entitlements" : "LiveContainer Entitlements", language: .resolve(selectedDisplayLocale.identifier)))
            .navigationBarTitleDisplayMode(.inline)
        } else {
            Text("lc.common.loading".loc)
                .onAppear() {
                    onAppear()
                }
        }
    }
    
    func onAppear() {
        if loaded {
            return
        }
        
        defer {
            loaded = true
        }
        
        let executablePath: String?
        
        if !isLiveProcess {
            executablePath = Bundle.main.executablePath
        } else {
            executablePath = Bundle.main.builtInPlugInsURL?.appendingPathComponent("LiveProcess.appex/LiveProcess").path
            if let executablePath, !FileManager.default.fileExists(atPath: executablePath) {
                entitlementContent = "LiveProcess is not installed."
                return
            }
        }

        guard let entitlementXML = getExecutableEntitlementXML(executablePath) else {
            entitlementContent = "Failed to load entitlement."
            return
        }
        entitlementContent = entitlementXML
        hasEntitlementPayload = true
        
        var format = PropertyListSerialization.PropertyListFormat.xml
        guard let entitlementDict = try? PropertyListSerialization.propertyList(from: entitlementXML.data(using: .utf8) ?? Data(), format: &format) as? [String : AnyObject] else {
            return
        }
        entitlementReadSuccess = true
        let entitlementTeamId = entitlementDict["com.apple.developer.team-identifier"] as? String
        teamId = entitlementTeamId
        if let entitlementTeamId {
            if let appGroups = entitlementDict["com.apple.security.application-groups"] as? Array<String> {
                if appGroups.count > 0 {
                    appGroup = true
                }
            }
            if let keyChainAccessGroups = entitlementDict["keychain-access-groups"] as? Array<String> {
                var notFound = true
                if keyChainAccessGroups.contains("\(entitlementTeamId).com.kdt.livecontainer.shared") {
                    notFound = false
                    for i in 1..<SharedModel.keychainAccessGroupCount {
                        if !keyChainAccessGroups.contains("\(entitlementTeamId).com.kdt.livecontainer.shared.\(i)") {
                            notFound = true
                            continue
                        }
                    }
                }
                keyChainAccessGroup = !notFound
            }
        }
        if let appIdentifier = entitlementDict["application-identifier"] as? String, appIdentifier.count > 11 {
            let startIndex = appIdentifier.index(appIdentifier.startIndex, offsetBy: 11)
            correctBundleId = String(appIdentifier[startIndex...])
            if let bundleId = Bundle.main.bundleIdentifier {
                isBundleIdCorrect = bundleId == correctBundleId
            }
        }
        
        getTaskAllow = entitlementDict["get-task-allow"] as? Bool ?? false

    }
    
}

struct LCJITLessDiagnoseView : View {
    @Environment(\.locale) private var selectedDisplayLocale
    @Environment(\.locale) private var dateLocale

    @State var loaded = false
    @State var appGroupId: String?
    @State var appGroupIdColor : Color = .gray
    @State var store : Store = .SideStore
    @State var certificateDataFound = false
    @State var certificatePasswordFound = false
    @State var appGroupAccessible = false
    @State var certTeamId : String?
    @State var expectedTeamId : String?
    @State var certLastUpdateDate : Date? = nil
    @State var certificateStatus : Int = -1
    @State var certificateValidateUntil : Date? = nil
    
    @State var isJITLessTestInProgress = false
    
    @State var errorShow = false
    @State var errorDisplay = V3DisplayMessage.raw("")
    var errorInfo: String {
        get { errorDisplay.original }
        nonmutating set { errorDisplay = .raw(newValue) }
    }
    @State var successShow = false
    @State var successDisplay = V3DisplayMessage.raw("")
    var successInfo: String {
        get { successDisplay.original }
        nonmutating set { successDisplay = .raw(newValue) }
    }
    
    @EnvironmentObject private var sharedModel : SharedModel
    
    let storeName = LCUtils.getStoreName()
    
    var body: some View {
        let _ = selectedDisplayLocale.identifier
        if loaded {
            Form {
                Section {
                    HStack {
                        Text("lc.jitlessDiag.bundleId".loc)
                        Spacer()
                        Text(Bundle.main.bundleIdentifier ?? "lc.common.unknown".loc)
                            .foregroundStyle(.gray)
                            .textSelection(.enabled)
                    }

                    HStack {
                        Text("lc.jitlessDiag.appGroupId".loc)
                        Spacer()
                        Text(appGroupId ?? "lc.common.unknown".loc)
                            .foregroundStyle(appGroupIdColor)
                    }
                    HStack {
                        Text("lc.jitlessDiag.appGroupAccessible".loc)
                        Spacer()
                        Text(appGroupAccessible ? "lc.common.yes".loc : "lc.common.no".loc)
                            .foregroundStyle(appGroupAccessible ? .green : .red)
                    }
                    HStack {
                        Text("lc.jitlessDiag.store".loc)
                        Spacer()
                        if store == .AltStore {
                            Text("AltStore")
                                .foregroundStyle(.gray)
                        } else if store == .SideStore {
                            Text("SideStore")
                                .foregroundStyle(.gray)
                        } else if store == .ADP {
                            Text("lc.common.ADP".loc)
                                .foregroundStyle(.gray)
                        } else {
                            Text("lc.common.unknown".loc)
                                .foregroundStyle(.gray)
                        }
                        
                    }
                    NavigationLink {
                        LCEntitlementView(isLiveProcess: false)
                    } label: {
                        Text("LiveContainer Entitlements".loc)
                    }
                    if sharedModel.multiLCStatus == 0 {
                        NavigationLink {
                            LCEntitlementView(isLiveProcess: true)
                        } label: {
                            Text("LiveProcess Entitlements".loc)
                        }
                    }
                }
                    
                Section() {
                    HStack {
                        Text("lc.jitlessDiag.certDataFound".loc)
                        Spacer()
                        Text(certificateDataFound ? "lc.common.yes".loc : "lc.common.no".loc)
                            .foregroundStyle(certificateDataFound ? .green : .red)
                        
                    }
                    HStack {
                        Text("lc.jitlessDiag.certPassFound".loc)
                        Spacer()
                        Text(certificatePasswordFound ? "lc.common.yes".loc : "lc.common.no".loc)
                            .foregroundStyle(certificatePasswordFound ? .green : .red)
                    }
                    
                    HStack {
                        Text("lc.jitlessDiag.certLastUpdate".loc)
                        Spacer()
                        if let certLastUpdateDate {
                            Text(V3Localization.legacyDate(certLastUpdateDate, dateStyle: .short, timeStyle: .medium, language: V3AppLanguage.resolve(dateLocale.identifier)))
                                .foregroundStyle(.green)
                        } else {
                            Text("lc.common.unknown".loc)
                                .foregroundStyle(.red)
                        }
                        
                    }
                    if certificateDataFound && certTeamId != nil && certTeamId != expectedTeamId {
                        HStack {
                            Text("lc.jitlessDiag.expectedTeamId".loc)
                            Spacer()
                            Text(expectedTeamId ?? "lc.common.unknown".loc)
                                .foregroundStyle(.gray)
                        }
                    }
                    if certificateDataFound {
                        HStack {
                            Text("lc.jitlessDiag.certTeamId".loc)
                            Spacer()
                            Text(certTeamId ?? "lc.common.unknown".loc)
                                .foregroundStyle(certTeamId != nil && certTeamId == expectedTeamId ? .green : .red)
                        }
                        HStack {
                            Text("lc.jitlessDiag.certificateStatus".loc)
                            Spacer()
                            Text(certificateStatus == -1 ? "lc.jitlessDiag.checking".loc : getStatusText(status: certificateStatus))
                                .foregroundStyle(certificateStatus == 0 ? .green : .red)
                        }
                        HStack {
                            Text("lc.jitlessDiag.certificateValidateUntil".loc)
                            Spacer()
                            Text(certificateValidateUntil.map { V3Localization.legacyDate($0, dateStyle: .short, timeStyle: .medium, language: V3AppLanguage.resolve(dateLocale.identifier)) } ?? "lc.common.unknown".loc)
                                .foregroundStyle(certificateStatus == 0 ? .green : .red)
                        }
                    }
                    
                }
                                
                Section {
                    Button {
                        testJITLessMode()
                    } label: {
                        Text("lc.settings.testJitLess".loc)
                    }
                    .disabled(isJITLessTestInProgress)
                    
                    Button {
                        getHelp()
                    } label: {
                        // we apply a super cool rainbow effect so people will never miss this button
                        Text("lc.jitlessDiag.getHelp".loc)
                            .bold()
                            .rainbow()
                    }
                }

            }
            .navigationTitle("lc.settings.jitlessDiagnose".loc)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        onAppear()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    
                }
            }
            .alert("lc.common.error".loc, isPresented: $errorShow){
            Button("lc.common.ok".loc, role: .cancel) {}
            Button("lc.common.copy".loc) {
                UIPasteboard.general.string = LCNativeErrorPresentation.details(errorInfo, site: .signingDiagnostics)
            }
            } message: {
                V3LocalizedText(errorDisplay.appendingDiagnostic(LCNativeErrorSite.signingDiagnostics.rawValue))
            }
            .alert("lc.common.success".loc, isPresented: $successShow){
            } message: {
                V3LocalizedText(successDisplay)
            }
            
        } else {
            Text("lc.common.loading".loc)
                .onAppear() {
                    onAppear()
                }
        }

    }
    
    func onAppear() {
        
        let task = SecTaskCreateFromSelf(nil)
        guard let value = SecTaskCopyValueForEntitlement(task, "com.apple.developer.team-identifier" as CFString, nil), let teamId = value.takeRetainedValue() as? String else {
            errorInfo = "Failed to read com.apple.developer.team-identifier"
            errorShow = true
            return
        }
        expectedTeamId = teamId
        
        if let fetchedAppGroupId = LCSharedUtils.appGroupID() {
            appGroupId = fetchedAppGroupId
            if UserDefaults.sideStoreExist() {
                if fetchedAppGroupId == "group.com.SideStore.SideStore." + teamId {
                    appGroupIdColor = .green
                } else {
                    appGroupIdColor = .orange
                }
            } else {
                appGroupIdColor = .green
            }
        } else {
            appGroupId = nil
            appGroupIdColor = .red
        }
        
        store = LCUtils.store()
        appGroupAccessible = LCSharedUtils.appGroupPath() != nil
        certificateDataFound = LCUtils.certificateData() != nil
        certificatePasswordFound = LCSharedUtils.certificatePassword() != nil
        if let lastUpdateDate = LCUtils.appGroupUserDefault.object(forKey: "LCCertificateUpdateDate") as? Date {
            certLastUpdateDate = lastUpdateDate
        }
        if certificateDataFound {
            validateCertificate()
        }

        loaded = true
    }
    
    func testJITLessMode() {
        if !certificateDataFound {
            errorDisplay = .localized("lc.settings.error.certNotImported")
            errorShow = true
            return;
        }

        isJITLessTestInProgress = true
        LCUtils.validateJITLessSetup { success, error in
            if success {
                successDisplay = .localized("lc.jitlessSetup.success")
                successShow = true
            } else {
                errorDisplay = .localized("lc.jitlessSetup.error.testLibLoadFailed %@ %@ %@", storeName, storeName, storeName) + .raw("\n") + .raw(error?.localizedDescription ?? "")
                errorShow = true
            }
            isJITLessTestInProgress = false
        }
    
    }
    
    func getHelp() {
        UIApplication.shared.open(URL(string: "https://livecontainer.github.io/docs/faq/jit-less-mode-setup")!)
    }
    
    func validateCertificate() {
        certificateStatus = -1
        certificateValidateUntil = nil
        LCUtils.validateCertificate { status, date, ou, error in
            if let error {
                errorDisplay = .localized(error)
                errorShow = true
                certificateStatus = 2
                return
            }
            certificateStatus = Int(status)
            if let date {
                certificateValidateUntil = date
            }
            if let ou {
                certTeamId = ou
            }
        }
    }
    
    func getStatusText(status: Int) -> String {
        switch status {
        case 0:
            return "lc.jitlessDiag.certificateValid".loc
        case 1:
            return "lc.jitlessDiag.certificateRevoked".loc
        default:
            return "lc.common.unknown".loc
        }
    }
}

// LC_NATIVE_ERROR_PRESENTERS_V1
