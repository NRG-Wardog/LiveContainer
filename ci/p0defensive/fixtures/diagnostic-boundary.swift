// Synthetic responses only. Exact production parser methods are assembled above.
struct BoundaryProvider: AnisetteDataProvider {
    var requiresLocalLibraries: Bool { false }
    func getAnisetteHeaders(libDir: String, provisioningDir: String, identifier: [UInt8], adiPb: [UInt8]) throws -> AnisetteDataResponse { fatalError("Native provider must never execute") }
    func startProvision(libDir: String, provisioningDir: String, identifier: [UInt8], spim: [UInt8]) throws -> (cpim: Data, session: UInt32) { fatalError("Native provider must never execute") }
    func endProvision(libDir: String, provisioningDir: String, identifier: [UInt8], session: UInt32, ptm: [UInt8], tk: [UInt8]) throws -> Data { fatalError("Native provider must never execute") }
}
let boundaryProvider = BoundaryProvider()
var boundaryChecks = 0
func checked(_ condition: @autoclosure () -> Bool) {
    boundaryChecks += 1
    precondition(condition())
}
func response<T>(_ object: [String: Any], _ body: (CStringPointer) throws -> T) throws -> T {
    let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    var bytes = Array(String(data: data, encoding: .utf8)!.utf8CString)
    return try bytes.withUnsafeMutableBufferPointer { try body($0.baseAddress!) }
}
func failure(_ body: () throws -> Void, _ expected: String) {
    do { try body(); fatalError("Expected synthetic error") }
    catch let error as AnisetteError {
        checked(error == .adiError(code: -1013, description: expected))
    } catch { fatalError("Unexpected error type") }
}
let acceptedWires = [valid,
    "v1;p0_fault_diag1;0;-1;0;-1;-1;0;-;-",
    "v1;p0_fault_diag1;3;256;7;65535;805306367;2;\(hash);\(hash)"]
let rejectedWires = ["SECRET",valid+";extra",valid+"\n",String(repeating: "a",count:256),
    "v1;p0_fault_diag1;0;8;1;0;32;1;-;-",
    "v1;p0_fault_diag1;1;8;1;-1;32;1;-;-",
    "v1;p0_fault_diag1;1;8;1;0;32;1;\(hash.uppercased());-",
    "v1;p0_fault_diag1;1;8;1;0;32;1;é;-"]
let boundaryValues: [String?] = [nil] + acceptedWires.map(Optional.some) + rejectedWires.map(Optional.some)
for value in boundaryValues {
    var metadata: [String: Any] = [:]
    if let value { metadata["v3_constructor_fault"] = value }
    let expected = "original-engine-error" + (value.map { acceptedWires.contains($0) ? " [DEBUG_TEMPORARY_CONSTRUCTOR_FAULT:\($0)]" : "" } ?? "")
    var error = metadata; error["error"] = "original-engine-error"
    failure({ try response(error) { _ = try boundaryProvider.parseHeadersResponse(code: -1013, outPtr: $0, providerName: "synthetic") } }, expected)
    failure({ try response(error) { _ = try boundaryProvider.parseStartProvisionResponse(code: -1013, outPtr: $0, providerName: "synthetic") } }, expected)
    failure({ try response(error) { _ = try boundaryProvider.parseEndProvisionResponse(code: -1013, outPtr: $0, providerName: "synthetic") } }, expected)
    var headers = metadata; headers[AnisetteConstants.Headers.oneTimePassword] = "fixture-otp"; headers[AnisetteConstants.Headers.machineID] = "fixture-mid"
    let headerResult = try response(headers) { try boundaryProvider.parseHeadersResponse(code: 0, outPtr: $0, providerName: "synthetic") }
    checked(headerResult == AnisetteDataResponse(oneTimePassword: "fixture-otp", machineID: "fixture-mid"))
    var start = metadata; start["cpim_base64"] = "AQID"; start["session"] = 42
    let startResult = try response(start) { try boundaryProvider.parseStartProvisionResponse(code: 0, outPtr: $0, providerName: "synthetic") }
    checked(startResult.cpim == Data([1,2,3]) && startResult.session == 42)
    var end = metadata; end["adi_pb_base64"] = "BAUG"
    let endResult = try response(end) { try boundaryProvider.parseEndProvisionResponse(code: 0, outPtr: $0, providerName: "synthetic") }
    checked(endResult == Data([4,5,6]))
}
// A non-string private value is rejected at the heterogeneous start boundary.
failure({ try response(["error":"original-engine-error","v3_constructor_fault":42]) { _ = try boundaryProvider.parseStartProvisionResponse(code: -1013,outPtr:$0,providerName:"synthetic") } }, "original-engine-error")
let nonStringResult = try response(["cpim_base64":"AQID","session":42,"v3_constructor_fault":42]) { try boundaryProvider.parseStartProvisionResponse(code:0,outPtr:$0,providerName:"synthetic") }
checked(nonStringResult.cpim == Data([1,2,3]) && nonStringResult.session == 42)
for boundary in 0..<3 {
    do {
        if boundary == 0 { _ = try boundaryProvider.parseHeadersResponse(code:-1013,outPtr:nil,providerName:"synthetic") }
        else if boundary == 1 { _ = try boundaryProvider.parseStartProvisionResponse(code:-1013,outPtr:nil,providerName:"synthetic") }
        else { _ = try boundaryProvider.parseEndProvisionResponse(code:-1013,outPtr:nil,providerName:"synthetic") }
        fatalError("nil response must fail")
    } catch let error as AnisetteError {
        checked(error == .loaderFailed(reason:"synthetic loader returned nil (code: -1013)"))
    }
}
precondition(boundaryChecks == 77)
print("BOUNDED_FAULT_SWIFT_BOUNDARIES_PASS:\(boundaryChecks)")
