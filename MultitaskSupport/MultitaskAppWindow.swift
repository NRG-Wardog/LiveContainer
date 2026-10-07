//
//  MultitaskAppWindow.swift
//  LiveContainer
//
//  Created by s s on 2025/5/17.
//
import SwiftUI

@available(iOS 16.1, *)
struct MultitaskAppInfo {
    var displayName: String
    var dataUUID: String
    var bundleId: String
    let windowID = UUID().uuidString
    var pid: Int32 = 0
    weak var controller: AppSceneViewController?
    var launchCallback: ((NSNumber, Error?) -> Void)?
    
    init(displayName: String, dataUUID: String, bundleId: String) {
        self.displayName = displayName
        self.dataUUID = dataUUID
        self.bundleId = bundleId
    }
}

@available(iOS 16.1, *)
@objc class MultitaskWindowManager: NSObject {
    @Environment(\.openWindow) static var openWindow
    static var appDict: [String: MultitaskAppInfo] = [:]
    

    // LC_GUEST_RETURN_V2: all registry mutations occur on the main queue.
    static var mainSceneSession: UISceneSession?

    static func activateMainScene(create: () -> Void) {
        if let session = mainSceneSession,
           UIApplication.shared.openSessions.contains(where: { $0.persistentIdentifier == session.persistentIdentifier }) {
            UIApplication.shared.requestSceneSessionActivation(session, userActivity: nil, options: nil) { error in
                print("[LC_RETURN] RETURN_FAILED reason=host_activation error=\(error.localizedDescription)")
            }
        } else {
            mainSceneSession = nil
            create()
        }
        // A request is not proof of a foreground transition.
        print("[LC_RETURN] HOST_ACTIVATION_REQUESTED mode=LIVEPROCESS_PRESERVED_RETURN")
    }

    @objc class func openAppWindow(displayName: String, dataUUID: String, bundleId: String, pidCallback: ((NSNumber, Error?) -> Void)?) {
        if !Thread.isMainThread {
            DispatchQueue.main.async { openAppWindow(displayName: displayName, dataUUID: dataUUID, bundleId: bundleId, pidCallback: pidCallback) }
            return
        }
        guard !appDict.values.contains(where: { $0.dataUUID == dataUUID }) else {
            pidCallback?(NSNumber(value: -1), NSError(domain: "LiveContainerReturn", code: 409,
                userInfo: [NSLocalizedDescriptionKey: "This guest container already has a window or a pending launch. Reopen it instead."]))
            return
        }
        DataManager.shared.model.enableMultipleWindow = true
        var entry = MultitaskAppInfo(displayName: displayName, dataUUID: dataUUID, bundleId: bundleId)
        entry.launchCallback = pidCallback
        appDict[entry.windowID] = entry
        openWindow(id: "appView", value: entry.windowID)
    }

    static func bind(_ controller: AppSceneViewController, windowID: String) {
        guard appDict[windowID] != nil else { return }
        appDict[windowID]?.controller = controller
    }

    static func initialized(_ controller: AppSceneViewController, windowID: String, error: Error?) {
        guard var entry = appDict[windowID] else { return }
        entry.controller = controller
        entry.pid = controller.pid
        let callback = entry.launchCallback
        entry.launchCallback = nil // Consume before calling re-entrant client code.
        appDict[windowID] = entry
        if error != nil {
            controller.appTerminationCleanUp()
            appDict.removeValue(forKey: windowID)
        }
        callback?(NSNumber(value: controller.pid), error)
    }

    static func exited(_ controller: AppSceneViewController, windowID: String) {
        guard let entry = appDict[windowID], entry.controller === controller else { return }
        appDict.removeValue(forKey: windowID)
        entry.launchCallback?(NSNumber(value: -1), NSError(domain: "LiveContainerReturn", code: 410,
            userInfo: [NSLocalizedDescriptionKey: "The guest exited before its launch completed."]))
        print("[LC_RETURN] STALE_GUEST_CLEANED");
    }

    @objc class func openExistingAppWindow(dataUUID: String) -> Bool {
        if !Thread.isMainThread {
            return DispatchQueue.main.sync { openExistingAppWindow(dataUUID: dataUUID) }
        }
        for (key, entry) in Array(appDict) where entry.dataUUID == dataUUID {
            if let controller = entry.controller {
                if !controller.isAppRunning && controller.pid > 0 {
                    // Cleanup on main completes before another launch can register.
                    controller.appTerminationCleanUp()
                    appDict.removeValue(forKey: key)
                    print("[LC_RETURN] STALE_GUEST_CLEANED")
                    continue
                }
            } else if entry.pid > 0 {
                // Missing scene ownership is not a verified resume. Do not touch
                // container registration; the model's in-use check prevents duplicates.
                appDict.removeValue(forKey: key)
                print("[LC_RETURN] RETURN_FAILED reason=retained_controller_missing")
                continue
            }
            openWindow(id: "appView", value: key)
            print(entry.pid > 0 ? "[LC_RETURN] GUEST_RESUMED_EXISTING" : "[LC_RETURN] GUEST_LAUNCH_PENDING")
            return true
        }
        return false
    }



}

@available(iOS 16.1, *)
struct AppSceneViewSwiftUI: UIViewControllerRepresentable {
    @Environment(\.openWindow) private var returnOpenWindow
    let windowID: String
    @Binding var show: Bool
    let bundleId: String
    let dataUUID: String
    let initSize: CGSize
    let onAppInitialize: (Int32, Error?) -> Void
    
    class Coordinator: NSObject, AppSceneViewControllerDelegate {
        let windowID: String
        let onExit: () -> Void
        let onAppInitialize: (Int32, Error?) -> Void
        init(windowID: String, onAppInitialize: @escaping (Int32, Error?) -> Void, onExit: @escaping () -> Void) {
            self.windowID = windowID
            self.onAppInitialize = onAppInitialize
            self.onExit = onExit
        }
        
        func appSceneVCAppDidExit(_ vc: AppSceneViewController!) {
            MultitaskWindowManager.exited(vc, windowID: windowID)
            onExit()
        }
        
        func appSceneVC(_ vc: AppSceneViewController!, didInitializeWithError error: (any Error)!) {
            DispatchQueue.main.async {
                (vc.view.window?.windowScene?.statusBarManager as? LCStatusBarManager)?.nativeWindowViewController = vc
            }
            DispatchQueue.main.async {
                MultitaskWindowManager.initialized(vc, windowID: self.windowID, error: error)
                self.onAppInitialize(vc.pid, error)
            }
        }
        
        func appSceneVCWillActivateScene(_ vc: AppSceneViewController!) {
            vc.updateSettings { settings in
                guard let settings else { return }
                let defaultInsets = vc.view.window?.safeAreaInsets ?? .zero
                settings.peripheryInsets = defaultInsets
                settings.safeAreaInsetsPortrait = defaultInsets
                settings.deviceOrientation = UIDevice.current.orientation
                settings.setInterfaceOrientation(UIApplication.shared.statusBarOrientation)
                if(settings.interfaceOrientation().isLandscape) {
                    settings.setFrame(CGRect(x: 0, y: 0, width: vc.view.frame.size.height, height: vc.view.frame.size.width))
                } else {
                    settings.setFrame(CGRect(x: 0, y: 0, width: vc.view.frame.size.width, height: vc.view.frame.size.height))
                }
            }
            // fix live resize
            vc.contentView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        }
        
        func appSceneVC(_ vc: AppSceneViewController!, didUpdateFrom settings: UIMutableApplicationSceneSettings!, transitionContext context: Any!, lifecycleActionType actionType: UInt32) {
            settings.interruptionPolicy = 0
            //settings.peripheryInsets = vc.view.window?.safeAreaInsets ?? .zero
            vc.presenter.scene.updateSettings(settings, withTransitionContext: context, completion: nil)
            // Not sure what actionType 2 is, but it's only set when this scene enters foreground, so we can pass URL scheme here
            if actionType == 2, let launchUrl = UserDefaults.standard.string(forKey: "launchAppUrlScheme") {
                UserDefaults.standard.removeObject(forKey: "launchAppUrlScheme")
                vc.openURLScheme(launchUrl)
            }
        }
    }
    
    func makeCoordinator() -> Coordinator {
        Coordinator(windowID: windowID, onAppInitialize: onAppInitialize, onExit: {
            show = false
        })
    }
    
    func makeUIViewController(context: Context) -> UIViewController {
        guard let controller = AppSceneViewController(bundleId: bundleId, dataUUID: dataUUID, delegate: context.coordinator) else {
            print("[LC_RETURN] RETURN_FAILED reason=guest_controller_initialization_failed")
            return UIViewController()
        }
        MultitaskWindowManager.bind(controller, windowID: windowID)
        controller.lcActivateHost = {
            MultitaskWindowManager.activateMainScene(create: { returnOpenWindow(id: "Main") })
        }
        return controller
    }
    
    func updateUIViewController(_ vc: UIViewController, context _: Context) {
        if let vc = vc as? AppSceneViewController {
            if !show {
                vc.terminate()
            }
        }
    }
}

@available(iOS 16.1, *)
struct MultitaskAppWindow: View {
    @State var show = true
    @State var pid = 0
    @State var appInfo: MultitaskAppInfo? = nil
    @State var errorMessage: String? = nil
    @State private var hasScheduledAutoClose = false
    @State private var didRequestManualClose = false
    @EnvironmentObject var sceneDelegate: SceneDelegate
    @Environment(\.openWindow) var openWindow
    @AppStorage("LCMultitaskMode", store: LCUtils.appGroupUserDefault) var multitaskMode: MultitaskMode = .virtualWindow
    @AppStorage("LCSkipTerminatedScreen", store: LCUtils.appGroupUserDefault) var skipTerminatedScreen = false
    let pub = NotificationCenter.default.publisher(for: UIScene.didDisconnectNotification)
    init(id: String) {
        guard let appInfo = MultitaskWindowManager.appDict[id] else {
            return
        }
        _appInfo = State(initialValue: appInfo)
    }
    
    var body: some View {
        let isVirtualWindowMode = multitaskMode == .virtualWindow
        if show, let appInfo {
            GeometryReader { geometry in
                AppSceneViewSwiftUI(windowID: appInfo.windowID, show: $show, bundleId: appInfo.bundleId, dataUUID: appInfo.dataUUID, initSize: geometry.size,
                                    onAppInitialize: { pid, error in
                    DispatchQueue.main.async {
                        if error == nil {
                            self.pid = Int(pid)
                        } else {
                            self.errorMessage = error?.localizedDescription
                        }
                    }
                })
                .background(.black)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .ignoresSafeArea(.all, edges: .all)
            .navigationTitle(Text("\(appInfo.displayName) - \(String(pid))"))
            .onReceive(pub) { out in
                if let scene1 = sceneDelegate.window?.windowScene, let scene2 = out.object as? UIWindowScene, scene1 == scene2 {
                    show = false
                }
            }
            
        } else if skipTerminatedScreen && isVirtualWindowMode, appInfo != nil {
            Color.clear
                .ignoresSafeArea(.all, edges: .all)
                .onAppear {
                    guard !didRequestManualClose else { return }
                    if let appInfo {
                        MultitaskRelaunchManager.scheduleRelaunchIfNeeded(bundleId: appInfo.bundleId, dataUUID: appInfo.dataUUID, isManualTermination: false)
                    }
                    if !hasScheduledAutoClose {
                        hasScheduledAutoClose = true
                        DispatchQueue.main.async {
                            requestSceneDestruction(isManual: false)
                        }
                    }
                }
        } else {
            VStack {
                Text("lc.multitaskAppWindow.appTerminated".loc)
                    .font(.largeTitle)
                if let errorMessage {
                    Text(errorMessage)
                        .font(.system(.body, design: .monospaced))
                    Button("lc.common.copy".loc) {
                        UIPasteboard.general.string = errorMessage
                        requestSceneDestruction(isManual: true)
                    }
                    .buttonStyle(.bordered)
                }
                Button("lc.common.close".loc) {
                    requestSceneDestruction(isManual: true)
                }
                .buttonStyle(.bordered)
            }.onAppear {
                // appInfo == nil indicates this is the first scene opened in this launch. We don't want this so we open lc's main scene and close this view
                // however lc's main view may already be starting in another scene so we wait a bit before opening the main view
                // also we have to keep the view open for a little bit otherwise lc will be killed by iOS
                if appInfo == nil {
                    if DataManager.shared.model.mainWindowOpened {
                        requestSceneDestruction()
                    } else {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                            if !DataManager.shared.model.mainWindowOpened {
                                openWindow(id: "Main")
                            }
                            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                                requestSceneDestruction()
                            }
                        }
                    }
                }
            }
        }
    }
    
    private func requestSceneDestruction(isManual: Bool = false) {
        if isManual {
            didRequestManualClose = true
        }
        guard let session = sceneDelegate.window?.windowScene?.session else { return }
        UIApplication.shared.requestSceneSessionDestruction(session, options: nil) { error in
            print(error)
        }
    }
}

@objcMembers
class MultitaskRelaunchManager: NSObject {
    private static var pendingKeys: Set<String> = []
    private static let pendingLock = NSLock()
    
    static func scheduleRelaunchIfNeeded(bundleId: String, dataUUID: String, isManualTermination: Bool) {
        let defaults = LCUtils.appGroupUserDefault
        let multitaskMode = MultitaskMode(rawValue: defaults.integer(forKey: "LCMultitaskMode")) ?? .virtualWindow
        guard defaults.bool(forKey: "LCSkipTerminatedScreen"),
              defaults.bool(forKey: "LCRestartTerminatedApp"),
              multitaskMode == .virtualWindow,
              !isManualTermination else { return }
        
        let key = "\(bundleId)#\(dataUUID)"
        guard markPendingIfNeeded(key: key) else { return }
        
        Task {
            defer { clearPending(key: key) }
            try? await Task.sleep(nanoseconds: 500_000_000)
            await relaunchApp(bundleId: bundleId, dataUUID: dataUUID)
        }
    }
    
    private static func markPendingIfNeeded(key: String) -> Bool {
        pendingLock.lock()
        defer { pendingLock.unlock() }
        if pendingKeys.contains(key) {
            return false
        }
        pendingKeys.insert(key)
        return true
    }
    
    private static func clearPending(key: String) {
        pendingLock.lock()
        pendingKeys.remove(key)
        pendingLock.unlock()
    }
    
    private static func relaunchApp(bundleId: String, dataUUID: String) async {
        guard let appModel = await MainActor.run(body: { lookupAppModel(bundleId: bundleId) }),
              appModel.appInfo.lastLaunched.distance(to: .now) > 2
        else {
            return
        }
        
        do {
            try await appModel.runApp(multitask: true, containerFolderName: dataUUID)
        } catch {
            print("Failed to restart \(bundleId): \(error)")
        }
    }
    
    @MainActor private static func lookupAppModel(bundleId: String) -> LCAppModel? {
        let sharedModel = DataManager.shared.model
        if let app = sharedModel.apps.first(where: { $0.appInfo.relativeBundlePath == bundleId }) {
            return app
        }
        return sharedModel.hiddenApps.first(where: { $0.appInfo.relativeBundlePath == bundleId })
    }
}
