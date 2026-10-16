// Synthetic state and lifecycle controls around the unmodified production prompt.
// No backend, real account, authentication, keychain, or network operation.
@MainActor struct P1PromptScreen: View {
    @State private var generation = 0
    @State private var shown = true
    @State private var submitting = false
    @State private var fieldsState = "unobserved"
    @State private var clipboardState = "unobserved"
    @StateObject private var observation = P1FeedbackObserver()
    private var diagnostic: String { "p1-safe-diagnostic-\(generation)" }
    private var prompt: [String: Any] {
        ["id": "p1-credentials-\(generation)", "kind": "credentials", "title": "P1 Credentials",
         "fields": [["key": "appleID", "label": "Apple ID", "secure": "false", "value": ""],
                    ["key": "password", "label": "Password", "secure": "true"]]]
    }
    var body: some View {
        NavigationView {
            Form {
                if shown {
                    V3PromptSection(prompt: prompt, isSubmitting: $submitting,
                        previousFailureMessage: "P1 synthetic failure", previousFailureDetails: diagnostic,
                        onCancel: { shown = false }) { answer in
                            if answer["appleID"] == "p1-user@example.invalid" && answer["password"] == "p1-synthetic-password" {
                                fieldsState = "synthetic-filled"
                            } else if (answer["appleID"] ?? "").isEmpty && (answer["password"] ?? "").isEmpty {
                                fieldsState = "empty"
                            } else { fieldsState = "other" }
                        }
                } else {
                    Text("Prompt dismissed").accessibilityIdentifier("p1-dismissed")
                }
            }
            .navigationTitle("P1 behavior")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Hide Keyboard") {
                        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
                    }.accessibilityIdentifier("p1-hide-keyboard")
                }
            }
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 4) {
                    HStack {
                        Button("Replace") { generation += 1; fieldsState = "unobserved" }
                            .accessibilityIdentifier("p1-replace")
                        Button(shown ? "Dismiss" : "Reopen") { shown.toggle(); fieldsState = "unobserved" }
                            .accessibilityIdentifier("p1-toggle")
                    }.buttonStyle(.bordered)
                    HStack {
                        Text("Ready").accessibilityIdentifier("p1-ready")
                        Text(String(generation)).accessibilityIdentifier("p1-generation")
                        Text(fieldsState).accessibilityIdentifier("p1-fields-state")
                        Text(clipboardState).accessibilityIdentifier("p1-clipboard-state")
                        Text(observation.reportJSON.isEmpty ? "Observing" : "Observed")
                            .accessibilityIdentifier("p1-observation-report")
                            .accessibilityValue(observation.reportJSON)
                    }.font(.system(size: 9))
                }
                .padding(6).background(Color(.systemBackground))
            }
        }.navigationViewStyle(.stack)
        .onReceive(NotificationCenter.default.publisher(for: UIPasteboard.changedNotification)) { _ in
            let value = UIPasteboard.general.string ?? ""
            clipboardState = value == diagnostic ? "exact-safe-diagnostic" : "other"
            observation.copyEvent(value: value, expected: diagnostic,
                changeCount: UIPasteboard.general.changeCount,
                context: { (generation, shown) },
                transition: {
                    fieldsState = "unobserved"
                    if ProcessInfo.processInfo.arguments.contains("--replace-on-copy") { generation += 1 }
                    else { shown = false }
                }, reopen: { shown = true; fieldsState = "unobserved" })
        }
    }
}

@main @MainActor struct P1BehaviorApp: App {
    init() { UIPasteboard.general.string = "" }
    var body: some Scene {
        WindowGroup {
            Group {
                if ProcessInfo.processInfo.arguments.contains("--recovery") {
                    P1RecoveryScreen()
                } else {
                    P1PromptScreen()
                }
            }
            .environment(\.sizeCategory, ProcessInfo.processInfo.arguments.contains("--largest")
                ? .accessibilityExtraExtraExtraLarge : .large)
        }
    }
}
