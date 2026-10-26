//
//  ViewExtensions.swift
//  LiveContainer
//
//  Created by s s on 2026/3/20.
//

import SwiftUI
import UniformTypeIdentifiers
import LocalAuthentication
import SafariServices
import Security
import Combine
import ObjectiveC

struct SafariView: UIViewControllerRepresentable {
    let url: Binding<URL>
    func makeUIViewController(context: UIViewControllerRepresentableContext<Self>) -> SFSafariViewController {
        return SFSafariViewController(url: url.wrappedValue)
    }
    func updateUIViewController(_ uiViewController: SFSafariViewController, context: UIViewControllerRepresentableContext<SafariView>) {
        
    }
}

// https://stackoverflow.com/questions/56726663/how-to-add-a-textfield-to-alert-in-swiftui
extension View {

    public func textFieldAlert(
        isPresented: Binding<Bool>,
        title: String,
        text: Binding<String>,
        placeholder: String = "",
        action: @escaping (String?) -> Void,
        actionCancel: @escaping (String?) -> Void
    ) -> some View {
        self.modifier(TextFieldAlertModifier(isPresented: isPresented, title: title, text: text, placeholder: placeholder, action: action, actionCancel: actionCancel))
    }
    
    public func betterFileImporter(
        isPresented: Binding<Bool>,
        types : [UTType],
        multiple : Bool = false,
        callback: @escaping ([URL]) -> (),
        onDismiss: @escaping () -> Void
    ) -> some View {
        self.modifier(DocModifier(isPresented: isPresented, types: types, multiple: multiple, callback: callback, onDismiss: onDismiss))
    }
    
    func onBackground(_ f: @escaping () -> Void) -> some View {
        self.onReceive(
            NotificationCenter.default.publisher(for: UIApplication.willResignActiveNotification),
            perform: { _ in f() }
        )
    }
    
    func onForeground(_ f: @escaping () -> Void) -> some View {
        self.onReceive(
            NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification),
            perform: { _ in f() }
        )
    }
    
    func rainbow() -> some View {
        self.modifier(RainbowAnimation())
    }
    
    func navigationBarProgressBar(show: Binding<Bool>, progress: Binding<Float>) -> some View {
        self.modifier(NavigationBarProgressModifier(show: show, progress: progress))
    }
    
    func modifier<ModifiedContent: View>(@ViewBuilder body: (_ content: Self) -> ModifiedContent
    ) -> ModifiedContent {
        body(self)
    }
}

public struct DocModifier: ViewModifier {
    @EnvironmentObject var sceneDelegate: SceneDelegate
    @State private var docController: UIDocumentPickerViewController?
    @State private var delegate : UIDocumentPickerDelegate
    
    @Binding var isPresented: Bool

    var callback: ([URL]) -> ()
    private let onDismiss: () -> Void
    private let types : [UTType]
    private let multiple : Bool
    
    init(isPresented : Binding<Bool>, types : [UTType], multiple : Bool, callback: @escaping ([URL]) -> (), onDismiss: @escaping () -> Void) {
        self.callback = callback
        self.onDismiss = onDismiss
        self.types = types
        self.multiple = multiple
        self.delegate = Coordinator(callback: callback, onDismiss: onDismiss)
        self._isPresented = isPresented
    }

    public func body(content: Content) -> some View {
        content.onChange(of: isPresented) { isPresented in
            if isPresented, docController == nil {
                let controller = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: true)
                controller.allowsMultipleSelection = multiple
                controller.delegate = delegate
                self.docController = controller
                sceneDelegate.window?.rootViewController?.present(controller, animated: true)
            } else if !isPresented, let docController = docController {
                docController.dismiss(animated: true)
                self.docController = nil
            }
        }
    }

    private func shutdown() {
        isPresented = false
        docController = nil
    }
    
    class Coordinator: NSObject, UIDocumentPickerDelegate {
        var callback: ([URL]) -> ()
        private let onDismiss: () -> Void
        
        init(callback: @escaping ([URL]) -> Void, onDismiss: @escaping () -> Void) {
            self.callback = callback
            self.onDismiss = onDismiss
        }
        
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            callback(urls)
            onDismiss()
        }
        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            onDismiss()
        }
    }

}

public struct TextFieldAlertModifier: ViewModifier {
    @EnvironmentObject var sceneDelegate: SceneDelegate
    @State private var alertController: UIAlertController?

    @Binding var isPresented: Bool

    let title: String
    let text: Binding<String>
    let placeholder: String
    let action: (String?) -> Void
    let actionCancel: (String?) -> Void

    public func body(content: Content) -> some View {
        content.onChange(of: isPresented) { isPresented in
            if isPresented, alertController == nil {
                guard let presenter = sceneDelegate.window?.rootViewController else { return }
                V3NativeAlertPresentation.present(from: presenter,
                    didReplace: { self.alertController = $0 },
                    onUnavailable: { self.actionCancel(nil); shutdown() }) { language, presentation in
                    makeAlertController(language: language, presentation: presentation)
                }
            } else if !isPresented, let alertController = alertController {
                V3NativeAlertPresentation.stop(alertController)
                self.alertController = nil
            }
        }
    }

    private func makeAlertController(language: V3AppLanguage, presentation: V3NativeAlertPresentation) -> UIAlertController {
        let controller = UIAlertController(title: V3DisplayMessage.localized(title).rendered(language: language), message: nil, preferredStyle: .alert)
        controller.addTextField {
            $0.placeholder = self.placeholder
            $0.text = self.text.wrappedValue
            $0.clearButtonMode = .always
        }
        controller.addAction(UIAlertAction(title: V3Localization.string("lc.common.cancel", language: language), style: .cancel) { [weak controller] _ in
            guard let controller else { return }
            presentation.finish(from: controller) { self.actionCancel(nil); shutdown() }
        })
        controller.addAction(UIAlertAction(title: V3Localization.string("lc.common.ok", language: language), style: .default) { [weak controller] _ in
            guard let controller else { return }
            let value = controller.textFields?.first?.text
            presentation.finish(from: controller) { self.action(value); shutdown() }
        })
        return controller
    }

    private func shutdown() {
        isPresented = false
        alertController = nil
    }

}

struct NavigationBarProgressModifier: ViewModifier {
    @Binding var show: Bool
    @Binding var progress: Float

    func body(content: Content) -> some View {
        content
            .background(NavigationBarProgressView(show: $show, progress: $progress))
    }
}

private struct NavigationBarProgressView: UIViewControllerRepresentable {
    @Binding var show: Bool
    @Binding var progress: Float

    func makeUIViewController(context: Context) -> ProgressInjectorViewController {
        ProgressInjectorViewController(progress: progress)
    }

    func updateUIViewController(_ uiViewController: ProgressInjectorViewController, context: Context) {
        uiViewController.updateProgress(!show, progress)
    }

    class ProgressInjectorViewController: UIViewController {
        private var progressView: UIProgressView?

        init(progress: Float) {
            super.init(nibName: nil, bundle: nil)
        }

        required init?(coder: NSCoder) {
            fatalError("init(coder:) has not been implemented")
        }

        override func viewDidAppear(_ animated: Bool) {
            super.viewDidAppear(animated)
            injectProgressView()
        }

        func updateProgress(_ hidden: Bool, _ progress: Float) {
            progressView?.setProgress(progress, animated: false)
            progressView?.isHidden = hidden
        }

        private func injectProgressView() {
            guard let navigationBar = self.navigationController?.navigationBar, progressView == nil else { return }

            let barProgress = UIProgressView(progressViewStyle: .bar)
            barProgress.translatesAutoresizingMaskIntoConstraints = false
            var contentView : UIView? = nil
            for curView in navigationBar.subviews {
                if NSStringFromClass(curView.classForCoder) == "_UINavigationBarContentView" ||
                    NSStringFromClass(curView.classForCoder) == "UIKit.NavigationBarContentView" {
                    contentView = curView
                    break
                }
            }
            if let contentView {
                contentView.addSubview(barProgress)
                NSLayoutConstraint.activate([
                    barProgress.leadingAnchor.constraint(equalTo: contentView.leadingAnchor),
                    barProgress.trailingAnchor.constraint(equalTo: contentView.trailingAnchor),
                    barProgress.bottomAnchor.constraint(equalTo: contentView.bottomAnchor)
                ])
            }
            self.progressView = barProgress
        }

    }
}

// https://kieranb662.github.io/blog/2020/04/15/Rainbow
struct RainbowAnimation: ViewModifier {
    // 1
    @State var isOn: Bool = false
    let hueColors = stride(from: 0, to: 1, by: 0.01).map {
        Color(hue: $0, saturation: 1, brightness: 1)
    }
    // 2
    var duration: Double = 4
    var animation: Animation {
        Animation
            .linear(duration: duration)
            .repeatForever(autoreverses: false)
    }

    func body(content: Content) -> some View {
    // 3
        let gradient = LinearGradient(gradient: Gradient(colors: hueColors+hueColors), startPoint: .leading, endPoint: .trailing)
        return content.overlay(GeometryReader { proxy in
            ZStack {
                gradient
    // 4
                    .frame(width: 2*proxy.size.width)
    // 5
                    .offset(x: self.isOn ? -proxy.size.width : 0)
            }
        })
    // 6
        .onAppear {
            withAnimation(self.animation) {
                self.isOn = true
            }
        }
        .mask(content)
    }
}

struct BasicButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
    }
}

struct ActivityViewController: UIViewControllerRepresentable {
    var activityItems: [Any]
    var applicationActivities: [UIActivity]? = nil

    func makeUIViewController(context: UIViewControllerRepresentableContext<ActivityViewController>) -> UIActivityViewController {
        return UIActivityViewController(activityItems: activityItems, applicationActivities: applicationActivities)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: UIViewControllerRepresentableContext<ActivityViewController>) {}
}

private class SizedHostingController<Content: View>: UIHostingController<Content> {
    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()

        let size = sizeThatFits(in: UIView.layoutFittingCompressedSize)
        if preferredContentSize != size {
            preferredContentSize = size
        }
    }
}

struct IconImageView: View {
    var icon: UIImage
    
    var body: some View {
        GeometryReader { g in
            Image(uiImage: icon)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: g.size.width*0.2667))
        }
    }
}


// V3_NATIVE_ALERT_LANGUAGE_V1: rebuild only the presentation; preserve inputs,
// continuation identity and callbacks. No guest or operation state is recreated.
@MainActor
private final class V3NativeAlertPresentation: NSObject {
    private static var associationKey: UInt8 = 0
    private weak var presenter: UIViewController?
    private weak var controller: UIAlertController?
    private var observer: NSObjectProtocol?
    private var explicitLanguageObserver: NSObjectProtocol?
    private var sceneObserver: NSObjectProtocol?
    private var renderedLanguage = V3AppLanguage.selected
    private var isTransitioning = false
    private var isFinished = false
    private var completion: (() -> Void)?
    private var afterDismissal: [() -> Void] = []
    @MainActor
    private struct TextFieldSnapshot {
        let text: String?
        let selection: (start: Int, end: Int)?
        let wasFirstResponder: Bool
        init(_ field: UITextField) {
            text = field.text
            wasFirstResponder = field.isFirstResponder
            selection = field.selectedTextRange.map {
                (field.offset(from: field.beginningOfDocument, to: $0.start),
                 field.offset(from: field.beginningOfDocument, to: $0.end))
            }
        }
        func restoreFocus(in field: UITextField) {
            if wasFirstResponder { field.becomeFirstResponder() }
            if let selection,
               let start = field.position(from: field.beginningOfDocument, offset: selection.start),
               let end = field.position(from: field.beginningOfDocument, offset: selection.end) {
                field.selectedTextRange = field.textRange(from: start, to: end)
            }
        }
    }
    private let build: (V3AppLanguage, V3NativeAlertPresentation) -> UIAlertController
    private let didReplace: (UIAlertController) -> Void
    private let onUnavailable: () -> Void

    private init(presenter: UIViewController, didReplace: @escaping (UIAlertController) -> Void,
                 onUnavailable: @escaping () -> Void,
                 build: @escaping (V3AppLanguage, V3NativeAlertPresentation) -> UIAlertController) {
        self.presenter = presenter
        self.didReplace = didReplace
        self.onUnavailable = onUnavailable
        self.build = build
        super.init()
        observer = NotificationCenter.default.addObserver(forName: UserDefaults.didChangeNotification,
            object: V3Localization.hostDefaults, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.refreshLanguage() }
        }
        explicitLanguageObserver = NotificationCenter.default.addObserver(forName: Notification.Name("V3HostLanguageDidChange"),
            object: V3Localization.hostDefaults, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.refreshLanguage() }
        }
        let sceneID = presenter.viewIfLoaded?.window?.windowScene?.session.persistentIdentifier
        sceneObserver = NotificationCenter.default.addObserver(forName: UIScene.didDisconnectNotification,
            object: nil, queue: .main) { [weak self] notification in
            guard let scene = notification.object as? UIScene,
                  scene.session.persistentIdentifier == sceneID else { return }
            Task { @MainActor [weak self] in self?.cancelUnavailable(forceCompletion: true) }
        }
    }

    deinit {
        if let observer { NotificationCenter.default.removeObserver(observer) }
        if let explicitLanguageObserver { NotificationCenter.default.removeObserver(explicitLanguageObserver) }
        if let sceneObserver { NotificationCenter.default.removeObserver(sceneObserver) }
    }

    static func present(from presenter: UIViewController,
                        didReplace: @escaping (UIAlertController) -> Void = { _ in },
                        onUnavailable: @escaping () -> Void = {},
                        build: @escaping (V3AppLanguage, V3NativeAlertPresentation) -> UIAlertController) {
        let presentation = Self(presenter: presenter, didReplace: didReplace,
                                onUnavailable: onUnavailable, build: build)
        presentation.presentController(presentation.makeController(), animated: true)
    }

    static func stop(_ controller: UIAlertController) {
        if let presentation = objc_getAssociatedObject(controller, &associationKey) as? V3NativeAlertPresentation {
            // External SwiftUI dismissal has already resolved its own binding.
            presentation.finish({})
        } else { controller.dismiss(animated: true) }
    }

    static func dismissManaged(_ controller: UIViewController, completion: @escaping () -> Void) -> Bool {
        guard let alert = controller as? UIAlertController,
              let presentation = objc_getAssociatedObject(alert, &associationKey) as? V3NativeAlertPresentation else { return false }
        presentation.afterDismissal.append(completion)
        if !presentation.isFinished { presentation.finish(presentation.onUnavailable) }
        else if !presentation.isTransitioning { presentation.dismissAndComplete() }
        return true
    }

    private func makeController() -> UIAlertController {
        renderedLanguage = V3AppLanguage.selected
        let result = build(renderedLanguage, self)
        result.view.semanticContentAttribute = renderedLanguage.isRightToLeft ? .forceRightToLeft : .forceLeftToRight
        // The alert owns the observer. The observer and presenter never retain it.
        objc_setAssociatedObject(result, &Self.associationKey, self, .OBJC_ASSOCIATION_RETAIN_NONATOMIC)
        controller = result
        return result
    }

    private func presentController(_ result: UIAlertController, animated: Bool,
                                   restoring fields: [TextFieldSnapshot] = []) {
        guard !isFinished, let presenter, presenter.viewIfLoaded?.window != nil,
              presenter.presentedViewController == nil else {
            cancelUnavailable()
            return
        }
        isTransitioning = true
        didReplace(result)
        presenter.present(result, animated: animated) { [self] in
            isTransitioning = false
            if isFinished { dismissAndComplete() } else {
                for (index, snapshot) in fields.enumerated() where index < (result.textFields?.count ?? 0) {
                    if let field = result.textFields?[index] { snapshot.restoreFocus(in: field) }
                }
                refreshLanguage()
            }
        }
    }

    /// One terminal action owns the callback/continuation across every replacement.
    /// Mark it before dismissal so rapid language changes cannot resurrect the alert.
    func finish(from source: UIAlertController, _ callback: @escaping () -> Void) {
        // A delayed action belonging to a replaced alert cannot decide a newer one.
        guard controller === source else { return }
        finish(callback)
    }

    func finish(_ callback: @escaping () -> Void) {
        guard !isFinished else { return }
        isFinished = true
        completion = callback
        if let observer { NotificationCenter.default.removeObserver(observer); self.observer = nil }
        if let explicitLanguageObserver { NotificationCenter.default.removeObserver(explicitLanguageObserver); self.explicitLanguageObserver = nil }
        if !isTransitioning { dismissAndComplete() }
    }

    private func deliverCompletion() {
        let callback = completion
        let pending = afterDismissal
        completion = nil
        afterDismissal.removeAll()
        callback?()
        pending.forEach { $0() }
    }

    private func dismissAndComplete() {
        guard let controller, controller.presentingViewController != nil else {
            deliverCompletion()
            return
        }
        isTransitioning = true
        controller.dismiss(animated: true) { [self] in
            isTransitioning = false
            deliverCompletion()
        }
    }

    private func cancelUnavailable(forceCompletion: Bool = false) {
        if !isFinished { finish(onUnavailable) }
        // A disconnected scene cannot finish an animated transition reliably.
        if forceCompletion || presenter?.viewIfLoaded?.window == nil { deliverCompletion() }
    }

    private func refreshLanguage() {
        guard !isFinished, !isTransitioning,
              V3AppLanguage.selected != renderedLanguage else { return }
        guard let presenter, let previous = controller,
              presenter.viewIfLoaded?.window != nil,
              presenter.presentedViewController === previous else {
            cancelUnavailable()
            return
        }
        let fields = previous.textFields?.map { TextFieldSnapshot($0) } ?? []
        isTransitioning = true
        previous.dismiss(animated: false) { [self] in
            isTransitioning = false
            guard !isFinished else { deliverCompletion(); return }
            guard presenter.viewIfLoaded?.window != nil, presenter.presentedViewController == nil else {
                cancelUnavailable()
                return
            }
            // Coalesce changes while dismissing; never build a stale replacement.
            let replacement = makeController()
            for (index, snapshot) in fields.enumerated() where index < (replacement.textFields?.count ?? 0) {
                replacement.textFields?[index].text = snapshot.text
            }
            presentController(replacement, animated: false, restoring: fields)
        }
    }
}

extension UIViewController {
    func presentConfirmation(
        title: V3DisplayMessage,
        message: V3DisplayMessage,
        confirmTitle: V3DisplayMessage,
        cancelTitle: V3DisplayMessage
    ) async -> Bool? {
        guard viewIfLoaded?.window != nil, presentedViewController == nil else {
            return nil
        }

        return await withUnsafeContinuation { continuation in
            V3NativeAlertPresentation.present(from: self,
                onUnavailable: { continuation.resume(returning: nil) }) { language, presentation in
                let alert = UIAlertController(title: title.rendered(language: language),
                    message: message.rendered(language: language), preferredStyle: .alert)
                alert.addAction(UIAlertAction(title: confirmTitle.rendered(language: language), style: .destructive) { [weak alert] _ in
                    guard let alert else { return }
                    presentation.finish(from: alert) { continuation.resume(returning: true) }
                })
                alert.addAction(UIAlertAction(title: cancelTitle.rendered(language: language), style: .cancel) { [weak alert] _ in
                    guard let alert else { return }
                    presentation.finish(from: alert) { continuation.resume(returning: false) }
                })
                return alert
            }
        }
    }

    func showError(_ message: String) {
        showError(V3DisplayMessage.raw(message))
    }

    func showError(_ message: V3DisplayMessage) {
        let details = LCNativeErrorPresentation.details(message.original, site: .banner)
        let display = message.appendingDiagnostic(LCNativeErrorSite.banner.rawValue)
        guard viewIfLoaded?.window != nil else { return }

        let presentError = { [weak self] in
            guard let self else { return }
            V3NativeAlertPresentation.present(from: self) { language, presentation in
                let alert = UIAlertController(title: V3Localization.string("lc.common.error", language: language),
                    message: display.rendered(language: language), preferredStyle: .alert)
                alert.addAction(UIAlertAction(title: V3Localization.string("lc.common.ok", language: language), style: .default) { [weak alert] _ in
                    guard let alert else { return }
                    presentation.finish(from: alert, {})
                })
                alert.addAction(UIAlertAction(title: V3Localization.string("lc.common.copy", language: language), style: .default) { [weak alert] _ in
                    guard let alert else { return }
                    presentation.finish(from: alert) { UIPasteboard.general.string = details }
                })
                return alert
            }
        }

        if let presentedViewController {
            // Programmatic dismissal does not invoke the adaptive-dismiss delegate.
            // Resolve any managed confirmation before replacing it with this error.
            if !V3NativeAlertPresentation.dismissManaged(presentedViewController, completion: presentError) {
                presentedViewController.dismiss(animated: true, completion: presentError)
            }
        } else {
            presentError()
        }
    }
}

// LC_NATIVE_ERROR_PRESENTERS_V1: site identity only, with unknown underlying cause.
enum LCNativeErrorSite: String {
    case appList = "SS-NATIVE-APP-LIST"
    case banner = "SS-NATIVE-BANNER"
    case appSettings = "SS-NATIVE-APP-SETTINGS"
    case container = "SS-NATIVE-CONTAINER"
    case storage = "SS-NATIVE-STORAGE"
    case dataManagement = "SS-NATIVE-DATA"
    case settings = "SS-NATIVE-SETTINGS"
    case signingDiagnostics = "SS-NATIVE-SIGNING"
    case source = "SS-NATIVE-SOURCE"
    case tweaks = "SS-NATIVE-TWEAKS"
    case webDownload = "SS-NATIVE-DOWNLOAD"
    case root = "SS-NATIVE-ROOT"
}
enum LCNativeErrorPresentation {
    static func message(_ original: String, site: LCNativeErrorSite) -> String {
        original + "\nError ID: " + site.rawValue
    }
    static func details(_ original: String, site: LCNativeErrorSite) -> String {
        let saved = Bundle.main.object(forInfoDictionaryKey: "LCBuilderCommit") as? String ?? ""
        let commit = saved.utf8.count == 40 && saved.range(of: "^[0-9a-fA-F]{40}$", options: .regularExpression) != nil
            ? saved.lowercased() : "unknown"
        return message(original, site: site) + "\nbuilder_commit=" + commit
    }
}
