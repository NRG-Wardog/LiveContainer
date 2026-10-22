// Explicit side-effect doubles: no defaults file, app, account or device IO.
final class UserDefaults {
    static let standard = UserDefaults()
    func synchronize() -> Bool { true }
    var values: [String: Any] = [:]
    func string(forKey key: String) -> String? { values[key] as? String }
    func dictionary(forKey key: String) -> [String: Any]? { values[key] as? [String: Any] }
    func object(forKey key: String) -> Any? { values[key] }
    func bool(forKey key: String) -> Bool { values[key] as? Bool ?? false }
    func set(_ value: Any?, forKey key: String) { values[key] = value }
    func removeObject(forKey key: String) { values.removeValue(forKey: key) }
}
enum V3SharedAppGroup {
    static var defaults = UserDefaults()
    static var available = true
    static func sharedUserDefaults() -> UserDefaults? { available ? defaults : nil }
}
protocol RefreshServer {
    func finish(_ error: String?)
    func finishRefresh(_ error: String?, runID: String, verification: Data?)
}
final class CapturedServer: RefreshServer {
    var error: String?
    var runID: String?
    var verification: Data?
    var calls = 0
    func finish(_ error: String?) { self.error = error; calls += 1 }
    func finishRefresh(_ error: String?, runID: String, verification: Data?) {
        self.error = error; self.runID = runID; self.verification = verification; calls += 1
    }
}
