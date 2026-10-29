@main
struct NotificationCases {
    @MainActor static func main() throws {
        let catalog = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String: [String: String]]
        let title = "Refresh Results"
        let body = "The operation completed. Open the app to review verification and expiration."
        let content = UNMutableNotificationContent()
        content.title = title; content.body = body; content.subtitle = "opaque-subtitle"
        content.userInfo = ["opaque": "unchanged"]
        content.categoryIdentifier = "category"; content.threadIdentifier = "thread"
        content.badge = 3; content.sound = .default
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 60, repeats: false)
        let original = UNNotificationRequest(identifier: "owned-id", content: content, trigger: trigger)
        for language in ["en", "he", "ru", "zh-Hans", "zh-Hant"] {
            V3RefreshNotificationLocalization.translate = { catalog[language]?[$0] ?? $0 }
            let result = V3RefreshNotificationLocalization.localized(original)
            precondition(result.content.title == catalog[language]![title]!)
            precondition(result.content.body == catalog[language]![body]!)
            precondition(result.identifier == original.identifier)
            precondition(result.content.subtitle == content.subtitle)
            precondition(result.content.categoryIdentifier == content.categoryIdentifier)
            precondition(result.content.threadIdentifier == content.threadIdentifier)
            precondition(result.content.badge == content.badge && result.content.sound != nil)
            precondition(result.content.attachments == content.attachments)
            precondition(NSDictionary(dictionary: result.content.userInfo).isEqual(to: content.userInfo))
            precondition((result.trigger as? UNTimeIntervalNotificationTrigger)?.timeInterval == 60 && result.trigger?.repeats == false)
            precondition(original.content.title == title && original.content.body == body)
            print("PASS notification_" + language)
        }
        V3RefreshNotificationLocalization.translate = { $0 }
        let missing = V3RefreshNotificationLocalization.localized(original)
        precondition(missing.content.title == title && missing.content.body == body)
        print("PASS notification_missing_catalog")
        let foreign = content.mutableCopy() as! UNMutableNotificationContent
        foreign.body = "arbitrary provider text"
        let unknown = UNNotificationRequest(identifier: "foreign", content: foreign, trigger: trigger)
        V3RefreshNotificationLocalization.translate = { _ in preconditionFailure("Unknown copy must not enter translator") }
        precondition(V3RefreshNotificationLocalization.localized(unknown) === unknown)
        print("PASS notification_unknown_unchanged")
        print("REFRESH_NOTIFICATION_RUNTIME_PASS")
    }
}
