//
//  MultitaskDockView.swift
//  LiveContainer
//
//  Created by boa-z on 2025/6/28.
//

import Foundation
import SwiftUI
import UIKit
import Combine

import Foundation

enum LCMultitaskDockRenderedMode: Equatable {
    case expandedDockView
    case collapsedDockView
}

// A reused UIHostingController may evaluate its old root before a new virtual
// window session is assembled. Keep the dock branch unavailable until that
// session's persisted preference has selected its first visible mode.
struct LCMultitaskDockPresentationState {
    private(set) var sessionID: String?
    private(set) var firstPresentedMode: LCMultitaskDockRenderedMode?
    private(set) var firstPresentedHiddenState: Bool?
    private(set) var firstBodyEvaluationMode: LCMultitaskDockRenderedMode?

    var isReady: Bool { sessionID != nil && firstPresentedMode != nil }

    mutating func begin(sessionID: String) {
        self.sessionID = sessionID
        firstPresentedMode = nil
        firstPresentedHiddenState = nil
        firstBodyEvaluationMode = nil
    }

    @discardableResult
    mutating func markReady(sessionID: String, isCollapsed: Bool,
                            isDockHidden: Bool = false) -> LCMultitaskDockRenderedMode? {
        guard self.sessionID == sessionID, firstPresentedMode == nil else { return nil }
        let mode = LCMultitaskDockSessionState.renderedMode(isCollapsed: isCollapsed)
        firstPresentedMode = mode
        firstPresentedHiddenState = isDockHidden
        return mode
    }

    @discardableResult
    mutating func recordFirstBodyEvaluation(sessionID: String, isCollapsed: Bool) -> LCMultitaskDockRenderedMode? {
        guard self.sessionID == sessionID, isReady, firstBodyEvaluationMode == nil else { return nil }
        let mode = LCMultitaskDockSessionState.renderedMode(isCollapsed: isCollapsed)
        firstBodyEvaluationMode = mode
        return mode
    }

    mutating func end(sessionID: String?) {
        guard sessionID != nil, self.sessionID == sessionID else { return }
        self.sessionID = nil
        firstPresentedMode = nil
        firstBodyEvaluationMode = nil
    }
}

// The dock singleton outlives multitasking sessions. This model owns the
// one-time first-frame preference and the user override for each fresh session.
struct LCMultitaskDockSessionState {
    private(set) var sessionID: String?
    private var storedPreference = false
    private var storedTuckedPreference = false
    private var initialPreferenceApplied = false
    private var initialTuckedPreferenceApplied = false
    private(set) var manuallyOverridden = false
    private(set) var wasPresented = false

    var isActiveSession: Bool { sessionID != nil }

    static func renderedMode(isCollapsed: Bool) -> LCMultitaskDockRenderedMode {
        isCollapsed ? .collapsedDockView : .expandedDockView
    }

    mutating func begin(storedPreference: Bool, storedTuckedPreference: Bool = false) -> String {
        let id = UUID().uuidString
        sessionID = id
        self.storedPreference = storedPreference
        self.storedTuckedPreference = storedTuckedPreference
        initialPreferenceApplied = false
        initialTuckedPreferenceApplied = false
        manuallyOverridden = false
        wasPresented = false
        return id
    }

    mutating func markPresented(sessionID id: String) -> Bool {
        guard sessionID == id, initialPreferenceApplied, !wasPresented else { return false }
        wasPresented = true
        return true
    }

    mutating func applyBeforeFirstFrame(sessionID id: String) -> Bool? {
        guard sessionID == id, !initialPreferenceApplied else { return nil }
        initialPreferenceApplied = true
        return manuallyOverridden ? nil : storedPreference
    }

    // The edge-tuck setting is independent of collapsed rendering. It is read
    // once with the session and never re-applied during layout or rotation.
    mutating func applyTuckedBeforeFirstFrame(sessionID id: String) -> Bool? {
        guard sessionID == id, !initialTuckedPreferenceApplied else { return nil }
        initialTuckedPreferenceApplied = true
        return storedTuckedPreference
    }

    mutating func userDidToggle() {
        guard sessionID != nil else { return }
        manuallyOverridden = true
    }

    mutating func end() {
        sessionID = nil
        initialPreferenceApplied = false
        initialTuckedPreferenceApplied = false
        storedTuckedPreference = false
        manuallyOverridden = false
        wasPresented = false
    }
}


// MARK: - App Info Provider
class AppInfoProvider {
    
    static let shared = AppInfoProvider()
    
    private var infoCacheByUUID = [String: LCAppInfo]()
    private var infoCacheByName = [String: LCAppInfo]()
    private let cacheQueue = DispatchQueue(label: "com.livecontainer.appinfoprovider.cachequeue", attributes: .concurrent)
    
    private init() {}
    
    public func findAppInfo(appName: String, dataUUID: String) -> LCAppInfo? {
        if let appInfo = findAppInfoFromSharedModel(appName: appName, dataUUID: dataUUID) {
            return appInfo
        }
        if let appInfo = findAppInfo(byUUID: dataUUID) {
            return appInfo
        }
        return findAppInfo(byName: appName)
    }
    
    public func findAppInfo(byUUID dataUUID: String) -> LCAppInfo? {
        if let cachedInfo = cacheQueue.sync(execute: { infoCacheByUUID[dataUUID] }) {
            return cachedInfo
        }
        
        guard let appGroupPath = LCSharedUtils.appGroupPath()?.path else { return nil }
        
        let searchPaths = [
            "\(appGroupPath)/LiveContainer/Data/Application/\(dataUUID)/LCAppInfo.plist",
            "\(appGroupPath)/Containers/\(dataUUID)/LCAppInfo.plist",
            "\(FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?.path ?? "")/Data/Application/\(dataUUID)/LCAppInfo.plist"
        ]
        
        for path in searchPaths {
            if FileManager.default.fileExists(atPath: path),
               let appInfoDict = NSDictionary(contentsOfFile: path),
               let bundlePath = appInfoDict["bundlePath"] as? String,
               let appInfo = LCAppInfo(bundlePath: bundlePath) {
                
                cacheQueue.async(flags: .barrier) { self.infoCacheByUUID[dataUUID] = appInfo }
                return appInfo
            }
        }
        return nil
    }

    public func findAppInfo(byName appName: String) -> LCAppInfo? {
        if let cachedInfo = cacheQueue.sync(execute: { infoCacheByName[appName] }) {
            return cachedInfo
        }

        var searchPaths: [String] = []
        if let appGroupPath = LCSharedUtils.appGroupPath()?.path {
            searchPaths.append("\(appGroupPath)/LiveContainer/Applications")
        }
        if let docPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?.path {
            searchPaths.append("\(docPath)/Applications")
        }

        for appsPath in searchPaths {
            guard let appDirs = try? FileManager.default.contentsOfDirectory(atPath: appsPath) else { continue }
            
            for appDir in appDirs where appDir.hasSuffix(".app") {
                if let appInfo = LCAppInfo(bundlePath: "\(appsPath)/\(appDir)"), appInfo.displayName() == appName {
                    cacheQueue.async(flags: .barrier) { self.infoCacheByName[appName] = appInfo }
                    return appInfo
                }
            }
        }
        return nil
    }

    private func findAppInfoFromSharedModel(appName: String, dataUUID: String) -> LCAppInfo? {
        let allApps = DataManager.shared.model.apps + DataManager.shared.model.hiddenApps
        
        for appModel in allApps {
            if appModel.appInfo.containers.contains(where: { $0.folderName == dataUUID }) {
                return appModel.appInfo
            }
        }
        
        for appModel in allApps {
            if appModel.appInfo.displayName() == appName {
                return appModel.appInfo
            }
        }
        return nil
    }
    
    public func clearCache() {
        cacheQueue.async(flags: .barrier) {
            self.infoCacheByUUID.removeAll()
            self.infoCacheByName.removeAll()
        }
    }
}

// MARK: - App Model for Dock
@objc class DockAppModel: NSObject, ObservableObject, Identifiable {
    let id = UUID()
    @objc let appName: String
    @objc let appUUID: String
    let appInfo: LCAppInfo?
    let view: UIView?
    
    @objc init(appName: String, appUUID: String, appInfo: LCAppInfo? = nil, view: UIView?) {
        self.appName = appName
        self.appUUID = appUUID
        self.appInfo = appInfo
        self.view = view
        super.init()
    }
}

// MARK: - MultitaskDockView Manager
@available(iOS 16.0, *)
@objc public class MultitaskDockManager: NSObject, ObservableObject {
    @objc public static let shared = MultitaskDockManager()
    
    @Published var apps: [DockAppModel] = []
    @Published var isVisible: Bool = false
    @Published @objc var isCollapsed: Bool = false
    private var v3CollapseObserver: AnyCancellable?
    @Published var isDockHidden: Bool = false
    @Published var settingsChanged: Bool = false
    // MULTITASK_DOCK_SESSION_APPLY_V2: session identity survives singleton reuse.
    // MULTITASK_DOCK_PRESENTATION_GATE_V1: do not expose a reused root branch before session preference is committed.
    @Published private(set) var v3DockPresentationState = LCMultitaskDockPresentationState()
    private var collapseStartState = LCMultitaskDockSessionState()
    var renderedDockMode: LCMultitaskDockRenderedMode {
        LCMultitaskDockSessionState.renderedMode(isCollapsed: isCollapsed)
    }
    private var firstRenderedDockSessionID: String?
    private var firstBodyEvaluationSessionID: String?
    private var firstPresentedBodySessionID: String?
    private var didLogPreSessionBodyEvaluation = false
    func v3RecordFirstDockBodyEvaluation() -> EmptyView {
        guard let sessionID = v3DockPresentationState.sessionID else {
            if !didLogPreSessionBodyEvaluation {
                didLogPreSessionBodyEvaluation = true
                // MULTITASK_DOCK_BODY_EVALUATION_V1: records the real host-root body evaluation before any multitask session exists.
                NSLog("[LC_DOCK] BODY_EVALUATION_FIRST manager=%@ session=none stored_preference=%d suite=%@ apps_count=%ld isCollapsed=%d branch=suppressed_no_session ready=0", String(describing: ObjectIdentifier(self)), LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, (LCSharedUtils.appGroupID() ?? "unavailable"), apps.count, isCollapsed ? 1 : 0)
            }
            return EmptyView()
        }
        if firstBodyEvaluationSessionID != sessionID {
            firstBodyEvaluationSessionID = sessionID
            // MULTITASK_DOCK_BODY_EVALUATION_V1: emitted synchronously during the concrete host-root body evaluation.
            NSLog("[LC_DOCK] BODY_EVALUATION_FIRST manager=%@ session=%@ stored_preference=%d stored_tucked=%d suite=%@ apps_count=%ld isCollapsed=%d isDockHidden=%d branch=%@ ready=%d", String(describing: ObjectIdentifier(self)), sessionID, LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsTuckedToEdge") ? 1 : 0, (LCSharedUtils.appGroupID() ?? "unavailable"), apps.count, isCollapsed ? 1 : 0, isDockHidden ? 1 : 0, v3DockPresentationState.isReady ? (isCollapsed ? "CollapsedDockView" : "ExpandedDockView") : "suppressed_waiting_for_session", v3DockPresentationState.isReady ? 1 : 0)
        }
        if v3DockPresentationState.isReady, firstPresentedBodySessionID != sessionID,
           let mode = v3DockPresentationState.recordFirstBodyEvaluation(sessionID: sessionID, isCollapsed: isCollapsed) {
            firstPresentedBodySessionID = sessionID
            NSLog("[LC_DOCK] BODY_BRANCH_SELECTED_FIRST manager=%@ session=%@ apps_count=%ld isCollapsed=%d branch=%@", String(describing: ObjectIdentifier(self)), sessionID, apps.count, isCollapsed ? 1 : 0, mode == .collapsedDockView ? "CollapsedDockView" : "ExpandedDockView")
        }
        return EmptyView()
    }
    func v3RecordFirstRenderedDockView(_ mode: LCMultitaskDockRenderedMode) {
        guard let sessionID = collapseStartState.sessionID, firstRenderedDockSessionID != sessionID else { return }
        firstRenderedDockSessionID = sessionID
        // MULTITASK_DOCK_BODY_FIRST_RENDER_V1: emitted from the concrete SwiftUI branch on first appearance.
        NSLog("[LC_DOCK] BODY_FIRST_RENDER manager=%@ session=%@ apps_count=%ld isCollapsed=%d branch=%@", String(describing: ObjectIdentifier(self)), sessionID, apps.count, isCollapsed ? 1 : 0, mode == .collapsedDockView ? "CollapsedDockView" : "ExpandedDockView")
    }

    @objc public var windowHostingView = VirtualWindowsHostView()
    internal var hostingController: UIHostingController<AnyView>?

    public struct Constants {
        // MARK: - Layout & Sizing
        static let defaultDockWidth: CGFloat = 90.0
        static let minAdaptiveDockWidth: CGFloat = 50.0
        static let minAdaptiveIconSize: CGFloat = 10.0
        static let maxIconSize: CGFloat = 100.0
        static let minCollapsedHeight: CGFloat = 60.0
        static let minCollapsedButtonSize: CGFloat = 44.0
        static let maxCollapsedButtonSize: CGFloat = 80.0
        static let initialDockShowHeight: CGFloat = 120.0

        // MARK: - Margins & Padding
        static let adaptiveWidthVerticalMargin: CGFloat = 20.0
        static let dockVerticalMargin: CGFloat = 30.0
        static let dockContentSpacing: CGFloat = 8.0
        static let dockVerticalPadding: CGFloat = 30.0
        // Extra padding is derived from dockVerticalPadding to match the SwiftUI layout exactly
        
        // MARK: - Ratios & Factors
        static let iconToWidthRatio: CGFloat = 0.75
        static let collapsedButtonToWidthRatio: CGFloat = 0.7
        static let maxHeightRatioOfAvailableArea: CGFloat = 0.85
        
        // MARK: - Animation & Interaction
        static var dockHiddenOffset: CGFloat {
            get {
                let ans = LCUtils.appGroupUserDefault.double(forKey: "LCDockWidth")
                if ans != 0 {
                    return ans * 2 / 3
                } else {
                    return 50
                }
            }
        }
        static var hideGestureThreshold: CGFloat {
            get {
                let ans = LCUtils.appGroupUserDefault.double(forKey: "LCDockWidth")
                if ans != 0 {
                    return ans / 5
                } else {
                    return 16
                }
            }
        }
        static let edgeSwipeThreshold: CGFloat = 30.0
        
        static let standardAnimationDuration: TimeInterval = 0.3
        static let longAnimationDuration: TimeInterval = 0.4
        static let shortAnimationDuration1: TimeInterval = 0.15
        static let shortAnimationDuration2: TimeInterval = 0.1
        
        static let standardSpringDamping: CGFloat = 0.8
        static let showHideSpringDamping: CGFloat = 0.7
        static let standardSpringVelocity: CGFloat = 0.3
        static let showHideSpringVelocity: CGFloat = 0.5
        
        static let initialScale: CGFloat = 0.8
        static let bringToFrontScale: CGFloat = 1.02
    }
    
    // Original dock width from user settings (without auto-adjustment)
    private var originalDockWidth: CGFloat {
        let storedValue = LCUtils.appGroupUserDefault.double(forKey: "LCDockWidth")
        return storedValue > 0 ? CGFloat(storedValue) : Constants.defaultDockWidth
    }
    
    // Calculate adaptive dock width (auto-adjust when exceeding safe area)
    public var dockWidth: CGFloat {
        guard !apps.isEmpty else { return originalDockWidth }
        
        let totalVerticalMargin = Constants.adaptiveWidthVerticalMargin * 2
        let availableHeight = self.safeAreaHeight - totalVerticalMargin
        
        let maxSafeHeight = availableHeight * Constants.maxHeightRatioOfAvailableArea
        
        let userWidth = originalDockWidth
        let iconSize = calculateIconSize(for: userWidth)
        let requiredHeight = expandedDockHeight(for: userWidth, iconSize: iconSize)
        
        if requiredHeight > maxSafeHeight && !apps.isEmpty {
            let buttonSize = calculateButtonSize(for: userWidth)
            let baseHeight = expandedDockBaseHeight(for: userWidth, buttonSize: buttonSize)
            let availableForIcons = maxSafeHeight - baseHeight
            let maxAllowedIconSize = availableForIcons / CGFloat(apps.count)
            
            let targetIconSize = max(Constants.minAdaptiveIconSize, maxAllowedIconSize)
            
            let targetWidth = targetIconSize / Constants.iconToWidthRatio
            
            return max(Constants.minAdaptiveDockWidth, targetWidth)
        }
        
        return userWidth
    }
    
    // Calculate icon size based on dock width
    private func calculateIconSize(for width: CGFloat) -> CGFloat {
        let iconSize = width * Constants.iconToWidthRatio
        return max(Constants.minAdaptiveIconSize, min(Constants.maxIconSize, iconSize))
    }

    private func calculateButtonSize(for width: CGFloat) -> CGFloat {
        let targetSize = width * Constants.collapsedButtonToWidthRatio
        return max(Constants.minCollapsedButtonSize, min(Constants.maxCollapsedButtonSize, targetSize))
    }

    private func expandedDockBaseHeight(for width: CGFloat, buttonSize: CGFloat) -> CGFloat {
        let spacingCount = max(self.apps.count + 1, 0)
        let totalSpacingHeight = CGFloat(spacingCount) * Constants.dockContentSpacing
        return Constants.dockVerticalPadding + buttonSize * 2 + totalSpacingHeight
    }

    private func expandedDockHeight(for width: CGFloat, iconSize: CGFloat) -> CGFloat {
        let buttonSize = calculateButtonSize(for: width)
        let baseHeight = expandedDockBaseHeight(for: width, buttonSize: buttonSize)
        let iconHeight = CGFloat(self.apps.count) * iconSize
        return baseHeight + iconHeight
    }

    private func collapsedDockHeight(for width: CGFloat) -> CGFloat {
        let buttonSize = calculateButtonSize(for: width)
        return Constants.dockVerticalPadding + buttonSize
    }
    

    // Calculate adaptive icon size
    public var adaptiveIconSize: CGFloat {
        return calculateIconSize(for: dockWidth)
    }

    public var keyWindow: UIWindow? {
        (UIApplication.shared.connectedScenes.first as? UIWindowScene)?.windows.first
    }

    public var safeAreaInsets: UIEdgeInsets {
        if #available(iOS 11.0, *) {
            return keyWindow?.safeAreaInsets ?? .zero
        }
        return .zero
    }

    private var safeAreaHeight: CGFloat {
        keyWindow!.bounds.height - safeAreaInsets.top - safeAreaInsets.bottom
    }
    
    override init() {
        super.init()
        // MULTITASK_DOCK_START_COLLAPSED_V3: initialize before setupDockView can create its first SwiftUI root.
        let stored = LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed")
        self.isCollapsed = stored
        // MULTITASK_DOCK_COLLAPSE_OBSERVER_V1: capture every later mutation, including reset/reuse paths.
        self.v3CollapseObserver = self.$isCollapsed.dropFirst().sink { [weak self] value in
            guard let self else { return }
            NSLog("[LC_DOCK] IS_COLLAPSED_PUBLISHED manager=%@ session=%@ stored_preference=%d suite=%@ apps_count=%ld value=%d ready=%d", String(describing: ObjectIdentifier(self)), self.collapseStartState.sessionID ?? "none", LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, (LCSharedUtils.appGroupID() ?? "unavailable"), self.apps.count, value ? 1 : 0, self.v3DockPresentationState.isReady ? 1 : 0)
        }
        NSLog("[LC_DOCK] INIT manager=%@ suite=%@ stored_preference=%d apps_count=%ld isCollapsed=%d", String(describing: ObjectIdentifier(self)), (LCSharedUtils.appGroupID() ?? "unavailable"), stored ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0)
        keyWindow!.rootViewController!.view.subviews.first!.addSubview(self.windowHostingView)
        NSLog("[LC_DOCK] BEFORE_SETUP_DOCK_VIEW manager=%@ suite=%@ stored_preference=%d apps_count=%ld isCollapsed=%d session=%@", String(describing: ObjectIdentifier(self)), (LCSharedUtils.appGroupID() ?? "unavailable"), LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.collapseStartState.sessionID ?? "none")
        setupDockView()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(userDefaultsDidChange),
            name: UserDefaults.didChangeNotification,
            object: LCUtils.appGroupUserDefault
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(deviceOrientationDidChange),
            name: UIDevice.orientationDidChangeNotification,
            object: nil
        )
    }
    
    deinit {
        NotificationCenter.default.removeObserver(self)
        NotificationCenter.default.removeObserver(self, name: UIDevice.orientationDidChangeNotification, object: nil)
    }

    @objc private func deviceOrientationDidChange() {
        DispatchQueue.main.async {
            if self.isVisible {
                self.updateDockFrame()
            }
        }
    }
    
    @objc private func userDefaultsDidChange() {
        DispatchQueue.main.async {
            self.settingsChanged.toggle()
            if self.isVisible {
                self.updateDockFrame()
            }
        }
    }
    
    private func setupDockView() {
        NSLog("[LC_DOCK] SETUP_DOCK_VIEW manager=%@ suite=%@ stored_preference=%d apps_count=%ld isCollapsed=%d session=%@", String(describing: ObjectIdentifier(self)), (LCSharedUtils.appGroupID() ?? "unavailable"), LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.collapseStartState.sessionID ?? "none")
        DispatchQueue.main.async {
            NSLog("[LC_DOCK] SETUP_ROOT_CREATE manager=%@ suite=%@ stored_preference=%d session=%@ apps_count=%ld isCollapsed=%d ready=%d", String(describing: ObjectIdentifier(self)), (LCSharedUtils.appGroupID() ?? "unavailable"), LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, self.collapseStartState.sessionID ?? "none", self.apps.count, self.isCollapsed ? 1 : 0, self.v3DockPresentationState.isReady ? 1 : 0)
            let dockView = AnyView(MultitaskDockSwiftView()
                .environmentObject(self))
            
            self.hostingController = UIHostingController(rootView: dockView)
            self.hostingController?.view.autoresizingMask = [.flexibleTopMargin, .flexibleLeftMargin, .flexibleRightMargin, .flexibleBottomMargin]
            self.hostingController?.view.backgroundColor = .clear
            NSLog("[LC_DOCK] HOSTING_ROOT_CREATED manager=%@ host=%@ suite=%@ stored_preference=%d session=%@ apps_count=%ld isCollapsed=%d ready=%d", String(describing: ObjectIdentifier(self)), self.hostingController.map { String(describing: ObjectIdentifier($0)) } ?? "none", (LCSharedUtils.appGroupID() ?? "unavailable"), LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, self.collapseStartState.sessionID ?? "none", self.apps.count, self.isCollapsed ? 1 : 0, self.v3DockPresentationState.isReady ? 1 : 0)
            // MULTITASK_DOCK_SETUP_PRESENT_V1: the app-add queue can beat host-controller creation.
            if !self.apps.isEmpty { self.showDock() }
        }
    }

    private func updateDockFrame(animated: Bool = true) {
        guard let hostingController = hostingController else { return }

        let screenBounds = keyWindow!.bounds
        let currentDockWidth = self.dockWidth
        
        let dockHeight = calculateTargetDockHeight(forWidth: currentDockWidth)

        let currentFrame = hostingController.view.frame
        let isOnRightSide = (currentFrame.midX > screenBounds.width / 2) || (currentFrame.isEmpty)
        let targetX = calculateTargetX(isDockHidden: self.isDockHidden, 
                                    isOnRightSide: isOnRightSide, 
                                    dockWidth: currentDockWidth, 
                                    screenWidth: screenBounds.width)

        let targetY = calculateTargetY(for: currentFrame, 
                                    dockHeight: dockHeight, 
                                    screenHeight: screenBounds.height)
        
        let newFrame = CGRect(x: targetX, y: targetY, width: currentDockWidth, height: dockHeight)
        
        applyNewFrame(newFrame, for: hostingController, animated: animated)
    }

    // MARK: - Frame Calculation Helpers

    private func calculateTargetDockHeight(forWidth width: CGFloat) -> CGFloat {
        if isCollapsed {
            let collapsedHeight = collapsedDockHeight(for: width)
            return max(Constants.minCollapsedHeight, collapsedHeight)
        } else {
            let currentIconSize = calculateIconSize(for: width)
            return expandedDockHeight(for: width, iconSize: currentIconSize)
        }
    }

    func calculateTargetX(isDockHidden: Bool, isOnRightSide: Bool, dockWidth: CGFloat, screenWidth: CGFloat) -> CGFloat {

        let safeInsets = self.safeAreaInsets
        var ans : CGFloat
        if isOnRightSide {
            ans = screenWidth - dockWidth
            if self.hostingController?.view.window?.windowScene?.interfaceOrientation == UIInterfaceOrientation.landscapeLeft {
                ans -= safeInsets.right
            }
            
            if isDockHidden {
                ans += Constants.dockHiddenOffset
            }
        } else {
            ans = 0
            if self.hostingController?.view.window?.windowScene?.interfaceOrientation == UIInterfaceOrientation.landscapeRight {
                ans += safeInsets.left
            }
            if isDockHidden {
                ans -= Constants.dockHiddenOffset
            }
        }
        
        return ans;

    }

    private func calculateTargetY(for currentFrame: CGRect, dockHeight: CGFloat, screenHeight: CGFloat) -> CGFloat {
        let safeAreaMinY = self.safeAreaInsets.top + Constants.dockVerticalMargin
        let safeAreaMaxY = screenHeight - self.safeAreaInsets.bottom - dockHeight - Constants.dockVerticalMargin
        
        if currentFrame.height > 0 {
            let desiredY = currentFrame.midY - dockHeight / 2
            return max(safeAreaMinY, min(safeAreaMaxY, desiredY))
        } else {
            let safeAreaCenterY = safeAreaMinY + (safeAreaMaxY - safeAreaMinY) / 2
            return max(safeAreaMinY, min(safeAreaMaxY, safeAreaCenterY - dockHeight / 2))
        }
    }

    private func applyNewFrame(_ newFrame: CGRect, for hostingController: UIHostingController<AnyView>, animated: Bool) {
        if animated {
            UIView.animate(
                withDuration: Constants.standardAnimationDuration,
                delay: 0,
                usingSpringWithDamping: Constants.standardSpringDamping,
                initialSpringVelocity: Constants.standardSpringVelocity,
                options: .curveEaseOut
            ) {
                hostingController.view.frame = newFrame
            }
        } else {
            hostingController.view.frame = newFrame
        }
    }
    
    @objc public func addRunningApp(_ appName: String, appUUID: String, view: UIView?) {
        let appInfo = AppInfoProvider.shared.findAppInfo(appName: appName, dataUUID: appUUID)
        addRunningAppWithInfo(appInfo, appUUID: appUUID, view: view)
    }
    
    @objc public func removeRunningApp(_ appUUID: String) {
        if !Thread.isMainThread {
            DispatchQueue.main.async { self.removeRunningApp(appUUID) }
            return
        }
        self.apps.removeAll { $0.appUUID == appUUID }
        if self.apps.isEmpty {
            // MULTITASK_DOCK_SESSION_APPLY_V2: a later session re-reads the preference.
            NSLog("[LC_DOCK] SESSION_END manager=%@ id=%@ apps_count=%ld isCollapsed=%d", String(describing: ObjectIdentifier(self)), self.collapseStartState.sessionID ?? "none", self.apps.count, self.isCollapsed ? 1 : 0)
            self.v3DockPresentationState.end(sessionID: self.collapseStartState.sessionID)
            self.collapseStartState.end()
            self.hideDock()
        }
        else if self.isVisible { self.updateDockFrame() }
    }

    @objc public func showDock() {
        NSLog("[LC_DOCK] BEFORE_SHOW_BLOCK manager=%@ session=%@ stored_preference=%d apps_count=%ld isCollapsed=%d ready=%d", String(describing: ObjectIdentifier(self)), self.collapseStartState.sessionID ?? "none", LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.v3DockPresentationState.isReady ? 1 : 0)
        guard isDockEnabled() else { return }
        guard !isVisible, let hostingController = hostingController else { return }
        
        guard let keyWindow = self.keyWindow else { return }
        
        DispatchQueue.main.async {
            // MULTITASK_DOCK_PREF_BEFORE_MOUNT_V1: re-read/apply before the host's first visible mount.
            NSLog("[LC_DOCK] SHOW_BLOCK_ENTER manager=%@ session=%@ host=%@ suite=%@ stored_preference=%d stored_tucked=%d apps_count=%ld isCollapsed=%d isDockHidden=%d ready=%d", String(describing: ObjectIdentifier(self)), self.collapseStartState.sessionID ?? "none", String(describing: ObjectIdentifier(hostingController)), (LCSharedUtils.appGroupID() ?? "unavailable"), LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsTuckedToEdge") ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.isDockHidden ? 1 : 0, self.v3DockPresentationState.isReady ? 1 : 0)
            if !self.collapseStartState.isActiveSession {
                let stored = LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed")
                let storedTucked = LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsTuckedToEdge")
                let sessionID = self.collapseStartState.begin(storedPreference: stored, storedTuckedPreference: storedTucked)
                self.v3DockPresentationState.begin(sessionID: sessionID)
                NSLog("[LC_DOCK] SESSION_BEGIN_IN_SHOW manager=%@ session=%@ suite=%@ stored_preference=%d stored_tucked=%d apps_count=%ld isCollapsed=%d isDockHidden=%d", String(describing: ObjectIdentifier(self)), sessionID, (LCSharedUtils.appGroupID() ?? "unavailable"), stored ? 1 : 0, storedTucked ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.isDockHidden ? 1 : 0)
                if let initialHidden = self.collapseStartState.applyTuckedBeforeFirstFrame(sessionID: sessionID) { self.isDockHidden = initialHidden }
            }
            if let sessionID = self.collapseStartState.sessionID, !self.collapseStartState.wasPresented {
                if let initial = self.collapseStartState.applyBeforeFirstFrame(sessionID: sessionID) { self.isCollapsed = initial }
                if let initialHidden = self.collapseStartState.applyTuckedBeforeFirstFrame(sessionID: sessionID) { self.isDockHidden = initialHidden }
                let firstMode = self.v3DockPresentationState.markReady(sessionID: sessionID, isCollapsed: self.isCollapsed, isDockHidden: self.isDockHidden)
                NSLog("[LC_DOCK] FIRST_PRESENTED_VIEW manager=%@ session=%@ first=%d stored_preference=%d stored_tucked=%d apps_count=%ld isCollapsed=%d isDockHidden=%d branch=%@", String(describing: ObjectIdentifier(self)), sessionID, firstMode == nil ? 0 : 1, LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsTuckedToEdge") ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.isDockHidden ? 1 : 0, firstMode == .collapsedDockView ? "CollapsedDockView" : "ExpandedDockView")
                // MULTITASK_DOCK_PRESENTATION_GATE_V1: the blank branch stays selected until the preference has been committed.
                hostingController.rootView = AnyView(MultitaskDockSwiftView().environmentObject(self).id(sessionID))
                NSLog("[LC_DOCK] ROOT_REUSED_FOR_SESSION manager=%@ host=%@ session=%@ suite=%@ stored_preference=%d apps_count=%ld isCollapsed=%d ready=%d", String(describing: ObjectIdentifier(self)), String(describing: ObjectIdentifier(hostingController)), sessionID, (LCSharedUtils.appGroupID() ?? "unavailable"), LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.v3DockPresentationState.isReady ? 1 : 0)
                let firstPresentation = self.collapseStartState.markPresented(sessionID: sessionID)
                NSLog("[LC_DOCK] FIRST_FRAME_ARMED manager=%@ session=%@ first=%d ready=%d isCollapsed=%d", String(describing: ObjectIdentifier(self)), sessionID, firstPresentation ? 1 : 0, self.v3DockPresentationState.isReady ? 1 : 0, self.isCollapsed ? 1 : 0)
            }
            NSLog("[LC_DOCK] SHOW_BLOCK_EXECUTED manager=%@ session=%@ host=%@ suite=%@ stored_preference=%d stored_tucked=%d apps_count=%ld isCollapsed=%d isDockHidden=%d branch=%@ ready=%d", String(describing: ObjectIdentifier(self)), self.collapseStartState.sessionID ?? "none", String(describing: ObjectIdentifier(hostingController)), (LCSharedUtils.appGroupID() ?? "unavailable"), LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsTuckedToEdge") ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.isDockHidden ? 1 : 0, self.renderedDockMode == .collapsedDockView ? "CollapsedDockView" : "ExpandedDockView", self.v3DockPresentationState.isReady ? 1 : 0)
            self.isVisible = true
            
            let screenBounds = keyWindow.bounds
            let currentDockWidth = self.dockWidth
            let initialHeight = Constants.initialDockShowHeight
            
            // If not already in view hierarchy, add it
            if hostingController.view.superview == nil {
                keyWindow.addSubview(hostingController.view)
                hostingController.view.frame = CGRect(
                    x: screenBounds.width - currentDockWidth,
                    y: (screenBounds.height - initialHeight) / 2,
                    width: currentDockWidth,
                    height: initialHeight
                )
            }
            
            NSLog("[LC_DOCK] BEFORE_FIRST_FRAME manager=%@ session=%@ suite=%@ stored_preference=%d stored_tucked=%d apps_count=%ld isCollapsed=%d isDockHidden=%d branch=%@ ready=%d", String(describing: ObjectIdentifier(self)), self.collapseStartState.sessionID ?? "none", (LCSharedUtils.appGroupID() ?? "unavailable"), LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed") ? 1 : 0, LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsTuckedToEdge") ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.isDockHidden ? 1 : 0, self.renderedDockMode == .collapsedDockView ? "CollapsedDockView" : "ExpandedDockView", self.v3DockPresentationState.isReady ? 1 : 0)
            self.updateDockFrame(animated: false) 
            
            self.setupEdgeGestureRecognizers()
            
            hostingController.view.alpha = 0
            let initialScale = Constants.initialScale
            hostingController.view.transform = CGAffineTransform(scaleX: initialScale, y: initialScale)
            
            UIView.animate(
                withDuration: Constants.standardAnimationDuration,
                delay: 0,
                usingSpringWithDamping: Constants.showHideSpringDamping,
                initialSpringVelocity: Constants.showHideSpringVelocity,
                options: .curveEaseOut
            ) {
                hostingController.view.alpha = 1
                hostingController.view.transform = .identity
            }
        }
    }
    
    @objc public func hideDock() {
        guard isVisible, let hostingController = hostingController else { return }
        
        DispatchQueue.main.async {
            UIView.animate(
                withDuration: Constants.standardAnimationDuration,
                delay: 0,
                usingSpringWithDamping: Constants.showHideSpringDamping,
                initialSpringVelocity: Constants.showHideSpringVelocity,
                options: .curveEaseOut
            ) {
                hostingController.view.alpha = 0
                let finalScale = Constants.initialScale
                hostingController.view.transform = CGAffineTransform(scaleX: finalScale, y: finalScale)
                // Move off-screen to hide, but keep in view hierarchy
                let screenBounds = self.keyWindow!.bounds
                let currentDockWidth = self.dockWidth
                let targetX = self.calculateTargetX(isDockHidden: true, isOnRightSide: hostingController.view.frame.midX > screenBounds.width / 2, dockWidth: currentDockWidth, screenWidth: screenBounds.width)
                let targetY = hostingController.view.frame.origin.y // Keep current Y
                hostingController.view.frame.origin = CGPoint(x: targetX, y: targetY)
            } completion: { _ in
                self.isVisible = false
                hostingController.view.transform = .identity
                // MULTITASK_DOCK_RESHOW_AFTER_TRANSITION_V1: preserve a new session arriving during hide.
                if !self.apps.isEmpty { self.showDock() }
            }
        }
    }

    @objc public func animateFrame(to finalFrame: CGRect) {
        guard let hostingController = self.hostingController else { return }
        
        UIView.animate(
            withDuration: Constants.standardAnimationDuration,
            delay: 0,
            usingSpringWithDamping: Constants.standardSpringDamping,
            initialSpringVelocity: Constants.standardSpringVelocity,
            options: .curveEaseOut
        ) {
            hostingController.view.frame = finalFrame
        }
    }

    @objc public func updateFrameAfterAnimation(finalOffset: CGSize) {
        guard let hostingController = self.hostingController else { return }
        
        let newFrame = hostingController.view.frame.offsetBy(dx: finalOffset.width, dy: finalOffset.height)
        
        hostingController.view.frame = newFrame
    }

    func handleSwipeToHideOrShowGesture(for originalFrame: CGRect, translation: CGSize) -> Bool {
        let screenWidth = keyWindow!.bounds.width
        let isOnRightSide = originalFrame.origin.x > screenWidth / 2
        let isSwipingAway = (isOnRightSide && translation.width > 0) || (!isOnRightSide && translation.width < 0)
        
        if isSwipingAway {
            guard !self.isDockHidden else { return false }
            self.hideDockToSide()
            let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
            impactFeedback.impactOccurred()
            return true
        } else {
            guard self.isDockHidden else { return false }
            self.showDockFromHidden()
            let impactFeedback = UIImpactFeedbackGenerator(style: .light)
            impactFeedback.impactOccurred()
            return true
        }
    }
    
    // Check if gesture is for cross-screen movement (left to right or vice versa)
    func isPositionChangeGesture(for originalFrame: CGRect, translation: CGSize) -> Bool {
        let horizontalDistance = abs(translation.width)
        let verticalDistance = abs(translation.height)
        
        guard !self.isDockHidden, horizontalDistance > verticalDistance else {
            return false
        }
        
        let screenWidth = keyWindow!.bounds.width
        let isOnRightSide = originalFrame.origin.x > screenWidth / 2
        
        guard !self.isDockHidden else { return false }
        
        let isMovingToOtherSide = (isOnRightSide && translation.width < 0) || (!isOnRightSide && translation.width > 0)
        guard isMovingToOtherSide else { return false }
        
        let draggedX = originalFrame.origin.x + translation.width
        let screenCenter = screenWidth / 2
        
        if isOnRightSide {
            return draggedX < screenCenter
        } else {
            return (draggedX + originalFrame.width) > screenCenter
        }
    }
    
    // Find and bring corresponding multitask view to front

    func bringMultitaskViewToFront(uuid: String, from center: CGPoint? = nil) -> Bool {
        guard let targetView = apps.first(where: { $0.appUUID == uuid })?.view,
              let controller = targetView._viewDelegate() as? DecoratedAppSceneViewController else { return false }
        if !controller.appSceneVC.isAppRunning && controller.appSceneVC.pid > 0 {
            controller.appSceneVC.appTerminationCleanUp()
            // Upstream may intentionally retain the terminated-screen row.
            // Remove that exact old row before registering its replacement.
            removeRunningApp(uuid)
            controller.willMove(toParent: nil)
            targetView.removeFromSuperview()
            controller.removeFromParent()
            print("[LC_RETURN] STALE_GUEST_CLEANED")
            return false
        }
        guard let window = targetView.window else {
            print("[LC_RETURN] RETURN_FAILED reason=retained_view_has_no_window")
            return false
        }
        passURLSchemeToView(targetView)
        animateViewAppearance(targetView, from: center, in: window)
        print(controller.appSceneVC.pid > 0 ? "[LC_RETURN] GUEST_RESUMED_EXISTING" : "[LC_RETURN] GUEST_LAUNCH_PENDING")
        return true
    }


    private func passURLSchemeToView(_ view: UIView) {
        if let launchUrl = UserDefaults.standard.string(forKey: "launchAppUrlScheme") {
            UserDefaults.standard.removeObject(forKey: "launchAppUrlScheme")
            if let decoratedVC = view._viewDelegate() as? DecoratedAppSceneViewController {
                decoratedVC.appSceneVC.openURLScheme(launchUrl)
            }
        }
    }

    private func animateViewAppearance(_ view: UIView, from center: CGPoint?, in window: UIWindow) {
        let isHidden = view.isHidden || view.alpha < 0.1
        let decoratedVC = view._viewDelegate() as? DecoratedAppSceneViewController
        let isMaximized = decoratedVC?.isMaximized ?? false
        
        // when a fullscreen multitask app is brought to front, optionally hide other windows
        if UserDefaults.lcShared().bool(forKey: "LCMaxOneAppOnStage") && isMaximized {
            MultitaskDockManager.shared.minimizeAllWindows(except: decoratedVC)
        }
        
        if isHidden {
            view.layer.removeAllAnimations()
            view.isHidden = true
            view.transform = .identity
            let origFrame = view.frame
            let pipManager = PiPManager.shared!
            if let decoratedVC = view._viewDelegate(), pipManager.isPiP(withDecoratedVC: decoratedVC) {
                pipManager.stopPiP()
            } else {
                view.transform = CGAffineTransform(scaleX: 0.1, y: 0.1)
                view.isHidden = false
                let smaller = min(view.frame.size.width, view.frame.size.height)
                view.frame.size = CGSize(width: smaller, height: smaller)
                if let center { view.center = center }
            }
            
            self.bringViewToFront(view, in: window)
            UIView.animate(
                withDuration: Constants.standardAnimationDuration,
                delay: 0,
                usingSpringWithDamping: 1.0,
                initialSpringVelocity: 0,
                options: .curveEaseInOut,
                animations: {
                    view.alpha = 1.0
                    view.transform = .identity
                    view.frame = origFrame
                }
            )
        } else {
            bringViewToFront(view, in: window)
            
            UIView.animate(withDuration: Constants.shortAnimationDuration1, animations: {
                let scale = Constants.bringToFrontScale
                view.transform = CGAffineTransform(scaleX: scale, y: scale)
            }) { _ in
                UIView.animate(withDuration: Constants.shortAnimationDuration2) {
                    view.transform = .identity
                }
            }
        }
    }

    private func bringViewToFront(_ view: UIView, in window: UIWindow) {
        if let superview = view.superview {
            superview.bringSubviewToFront(view)
        }
        if let windowSuperview = window.superview {
            windowSuperview.bringSubviewToFront(window)
        }
    }
    
    // Recursively find multitask view
    private func findMultitaskView(in view: UIView, withUUID uuid: String) -> UIView? {
        apps.first { $0.appUUID == uuid }?.view
    }
    
    // Get view's dataUUID property through reflection
    private func getDataUUID(from view: UIView) -> String? {
        let mirror = Mirror(reflecting: view)
        
        if let child = (mirror.children.first { $0.label == "dataUUID" })?.value as? String {
            return child
        }
        
        if view.responds(to: NSSelectorFromString("dataUUID")) {
            return view.value(forKey: "dataUUID") as? String
        }
        
        return nil
    }
    
    @objc public func addRunningAppWithInfo(_ appInfo: LCAppInfo?, appUUID: String, view: UIView?) {
        guard isDockEnabled() else { return }
        
        if apps.contains(where: { $0.appUUID == appUUID }) {
            return
        }
        
        let appName = appInfo?.displayName() ?? "Unknown App"
        let appModel = DockAppModel(appName: appName, appUUID: appUUID, appInfo: appInfo, view: view)
        
        DispatchQueue.main.async {
            self.apps.append(appModel)
            
            // MULTITASK_DOCK_SESSION_RECOVERY_V1: recover if a prior session lost its final removal callback.
            if self.collapseStartState.wasPresented && !self.isVisible {
                NSLog("[LC_DOCK] STALE_SESSION_RESET manager=%@ id=%@ apps_count=%ld isCollapsed=%d", String(describing: ObjectIdentifier(self)), self.collapseStartState.sessionID ?? "none", self.apps.count, self.isCollapsed ? 1 : 0)
                self.apps = [appModel]
                self.v3DockPresentationState.end(sessionID: self.collapseStartState.sessionID)
                self.collapseStartState.end()
            }
            if !self.collapseStartState.isActiveSession {
                // MULTITASK_DOCK_SESSION_APPLY_V2: snapshot the preference before the first view is selected.
                let stored = LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsCollapsed")
                let storedTucked = LCUtils.appGroupUserDefault.bool(forKey: "LCMultitaskDockStartsTuckedToEdge")
                let sessionID = self.collapseStartState.begin(storedPreference: stored, storedTuckedPreference: storedTucked)
                self.v3DockPresentationState.begin(sessionID: sessionID)
                NSLog("[LC_DOCK] SESSION_BEGIN manager=%@ id=%@ suite=%@ stored_preference=%d stored_tucked=%d apps_count=%ld isCollapsed_before_setup=%d isDockHidden_before_setup=%d", String(describing: ObjectIdentifier(self)), sessionID, (LCSharedUtils.appGroupID() ?? "unavailable"), stored ? 1 : 0, storedTucked ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.isDockHidden ? 1 : 0)
                if let initial = self.collapseStartState.applyBeforeFirstFrame(sessionID: sessionID) { self.isCollapsed = initial }
                if let initialHidden = self.collapseStartState.applyTuckedBeforeFirstFrame(sessionID: sessionID) { self.isDockHidden = initialHidden }
                if let hostingController = self.hostingController {
                    hostingController.rootView = AnyView(MultitaskDockSwiftView().environmentObject(self).id(sessionID))
                }
                // MULTITASK_DOCK_PRESENTATION_GATE_V1: keep the reused host root blank until showDock commits the first branch.
                NSLog("[LC_DOCK] SESSION_PREPARED manager=%@ session=%@ host=%@ stored_preference=%d stored_tucked=%d apps_count=%ld isCollapsed=%d isDockHidden=%d ready=%d", String(describing: ObjectIdentifier(self)), sessionID, self.hostingController.map { String(describing: ObjectIdentifier($0)) } ?? "not_created", stored ? 1 : 0, storedTucked ? 1 : 0, self.apps.count, self.isCollapsed ? 1 : 0, self.isDockHidden ? 1 : 0, self.v3DockPresentationState.isReady ? 1 : 0)
                self.showDock()
            } else if self.isVisible {
                self.updateDockFrame()
            }
        }
    }
    
    @objc public func minimizeAllWindows(except: DecoratedAppSceneViewController? = nil) {
        DispatchQueue.main.async {
            self.apps.forEach { app in
                if let vc = app.view?._viewDelegate() as? DecoratedAppSceneViewController,
                   vc != except {
                    app.view?.layer.removeAllAnimations()
                    vc.minimizeWindow()
                }
            }
        }
    }
    
    @objc public func toggleDockCollapse() {
        DispatchQueue.main.async {
            self.collapseStartState.userDidToggle()
            NSLog("[LC_DOCK] MANUAL_TOGGLE session=%@ apps_count=%ld collapsed_before=%d", self.collapseStartState.sessionID ?? "none", self.apps.count, self.isCollapsed ? 1 : 0)
            self.isCollapsed.toggle()
            self.updateDockFrame()
            self.notifyDockCollapseChanged()
        }
    }
    
    @objc public func notifyDockCollapseChanged() {
        self.updateDockFrame()
        // find fullscreen apps and hide its UINavigationBar
        self.apps.forEach { app in
            if let vc = app.view?._viewDelegate() as? DecoratedAppSceneViewController, vc.isMaximized {
                vc.updateVerticalConstraints()
            }
        }
    }
    
    // Toggle dock hide/show state
    @objc public func toggleDockVisibility() {
        DispatchQueue.main.async {
            self.isDockHidden.toggle()
            self.updateDockFrame()
        }
    }
    
    @objc public func showDockFromHidden() {
        DispatchQueue.main.async {
            self.isDockHidden = false
            self.updateDockFrame()
            self.setupEdgeGestureRecognizers()
        }
    }
    
    @objc public func hideDockToSide() {
        DispatchQueue.main.async {
            self.isDockHidden = true
            self.updateDockFrame()
            self.setupEdgeGestureRecognizers()
        }
    }
    
    // Add edge gesture recognition areas when dock is hidden
    private func setupEdgeGestureRecognizers() {
        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let keyWindow = windowScene.windows.first else { return }
        
        keyWindow.gestureRecognizers?.removeAll { gesture in
            return gesture is UITapGestureRecognizer || gesture is UIScreenEdgePanGestureRecognizer
        }
        
        if isDockHidden {
            let leftEdgeGesture = UIScreenEdgePanGestureRecognizer(target: self, action: #selector(handleEdgeSwipe(_:)))
            leftEdgeGesture.edges = .left
            keyWindow.addGestureRecognizer(leftEdgeGesture)
            
            let rightEdgeGesture = UIScreenEdgePanGestureRecognizer(target: self, action: #selector(handleEdgeSwipe(_:)))
            rightEdgeGesture.edges = .right
            keyWindow.addGestureRecognizer(rightEdgeGesture)
        }
    }
    
    @objc private func handleEdgeSwipe(_ gesture: UIScreenEdgePanGestureRecognizer) {
        guard isDockHidden, gesture.state == .began || gesture.state == .changed else {
            return
        }
        
        let translation = gesture.translation(in: gesture.view)
        let swipeDistance = abs(translation.x)
        
        if swipeDistance > Constants.edgeSwipeThreshold {
            showDockFromHidden()
        }
    }
    
    // MARK: - Multitask Mode Check
    private func isDockEnabled() -> Bool {
        let multitaskMode = MultitaskMode(rawValue: LCUtils.appGroupUserDefault.integer(forKey: "LCMultitaskMode")) ?? .virtualWindow
        return multitaskMode == .virtualWindow
    }
}

// MARK: - SwiftUI Dock View
@available(iOS 16.0, *)
public struct MultitaskDockSwiftView: View {
    @EnvironmentObject var dockManager: MultitaskDockManager
    @State private var dragOffset = CGSize.zero
    @State private var isMoving: Bool = false
    @AppStorage("LCHideCollapsedDock", store: LCUtils.appGroupUserDefault) var hideCollapsedDock: Bool = false
    
    // Calculate dynamic padding based on user settings
    private var dynamicPadding: CGFloat {
        let basePadding: CGFloat = 4
        let extraPadding = (dockManager.dockWidth - MultitaskDockManager.Constants.defaultDockWidth) * 0.2
        return max(basePadding, basePadding + extraPadding)
    }
    
    public var body: some View {
        GeometryReader { g in
            VStack(spacing: 8) {
                dockManager.v3RecordFirstDockBodyEvaluation()
                // MULTITASK_DOCK_PRESENTATION_GATE_V1: no expanded/collapsed branch is exposed before session readiness.
                if dockManager.v3DockPresentationState.isReady {
                    if dockManager.isCollapsed {
                    CollapsedDockView(isHidden: dockManager.isDockHidden)
                        .onAppear { dockManager.v3RecordFirstRenderedDockView(.collapsedDockView) }
                        .onTapGesture {
                            dockManager.toggleDockCollapse()
                        }
                } else {
                    VStack(spacing: 8) {
                        CollapseButtonView()
                            .onTapGesture {
                                dockManager.toggleDockCollapse()
                            }
                        
                        MinimizeAllButtonView()
                            .onTapGesture {
                                dockManager.minimizeAllWindows()
                            }
                        
                        ForEach(dockManager.apps) { app in
                            AppIconView(app: app)
                        }
                    }
                    .onAppear { dockManager.v3RecordFirstRenderedDockView(.expandedDockView) }
                }
                } else {
                    Color.clear
                }
            }
            .padding(dynamicPadding)
            .modifier { content in
                if #available(iOS 26.0, *), SharedModel.isLiquidGlassEnabled {
                    content.glassEffect(.regular, in: .rect(cornerRadius: 15))
                } else {
                    content.background(
                        RoundedRectangle(cornerRadius: 15)
                            .fill(Color.black.opacity(dockManager.isDockHidden ? 0.3 : 0.7))
                            .overlay(
                                RoundedRectangle(cornerRadius: 15)
                                    .stroke(Color.white.opacity(dockManager.isDockHidden ? 0.1 : 0.3), lineWidth: 1)
                            )
                    )
                }
            }
            .scaleEffect(dockManager.isVisible ? 1.0 : 0.8)
            .opacity(dockManager.isDockHidden ? (hideCollapsedDock && dockManager.isCollapsed ? 0.01 : 0.4) : 1.0)
            .offset(dragOffset)
            .position(x: g.size.width / 2, y: g.size.height / 2)
        }



        .ignoresSafeArea()
        .gesture(
            DragGesture(minimumDistance: 5)
            .onChanged { value in
                self.isMoving = true
                self.dragOffset = value.translation
            }
            .onEnded { value in
                self.isMoving = true

                let hcFrame = dockManager.hostingController?.view.frame ?? .zero
                
                let currentPhysicalFrame = hcFrame.offsetBy(dx: self.dragOffset.width, dy: self.dragOffset.height)
                
                if dockManager.isPositionChangeGesture(for: hcFrame, translation: value.translation) {
                    let screenBounds = dockManager.keyWindow!.bounds
                    let targetX = dockManager.calculateTargetX(isDockHidden: false, isOnRightSide: currentPhysicalFrame.midX > screenBounds.width / 2, dockWidth: dockManager.dockWidth, screenWidth: screenBounds.width)
                    
                    let safeAreaInsets = dockManager.safeAreaInsets
                    let dockVerticalMargin = MultitaskDockManager.Constants.dockVerticalMargin
                    let minY = safeAreaInsets.top + dockVerticalMargin
                    let maxY = screenBounds.height - safeAreaInsets.bottom - currentPhysicalFrame.height - dockVerticalMargin
                    let targetY = max(minY, min(maxY, currentPhysicalFrame.origin.y))
                    
                    let finalPhysicalPosition = CGPoint(x: targetX, y: targetY)
                    
                    let newOffset = CGSize(
                        width: finalPhysicalPosition.x - hcFrame.origin.x,
                        height: finalPhysicalPosition.y - hcFrame.origin.y
                    )
                    
                    let animationDuration = MultitaskDockManager.Constants.longAnimationDuration
                    
                    withAnimation(.spring(response: animationDuration, dampingFraction: MultitaskDockManager.Constants.standardSpringDamping)) {
                        self.dragOffset = newOffset
                    }
                    
                    DispatchQueue.main.asyncAfter(deadline: .now() + animationDuration) {
                        dockManager.updateFrameAfterAnimation(finalOffset: newOffset)
                        
                        self.dragOffset = .zero
                        
                        self.isMoving = false
                    }
                    return
                }
                
                if dockManager.handleSwipeToHideOrShowGesture(for: hcFrame, translation: value.translation) {
                    withAnimation(.spring(response: MultitaskDockManager.Constants.longAnimationDuration, dampingFraction: MultitaskDockManager.Constants.standardSpringDamping)) {
                        self.dragOffset = .zero
                    }
                    DispatchQueue.main.asyncAfter(deadline: .now() + MultitaskDockManager.Constants.longAnimationDuration) {
                        self.isMoving = false
                    }
                    return
                }
                
                let screenBounds = dockManager.keyWindow!.bounds
                let safeAreaInsets = dockManager.safeAreaInsets
                let dockVerticalMargin = MultitaskDockManager.Constants.dockVerticalMargin
                let minY = safeAreaInsets.top + dockVerticalMargin
                let maxY = screenBounds.height - safeAreaInsets.bottom - currentPhysicalFrame.height - dockVerticalMargin
                let targetY = max(minY, min(maxY, currentPhysicalFrame.origin.y))
                
                let targetX: CGFloat

                let isOnRightSide = hcFrame.origin.x > screenBounds.width / 2
                targetX = dockManager.calculateTargetX(isDockHidden: dockManager.isDockHidden, isOnRightSide: isOnRightSide, dockWidth: currentPhysicalFrame.width, screenWidth: screenBounds.width)
                
                let finalPhysicalPosition = CGPoint(x: targetX, y: targetY)
                
                let newOffset = CGSize(
                    width: finalPhysicalPosition.x - hcFrame.origin.x,
                    height: finalPhysicalPosition.y - hcFrame.origin.y
                )
                
                let animationDuration = MultitaskDockManager.Constants.longAnimationDuration
                
                withAnimation(.spring(response: animationDuration, dampingFraction: MultitaskDockManager.Constants.standardSpringDamping)) {
                    self.dragOffset = newOffset
                }
                
                DispatchQueue.main.asyncAfter(deadline: .now() + animationDuration) {
                    dockManager.updateFrameAfterAnimation(finalOffset: newOffset)
                    
                    self.dragOffset = .zero
                    
                    self.isMoving = false
                }
            }
        )
        .animation(.spring(response: MultitaskDockManager.Constants.standardAnimationDuration, dampingFraction: MultitaskDockManager.Constants.standardSpringDamping), value: dockManager.isCollapsed)
        .animation(.spring(response: MultitaskDockManager.Constants.standardAnimationDuration, dampingFraction: MultitaskDockManager.Constants.standardSpringDamping), value: dockManager.isDockHidden)
        .animation(.spring(response: MultitaskDockManager.Constants.longAnimationDuration, dampingFraction: MultitaskDockManager.Constants.standardSpringDamping), value: dockManager.dockWidth)
        .animation(.spring(response: MultitaskDockManager.Constants.longAnimationDuration, dampingFraction: MultitaskDockManager.Constants.standardSpringDamping), value: dockManager.settingsChanged)
    }
    
    public init() {}
}

// MARK: - Collapsed Dock View
@available(iOS 16.0, *)
struct CollapsedDockView: View {
    let isHidden: Bool
    @EnvironmentObject var dockManager: MultitaskDockManager
    
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8)
                .fill(
                    LinearGradient(
                        gradient: Gradient(colors: [
                            Color.blue.opacity(isHidden ? 0.4 : 0.8),
                            Color.blue.opacity(isHidden ? 0.3 : 0.6)
                        ]),
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: dockManager.adaptiveIconSize, height: dockManager.adaptiveIconSize)
            
            Group {
                if isHidden {
                    Image(systemName: "eye.slash")
                        .foregroundColor(.white.opacity(0.8))
                        .font(.system(size: dockManager.adaptiveIconSize * 0.35, weight: .bold))
                } else {
                    Image(systemName: "chevron.up")
                        .foregroundColor(.white)
                        .font(.system(size: dockManager.adaptiveIconSize * 0.4, weight: .bold))
                }
            }
            .shadow(color: .black.opacity(0.3), radius: 1, x: 0, y: 1)
        }
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.white.opacity(isHidden ? 0.2 : 0.3), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.3), radius: 3, x: 0, y: 2)
        .scaleEffect(isHidden ? 0.9 : 1.0)
        .animation(.easeInOut(duration: 0.2), value: isHidden)
        .animation(.spring(response: MultitaskDockManager.Constants.longAnimationDuration, dampingFraction: MultitaskDockManager.Constants.standardSpringDamping), value: dockManager.adaptiveIconSize)
    }
}

// MARK: - Collapse Button View
@available(iOS 16.0, *)
struct CollapseButtonView: View {
    @EnvironmentObject var dockManager: MultitaskDockManager
    
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8)  
                .fill(Color.gray.opacity(0.8))
                .frame(width: dockManager.adaptiveIconSize, height: dockManager.adaptiveIconSize)
            
            Image(systemName: "chevron.down")
                .foregroundColor(.white)
                .font(.system(size: dockManager.adaptiveIconSize * 0.4, weight: .semibold))
        }
        .overlay(
            RoundedRectangle(cornerRadius: 8)  
                .stroke(Color.white.opacity(0.2), lineWidth: 1)
        )
        .animation(.spring(response: MultitaskDockManager.Constants.longAnimationDuration, dampingFraction: MultitaskDockManager.Constants.standardSpringDamping), value: dockManager.adaptiveIconSize)
    }
}

// MARK: - Minimize All Button View
@available(iOS 16.0, *)
struct MinimizeAllButtonView: View {
    @EnvironmentObject var dockManager: MultitaskDockManager
    
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.gray.opacity(0.8))
                .frame(width: dockManager.adaptiveIconSize, height: dockManager.adaptiveIconSize)
            
            Image(systemName: "rectangle.stack.badge.minus")
                .foregroundColor(.white)
                .font(.system(size: dockManager.adaptiveIconSize * 0.4, weight: .semibold))
        }
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.white.opacity(0.2), lineWidth: 1)
        )
    }
}

// MARK: - Icon Cache Manager
class IconCacheManager {
    static let shared = IconCacheManager()
    private var cache: [String: UIImage] = [:]
    private let cacheQueue = DispatchQueue(label: "icon.cache.queue", attributes: .concurrent)
    
    private init() {}
    
    func getIcon(for key: String) -> UIImage? {
        return cacheQueue.sync {
            return cache[key]
        }
    }
    
    func setIcon(_ icon: UIImage, for key: String) {
        cacheQueue.async(flags: .barrier) {
            self.cache[key] = icon
        }
    }
    
    func clearCache() {
        cacheQueue.async(flags: .barrier) {
            self.cache.removeAll()
        }
    }
}
// MARK: - App Icon View
@available(iOS 16.0, *)
struct AppIconView: View {
    let app: DockAppModel
    @State private var isPressed = false
    @State private var appIcon: UIImage?
    @State private var isLoading = true
    @EnvironmentObject var dockManager: MultitaskDockManager
    @AppStorage("darkModeIcon", store: LCUtils.appGroupUserDefault) var darkModeIcon = false
    
    private var iconSize: CGFloat {
        return dockManager.adaptiveIconSize
    }
    
    var body: some View {
        Group {
            if isLoading && appIcon == nil {
                LoadingIconView()
            } else if let icon = appIcon {
                IconImageView(icon: icon)
            } else {
                RoundedRectangle(cornerRadius: 16)
                .fill(Color.gray.opacity(0.3))
            }
        }
        .frame(width: iconSize, height: iconSize)
        .shadow(color: .black.opacity(0.3), radius: 4, x: 0, y: 3)
        .scaleEffect(isPressed ? 1.15 : 1.0)
        .animation(.easeInOut(duration: 0.1), value: isPressed)
        .animation(.easeInOut(duration: MultitaskDockManager.Constants.standardAnimationDuration), value: dockManager.settingsChanged)
        .onAppear {
            loadAppIcon()
        }
        .onPressGesture(
            onPress: { 
                isPressed = true
            },
            onRelease: { location in 
                isPressed = false
                let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
                impactFeedback.impactOccurred()
                let _ = dockManager.bringMultitaskViewToFront(uuid: app.appUUID, from: location)
            }
        )
        .contentShape(Rectangle())
    }
    
    private func loadAppIcon() {
        let cacheKey = "\(app.appName)_\(app.appUUID)"
        
        if let cachedIcon = IconCacheManager.shared.getIcon(for: cacheKey) {
            self.appIcon = cachedIcon
            self.isLoading = false
            return
        }
        
        DispatchQueue.global(qos: .userInitiated).async {
            var finalIcon: UIImage?
            
            if let appInfo = self.app.appInfo {
                finalIcon = appInfo.iconIsDarkIcon(darkModeIcon)
            } else {
                if let foundAppInfo = AppInfoProvider.shared.findAppInfo(appName: self.app.appName, dataUUID: self.app.appUUID) {
                    finalIcon = foundAppInfo.iconIsDarkIcon(darkModeIcon)
                }
            }
            
            DispatchQueue.main.async {
                self.isLoading = false
                if let icon = finalIcon {
                    self.appIcon = icon
                    IconCacheManager.shared.setIcon(icon, for: cacheKey)
                }
            }
        }
    }
}

// MARK: - Press Gesture Helper
extension View {
    func onPressGesture(onPress: @escaping () -> Void, onRelease: @escaping (_ location: CGPoint) -> Void) -> some View {
        self.simultaneousGesture(
            DragGesture(minimumDistance: 0, coordinateSpace: .global)
                .onChanged { value in
                    if value.translation == CGSize.zero {
                        onPress()
                    }
                }
                .onEnded { value in
                    onRelease(value.startLocation)
                }
        )
    }
}

// MARK: - Loading Icon View
struct LoadingIconView: View {
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.gray.opacity(0.3))
            
            ProgressView()
                .progressViewStyle(CircularProgressViewStyle(tint: .white))
                .scaleEffect(1.2)
        }
    }
}
