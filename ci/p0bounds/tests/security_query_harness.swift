func verifyScope(_ raw: CFDictionary) {
    let query = raw as NSDictionary
    precondition(query[kSecClass] as? String == (kSecClassGenericPassword as String))
    precondition(query[kSecAttrService] as? String == "fixture.pending-certificate")
    precondition(query[kSecAttrAccessGroup] as? String == "fixture.group")
    precondition(query[kSecAttrAccount] as? String == "pending-create-v1")
    precondition(query[kSecAttrSynchronizable] as? Bool == false)
    precondition(query[kSecAttrAccessible] as? String == (kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String))
    precondition(query[kSecUseDataProtectionKeychain] as? Bool == true)
}
enum V3PendingCertificateCreationError: Error { case storageUnverified }
@main struct Main {
    static func main() throws {
        var bytes: Data?, reads = 0, adds = 0, updates = 0, deletes = 0
        var calls = V3PendingCertificateKeychainCalls()
        calls.copyMatching = { query, out in
            verifyScope(query); reads += 1
            if let bytes { out?.pointee = bytes as CFData; return errSecSuccess }
            return errSecItemNotFound
        }
        calls.update = { query, raw in
            verifyScope(query); updates += 1
            guard bytes != nil else { return errSecItemNotFound }
            let attributes = raw as NSDictionary
            precondition(attributes.count == 1)
            bytes = attributes[kSecValueData] as? Data
            return errSecSuccess
        }
        calls.add = { query, _ in
            verifyScope(query); adds += 1
            precondition(bytes == nil)
            bytes = (query as NSDictionary)[kSecValueData] as? Data
            return errSecSuccess
        }
        calls.delete = { query in verifyScope(query); deletes += 1; bytes = nil; return errSecSuccess }
        let client = V3PendingCertificateKeychainClient(service: "fixture.pending-certificate", accessGroup: "fixture.group", calls: calls)
        let empty = try client.getData("pending-create-v1"); precondition(empty == nil)
        try client.set(Data([1,2]), key: "pending-create-v1")
        let first = try client.getData("pending-create-v1"); precondition(first == Data([1,2]))
        try client.set(Data([3,4]), key: "pending-create-v1")
        let second = try client.getData("pending-create-v1"); precondition(second == Data([3,4]))
        try client.remove("pending-create-v1")
        let final = try client.getData("pending-create-v1"); precondition(final == nil)
        precondition(reads == 4 && adds == 1 && updates == 2 && deletes == 1)
        print("PENDING_CERTIFICATE_EXACT_SECURITY_SCOPE_PASS")
    }
}
