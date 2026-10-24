struct CaseResult: Codable {
    let name: String
    let passed: Bool
}
func resetPreferences() {
    testDefaults.removePersistentDomain(forName: testSuiteName)
    testDefaults.removeVolatileDomain(forName: UserDefaults.registrationDomain)
    AuthManager.shared.calls = 0
    ProfileManager.shared.calls = 0
}
func registerExtractedFalseDefaults() { testDefaults.register(defaults: extractedRegistrationDefaults) }
func persistedTrueThenRegisterFalse(_ key: String) throws {
    testDefaults.set(true, forKey: key)
    try require(testDefaults.persistentDomain(forName: testSuiteName)?[key] as? Bool == true,
                "Expected persisted true before registration for \(key)")
    registerExtractedFalseDefaults()
    // MUTATION_POINT_DROP_PERSISTED_TRUE
    try require(testDefaults.bool(forKey: key), "Registering false must not erase persisted true for \(key)")
    try require(testDefaults.persistentDomain(forName: testSuiteName)?[key] as? Bool == true,
                "Persisted true must remain after registration for \(key)")
}
func expectInvalid(_ message: String, _ body: () async throws -> Void) async throws {
    do { try await body() }
    catch let error as OperationError {
        try require(error == .invalidParameters(message), "Wrong unsupported/guard error: \(error)")
        return
    }
    catch { throw FixtureFailure.assertion("Unexpected error type: \(error)") }
    throw FixtureFailure.assertion("Expected exact invalidParameters error: \(message)")
}
func assertUntouched(_ context: InstallAppOperationContext, _ handler: DefaultHostHandler) throws {
    try require(handler.bundleCalls == 0 && handler.groupCalls == 0, "No handler prompt should be requested")
    try require(context.customBundleIdentifier == nil && context.customInfoPlistByBundleID.isEmpty
                && context.customEntitlementsByBundleID.isEmpty && context.additionalEntitlements.isEmpty,
                "Customization state changed unexpectedly")
    try require(context.overrideProvisioningProfile == nil, "Provisioning profile changed unexpectedly")
    switch context.alternateIconMode {
    case .unchanged: break
    case .set: throw FixtureFailure.assertion("Icon state changed unexpectedly")
    }
    try require(AuthManager.shared.calls == 0 && context.dbBackgroundContext.fetchCalls == 0
                && ProfileManager.shared.calls == 0, "A boundary was crossed unexpectedly")
}
func emit<T: Encodable>(_ value: T) {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    let data = try! encoder.encode(value)
    print(String(data: data, encoding: .utf8)!)
}
@main struct GroupBFixture {
    static func main() async {
        var results: [CaseResult] = []
        func run(_ name: String, _ body: () async throws -> Void) async {
            resetPreferences()
            do {
                try await body()
                let result = CaseResult(name: name, passed: true)
                results.append(result)
            } catch {
                let result = CaseResult(name: name, passed: false)
                results.append(result)
                FileHandle.standardError.write(Data("\(name): \(error)\n".utf8))
            }
        }
        await run("absent_preferences_no_handler_nil_result") {
            try require(featureKeys.allSatisfy { testDefaults.object(forKey: $0) == nil }, "Expected absent preferences")
            let handler = DefaultHostHandler()
            let context = InstallAppOperationContext(handler: handler)
            let operation = UserCustomizationOperation(context: context)
            let result = try await operation.execute(parentProgress: nil)
            try require(result == nil, "Absent preferences should return nil")
            try require(operation.preconditionCalls == 1 && operation.progressValues == [10, 100], "Real execute progress/precondition path not taken")
            try assertUntouched(context, handler)
        }
        await run("registered_false_preferences_no_handler_nil_result") {
            registerExtractedFalseDefaults()
            try require(featureKeys.allSatisfy { !testDefaults.bool(forKey: $0) }, "Expected registered false values")
            try require(featureKeys.allSatisfy { testDefaults.persistentDomain(forName: testSuiteName)?[$0] == nil }, "Registration must not persist feature values")
            let handler = DefaultHostHandler()
            let context = InstallAppOperationContext(handler: handler)
            let result = try await UserCustomizationOperation(context: context).execute(parentProgress: nil)
            try require(result == nil, "Registered false preferences should return nil")
            try assertUntouched(context, handler)
        }
        await run("persisted_false_preferences_no_handler_nil_result") {
            for key in featureKeys { testDefaults.set(false, forKey: key) }
            registerExtractedFalseDefaults()
            let handler = DefaultHostHandler()
            let context = InstallAppOperationContext(handler: handler)
            let result = try await UserCustomizationOperation(context: context).execute(parentProgress: nil)
            try require(result == nil, "Persisted false preferences should return nil")
            try assertUntouched(context, handler)
        }
        let unsupported: [(String, String, [Int64], Int, Int)] = [
            ("customizeInfoPlist", "Info.plist customization requires a supported host prompt.", [10, 40], 1, 1),
            ("customizeEntitlements", "Entitlement customization requires a supported host prompt.", [10, 70], 1, 0),
            ("customizeAppIcon", "Icon customization requires a supported host prompt.", [10, 85], 0, 0),
            ("customizeProvisioningProfile", "Provisioning profile customization requires a supported host prompt.", [10, 95], 0, 0),
        ]
        for (key, expectedError, expectedProgress, expectedAuth, expectedDB) in unsupported {
            await run("persisted_true_\(key)_survives_registration_and_reaches_actual_default") {
                try persistedTrueThenRegisterFalse(key)
                let handler = DefaultHostHandler()
                let context = InstallAppOperationContext(handler: handler)
                let operation = UserCustomizationOperation(context: context)
                try await expectInvalid(expectedError) { _ = try await operation.execute(parentProgress: nil) }
                try require(operation.preconditionCalls == 1 && operation.progressValues == expectedProgress,
                            "Unexpected branch progress for \(key)")
                try require(AuthManager.shared.calls == expectedAuth && context.dbBackgroundContext.fetchCalls == expectedDB,
                            "Unexpected Auth/DB boundary path for \(key)")
                try require(handler.bundleCalls == 0 && handler.groupCalls == 0 && ProfileManager.shared.calls == 0,
                            "Unsupported workflow should not fall through to another prompt or profile assignment")
            }
        }
        await run("persisted_true_app_id_supported_default_choice") {
            try persistedTrueThenRegisterFalse("customizeAppId")
            let handler = DefaultHostHandler()
            let context = InstallAppOperationContext(handler: handler)
            let operation = UserCustomizationOperation(context: context)
            let result = try await operation.execute(parentProgress: nil)
            try require(handler.bundleCalls == 1 && handler.groupCalls == 0, "Supported App ID handler must be called once")
            try require(result == "example.imported" && context.customBundleIdentifier == nil && context.appendTeamID,
                        "Default App ID choice must preserve identity")
            try require(operation.progressValues == [10, 40, 100] && AuthManager.shared.calls == 0, "Wrong supported App ID path")
        }
        await run("supported_app_id_cancel_propagates") {
            try persistedTrueThenRegisterFalse("customizeAppId")
            let handler = DefaultHostHandler()
            handler.bundleResult = nil
            let operation = UserCustomizationOperation(context: InstallAppOperationContext(handler: handler))
            do { _ = try await operation.execute(parentProgress: nil) }
            catch let error as OperationError {
                try require(error == .cancelled && handler.bundleCalls == 1, "Wrong App ID cancellation")
                return
            }
            throw FixtureFailure.assertion("Expected App ID cancellation")
        }
        await run("nil_target_guard_preserved_with_all_flags_false") {
            registerExtractedFalseDefaults()
            let handler = DefaultHostHandler()
            let context = InstallAppOperationContext(handler: handler)
            context.targetAppBundle = nil
            let operation = UserCustomizationOperation(context: context)
            try await expectInvalid("UserCustomizationOperation: context.targetAppBundle is nil") {
                _ = try await operation.execute(parentProgress: nil)
            }
            try require(operation.progressValues == [10], "Nil target guard changed")
            try assertUntouched(context, handler)
        }
        await run("store_update_skips_true_flags_and_nil_target") {
            for key in featureKeys { testDefaults.set(true, forKey: key) }
            registerExtractedFalseDefaults()
            let handler = DefaultHostHandler()
            let context = InstallAppOperationContext(handler: handler)
            context.isStoreUpdate = true
            context.targetAppBundle = nil
            let operation = UserCustomizationOperation(context: context)
            let result = try await operation.execute(parentProgress: nil)
            try require(result == nil && operation.progressValues == [10, 100] && operation.preconditionCalls == 1,
                        "Store-update early return changed")
            try assertUntouched(context, handler)
        }
        await run("direct_default_info_plist_targets_exact_error") {
            let handler: any UserCustomizationHandler = DefaultHostHandler()
            try await expectInvalid("Info.plist customization requires a supported host prompt.") {
                _ = try await handler.resolveInfoPlistCustomization(targets: [], initialBundleID: "example.imported", appendTeamID: true, installedAppIdentities: [:], teamID: "FIXTURETEAM")
            }
        }
        await run("direct_default_info_plist_single_exact_error") {
            let handler: any UserCustomizationHandler = DefaultHostHandler()
            try await expectInvalid("Info.plist customization requires a supported host prompt.") {
                _ = try await handler.resolveInfoPlistCustomization(initialPlist: [:], initialBundleID: "example.imported", appendTeamID: true, installedAppIdentities: [:], teamID: "FIXTURETEAM")
            }
        }
        await run("direct_default_entitlements_targets_exact_error") {
            let handler: any UserCustomizationHandler = DefaultHostHandler()
            try await expectInvalid("Entitlement customization requires a supported host prompt.") {
                _ = try await handler.resolveEntitlementsCustomization(targets: [], teamType: .free)
            }
        }
        await run("direct_default_entitlements_single_exact_error") {
            let handler: any UserCustomizationHandler = DefaultHostHandler()
            try await expectInvalid("Entitlement customization requires a supported host prompt.") {
                _ = try await handler.resolveEntitlementsCustomization(initialEntitlements: [:], bundleID: "example.imported", teamType: .free)
            }
        }
        await run("direct_default_icon_exact_error") {
            let handler: any UserCustomizationHandler = DefaultHostHandler()
            try await expectInvalid("Icon customization requires a supported host prompt.") {
                _ = try await handler.resolveAppIconCustomization(appName: "Ordinary Imported IPA")
            }
        }
        await run("direct_default_provisioning_exact_error") {
            let handler: any UserCustomizationHandler = DefaultHostHandler()
            try await expectInvalid("Provisioning profile customization requires a supported host prompt.") {
                _ = try await handler.resolveProvisioningProfileCustomization(appName: "Ordinary Imported IPA", bundleID: "example.imported")
            }
        }
        resetPreferences()
        struct Report: Codable {
            let schema: String
            let group: String
            let cases: [CaseResult]
            let passed: Bool
            let native_signing_device_executed: Bool
        }
        let failures = results.filter { !$0.passed }.count
        emit(Report(schema: "install-chain-runtime-v1", group: "customization", cases: results,
                    passed: failures == 0, native_signing_device_executed: false))
        if failures != 0 { exit(1) }
    }
}
