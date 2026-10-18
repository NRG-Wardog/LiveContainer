// Appended to the exact marked reader block; macOS only, no simulator or UI.
private struct RegressionFailure: Error { let message: String }
private func ensure(_ value: Bool, _ message: String) throws {
    if !value { throw RegressionFailure(message: message) }
}
private var cases: [[String: Any]] = []
private func runCase(_ name: String, _ body: (URL, Int32) throws -> Void) throws {
    let root = FileManager.default.temporaryDirectory.resolvingSymlinksInPath()
        .appendingPathComponent("p1-reader-" + UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false)
    let directory = open(root.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
    guard directory >= 0 else { throw RegressionFailure(message: "test root open") }
    defer { P1RequestReader.checkpoint = nil; close(directory); try? FileManager.default.removeItem(at: root) }
    do { try body(root, directory); cases.append(["id": name, "passed": true]) }
    catch { cases.append(["id": name, "passed": false]); throw error }
}
private func put(_ root: URL, _ value: Data = Data("old".utf8)) throws {
    try value.write(to: root.appendingPathComponent("request.json"))
}
private func replace(_ root: URL) throws {
    try Data("new".utf8).write(to: root.appendingPathComponent("next.json"))
    try ensure(rename(root.appendingPathComponent("next.json").path,
                      root.appendingPathComponent("request.json").path) == 0, "rename")
}
private func closed(_ descriptor: Int32) throws {
    errno = 0; try ensure(fcntl(descriptor, F_GETFD) == -1 && errno == EBADF, "descriptor leaked")
}
private func rejection(_ directory: Int32, reason: String) throws -> [String: Any] {
    do { _ = try P1RequestReader.read(directory: directory) }
    catch let error as P1RequestReadError {
        try ensure(error.receipt["reason"] as? String == reason, "wrong rejection reason")
        return error.receipt
    }
    throw RegressionFailure(message: "unsafe request accepted")
}
private func runAll() throws {
    try runCase("missing") { _, fd in let row = try P1RequestReader.read(directory: fd); try ensure(row.data == nil && row.discarded == nil, "missing") }
    try runCase("regular") { root, fd in try put(root); let row = try P1RequestReader.read(directory: fd); try ensure(row.data == Data("old".utf8) && row.discarded == nil, "regular") }
    for phase in ["before", "after"] {
        try runCase("rename-" + phase) { root, fd in
            try put(root); var opened: Int32 = -1
            P1RequestReader.checkpoint = { stage, input in if stage == phase { opened = input; try replace(root) } }
            let row = try P1RequestReader.read(directory: fd)
            try ensure(row.data == nil && row.discarded?["reason"] as? String == "unlinked prior request discarded", "old bytes consumed")
            let observed = row.discarded?[phase] as? [String: Any]
            try ensure(observed?["links"] as? UInt64 == 0 && observed?["size"] as? Int64 == 3, "discard stat absent")
            try closed(opened); P1RequestReader.checkpoint = nil
            let fresh = try P1RequestReader.read(directory: fd)
            try ensure(fresh.data == Data("new".utf8), "successor not accepted")
        }
        try runCase("unlink-" + phase) { root, fd in
            try put(root); var opened: Int32 = -1
            P1RequestReader.checkpoint = { stage, input in if stage == phase { opened = input; try ensure(unlink(root.appendingPathComponent("request.json").path) == 0, "unlink") } }
            let row = try P1RequestReader.read(directory: fd); try ensure(row.data == nil && row.discarded != nil, "unlinked bytes consumed"); try closed(opened)
        }
        try runCase("hardlink-" + phase) { root, fd in
            try put(root); var opened: Int32 = -1
            P1RequestReader.checkpoint = { stage, input in if stage == phase { opened = input; try ensure(link(root.appendingPathComponent("request.json").path, root.appendingPathComponent("linked").path) == 0, "link") } }
            let row = try rejection(fd, reason: "multiply linked request")
            try ensure((row[phase] as? [String: Any])?["links"] as? UInt64 == 2, "link stat absent"); try closed(opened)
        }
    }
    try runCase("empty") { root, fd in try put(root, Data()); _ = try rejection(fd, reason: "invalid request size") }
    try runCase("oversized") { root, fd in try put(root, Data(repeating: 65, count: 8193)); _ = try rejection(fd, reason: "invalid request size") }
    try runCase("maximum-size") { root, fd in let bytes = Data(repeating: 65, count: 8192); try put(root, bytes); let row = try P1RequestReader.read(directory: fd); try ensure(row.data == bytes, "maximum rejected") }
    try runCase("directory") { root, fd in try FileManager.default.createDirectory(at: root.appendingPathComponent("request.json"), withIntermediateDirectories: false); _ = try rejection(fd, reason: "nonregular request") }
    try runCase("fifo") { root, fd in try ensure(mkfifo(root.appendingPathComponent("request.json").path, 0o600) == 0, "fifo"); _ = try rejection(fd, reason: "nonregular request") }
    try runCase("symlink") { root, fd in try Data("payload".utf8).write(to: root.appendingPathComponent("target")); try ensure(symlink("target", root.appendingPathComponent("request.json").path) == 0, "symlink"); let row = try rejection(fd, reason: "safe open failed"); try ensure(row["errno"] as? Int32 == ELOOP, "symlink errno") }
    try runCase("unlinked-empty-fatal") { root, fd in try put(root, Data()); P1RequestReader.checkpoint = { stage, _ in if stage == "before" { _ = unlink(root.appendingPathComponent("request.json").path) } }; _ = try rejection(fd, reason: "invalid request size") }
    try runCase("fstat-error-typed") { _, _ in
        var receipt: [String: Any] = [:]
        do { _ = try P1RequestReader.inspect(-1, stage: "before", receipt: &receipt); throw RegressionFailure(message: "bad fd accepted") }
        catch let error as P1RequestReadError { let row = error.receipt["before"] as? [String: Any]; try ensure(row?["result"] as? Int32 == -1 && row?["errno"] as? Int32 == EBADF, "fstat details") }
    }
    try runCase("close-error-preserves-primary") { root, fd in
        try put(root); P1RequestReader.checkpoint = { stage, input in if stage == "before" { _ = close(input) } }
        let row = try rejection(fd, reason: "request descriptor close failed")
        try ensure(row["primaryReason"] as? String == "fstat failed" && (row["close"] as? [String: Any])?["errno"] as? Int32 == EBADF, "close details")
    }
    try runCase("short-read-fatal") { root, fd in try put(root); P1RequestReader.checkpoint = { stage, input in if stage == "before" { _ = lseek(input, 3, SEEK_SET) } }; _ = try rejection(fd, reason: "short or failed request read") }
    try runCase("read-error-fatal") { root, fd in
        try put(root); P1RequestReader.checkpoint = { stage, input in if stage == "before" { let writer = open(root.appendingPathComponent("request.json").path, O_WRONLY); defer { close(writer) }; try ensure(writer >= 0 && dup2(writer, input) == input, "write-only swap") } }
        let row = try rejection(fd, reason: "short or failed request read"); try ensure(row["errno"] as? Int32 == EBADF, "read errno")
    }
    try runCase("changed-size-fatal") { root, fd in try put(root); P1RequestReader.checkpoint = { stage, _ in if stage == "after" { let writer = open(root.appendingPathComponent("request.json").path, O_WRONLY); defer { close(writer) }; try ensure(writer >= 0 && ftruncate(writer, 6) == 0, "truncate") } }; _ = try rejection(fd, reason: "request changed during read") }
    try runCase("repeated-replace-no-fd-leak") { root, fd in
        for _ in 0..<32 {
            try put(root); var opened: Int32 = -1
            P1RequestReader.checkpoint = { stage, input in if stage == "after" { opened = input; try replace(root) } }
            let row = try P1RequestReader.read(directory: fd); try ensure(row.data == nil && row.discarded != nil, "race not discarded"); try closed(opened)
        }
    }
}
var report: [String: Any] = ["schema": "p1-request-reader-regression-v1", "passed": false,
    "admissionEligible": false, "uiExecuted": false, "simulatorExecuted": false]
do { try runAll(); report["passed"] = true }
catch { report["error"] = String(describing: error) }
report["cases"] = cases
let output = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
FileHandle.standardOutput.write(output); FileHandle.standardOutput.write(Data("\n".utf8))
exit(report["passed"] as? Bool == true ? 0 : 1)
