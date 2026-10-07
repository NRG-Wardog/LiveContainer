//
//  SideStoreClient.swift
//  SideStoreSupport
//
//  Created by s s on 2025/7/20.
//

import Foundation
import AppIntents
import OSLog

enum SideStoreIntentError: LocalizedError {
    case typeNotFound(String)
    case typeIsNotAppIntent(String)

    var errorDescription: String? {
        switch self {
        case .typeNotFound(let name):
            return "SideStore refresh intent type was not found: \(name)"
        case .typeIsNotAppIntent(let name):
            return "SideStore type is not an AppIntent: \(name)"
        }
    }
}

@available(iOS 17.0, *)
private func resolveType(_ mangledTypeName: String) throws -> any Any.Type {
    let bytes = Array(mangledTypeName.utf8)
    let resolvedType: Any.Type? = bytes.withUnsafeBufferPointer { buffer in
        guard let baseAddress = buffer.baseAddress else {
            return nil
        }

        // Swift exposes the runtime symbol swift_getTypeByMangledNameInContext
        // as _getTypeByMangledNameInContext. The name intentionally omits
        // the "$s" prefix, which is the form accepted for this module.
        return _getTypeByMangledNameInContext(
            baseAddress,
            UInt(buffer.count),
            genericContext: nil,
            genericArguments: nil
        )
    }

    guard let resolvedType else {
        throw SideStoreIntentError.typeNotFound(mangledTypeName)
    }

    return resolvedType
}

@available(iOS 17.0, *)
struct SideStoreIntentCaller {
    static let shared = SideStoreIntentCaller()
    
    // call this when a IntentContext already exists (when sidestore is loaded in LiveContainer itself)
    func callRefreshIntent(mangledTypeName: String) async throws {
        let resolvedType = try resolveType(mangledTypeName)
        guard let intentType = resolvedType as? any ProgressReportingIntent.Type else {
            throw SideStoreIntentError.typeIsNotAppIntent(mangledTypeName)
        }
        
        let intent = intentType.init()
        let _ = try await intent.perform()
    }
    
    // call this when no IntentContext exists (when sidestore is loaded in LiveProcess)
    func callRefreshIntent2(identifier: String, mangledTypeName: String, progressCallback: (Progress)->Void ) async throws {
        try await withUnsafeThrowingContinuation { (c: UnsafeContinuation<(), any Error>) in
            let parent = PrivateIntentRunner.run(
                        identifier: identifier,
                        mangledTypeName: mangledTypeName
                    ) { result, error in
                        print("performAction result=\(String(describing: result)), " +
                              "error=\(String(describing: error))")
                        if let error {
                            c.resume(throwing: error)
                        } else {
                            c.resume()
                        }
                    }
            if let parent {
                progressCallback(parent)
            }
        }
    }
}

@available(iOS 17.0, *)
@objc extension SideStoreClient {

    // LC_REFRESH_RESULT_XPC_V1: bounded, allowlisted non-secret metadata only.
    // V3_RUNTIME_SHARED_REFRESH_STORE_V1: the same runtime App Group the service
    // wrote the manifest into. Without it the result is reported unconfirmed
    // rather than read from a store the service can never have written.
    func reportRefreshResult(_ error: String?, server: any RefreshServer) {
        guard let defaults = V3SharedAppGroup.sharedUserDefaults() else {
            server.finish("SideStore could not open its refresh-state store. Refresh is unconfirmed.")
            return
        }
        guard let runID = defaults.string(forKey: "liveContainerAutoRefreshExpectedRunID") else {
            server.finish(error)
            return
        }
        var payload: [String: Any] = [:]
        for key in ["liveContainerAutoRefreshVerification", "liveContainerAutoRefreshHostHandoff", "liveContainerAutoRefreshHostHandoffRunID", "liveContainerAutoRefreshHostHandoffStartedAt", "liveContainerAutoRefreshHostPreviousExpiration"] {
            if let value = defaults.object(forKey: key) { payload[key] = value }
        }
        do {
            payload = CombinedVerification.sanitized(payload, runID: runID)
            let data = try PropertyListSerialization.data(fromPropertyList: payload, format: .binary, options: 0)
            guard data.count <= 262144 else {
                server.finishRefresh("SideStore's verification results exceeded the allowed size.", runID: runID, verification: nil)
                return
            }
            server.finishRefresh(error, runID: runID, verification: data)
        } catch {
            server.finishRefresh(CombinedFailure.capture(error, operation: "refresh", stage: .refreshVerification, id: runID).encodedString, runID: runID, verification: nil)
        }
    }

    @objc(performRefreshForRealWithIdentifier:mangledTypeName:server:)
    func performRefreshForReal(identifier: String, mangledTypeName: String, server: any RefreshServer) {
        Task {
            do {
                var obs: NSKeyValueObservation? = nil
                try await SideStoreIntentCaller.shared.callRefreshIntent2(identifier: identifier, mangledTypeName: mangledTypeName) { progress in
                    obs = progress.observe(\.fractionCompleted, options: [.new]) { progress, change in
                        if let newValue = change.newValue {
                            server.updateProgress(newValue)
                        }
                    }
                }
                obs?.invalidate()
                reportRefreshResult(nil, server: server)
            } catch {
                reportStructuredRefreshFailure(error, server: server)
            }
        }
    }

}

    @available(iOS 17.0, *)
    extension SideStoreClient {
    func reportStructuredRefreshFailure(_ error: Error, server: any RefreshServer) {
        // V3_RUNTIME_SHARED_REFRESH_STORE_V1: the expected run ID is written by
        // the host scheduler into the one runtime App Group, and read back by the
        // embedded service. A fixed suite name correlates the failure to a run
        // the service never began.
        let id = V3SharedAppGroup.sharedUserDefaults()?.string(forKey: "liveContainerAutoRefreshExpectedRunID") ?? UUID().uuidString
        reportRefreshResult(CombinedFailure.capture(error, operation: "refresh", stage: .command, id: id).encodedString, server: server)
    }
}
