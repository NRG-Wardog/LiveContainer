@main struct PortalHostCases {
    static let id = "00000000-0000-0000-0000-000000000001"
    static func check(_ value: @autoclosure () -> Bool, _ name: String) { precondition(value(), name) }
    static func main() throws {
        precondition(CommandLine.arguments.count == 3)
        let input = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let rows = try PropertyListSerialization.propertyList(from: input, format: nil) as! [[String: Any]]
        var names = Set<String>()
        var reports: [[String: Any]] = []
        for row in rows {
            let name = row["name"] as! String
            check(names.insert(name).inserted, "unique names")
            let data = row["response"] as! Data
            let candidate = row["candidate"] as! Bool
            do {
                let result = try V3CatalogRequestContext.classifyReply(data, operation: "certPortalList", id: id)
                check(name == "success_unchanged", "failure must not become success")
                check((result["certificates"] as! [[String: Any]]).isEmpty, "original empty success transported")
            } catch let failure as CombinedFailure {
                check(name != "success_unchanged", "success must not become failure")
                let remoteIdentity = name.hasPrefix("remoteIdentity")
                check(failure.operation == "certPortalList", "command operation preserved through actual host parser")
                if !remoteIdentity {
                    check(failure.stage == .signing && failure.sourceStep == .fetchCertificate, "command identity preserved through actual host parser")
                }
                check(failure.correlationID == id && failure.code == .failed, "original primary classification preserved")
                let copy = V3DiagnosticCopy.details(visibleMessage: failure.safeMessage, technical: failure.technicalDetails)
                check(copy.contains("operation=certPortalList"), "Copy retains operation")
                if !remoteIdentity { check(copy.contains("source_step=fetchCertificate"), "Copy retains certificate source") }
                for secret in ["SECRET_", "NEW_IDENTIFIER", "PRIVATE", "lc_stage=installation", "quota", "X-Fixture", "https://", "fixture-serial"] {
                    check(!copy.contains(secret), "Copy rejects raw provider, request, and certificate information")
                }
                if remoteIdentity {
                    let typed = row["typed"] as! String
                    let token = row["token"] as! String
                    check(row["direct_and_wrapped_verified"] as? Bool == true, "both actual NSError chains reached service capture")
                    let recovered = failure.stage == .authentication && failure.sourceStep == .anisetteFetch &&
                        failure.signingContext["typed_error"] == typed && copy.contains("typed_error=" + typed) &&
                        copy.contains("-" + token)
                    check(recovered == candidate, "same local identity evidence absent before and present after")
                    check(failure.signingContext["anisette_blob_state"] == "existing" &&
                          failure.signingContext["anisette_recovery"] == "notAttempted",
                          "validated outer context survives actual IPC host decode")
                    do {
                        _ = try V3CatalogRequestContext.classifyReply(row["incompatible_response"] as! Data,
                            operation: "certPortalList", id: id)
                        preconditionFailure("incompatible context must remain a failure")
                    } catch let trimmed as CombinedFailure {
                        let trimmedCopy = V3DiagnosticCopy.details(visibleMessage: trimmed.safeMessage,
                            technical: trimmed.technicalDetails)
                        if candidate {
                            check(trimmed.stage == .authentication && trimmed.sourceStep == .anisetteFetch &&
                                  trimmed.signingContext["typed_error"] == typed && trimmedCopy.contains("-" + token) &&
                                  trimmedCopy.contains("auth_diagnostic_state=trimmed"),
                                  "decisive identity diagnosis survives incompatible outer tuple through actual Copy")
                            check(trimmed.signingContext["auth_response_shape"] == nil &&
                                  trimmed.signingContext["auth_response_mime"] == nil,
                                  "host accepts explicitly trimmed incompatible optional observations")
                        } else {
                            check(trimmed.signingContext["typed_error"] == "sideSignInvalidResponse" &&
                                  !trimmedCopy.contains("-" + token), "baseline has no fabricated local identity mapping")
                        }
                        check(!trimmedCopy.contains("SECRET_") && !trimmedCopy.contains("PRIVATE"),
                              "incompatible tuple never exposes private userInfo")
                    }
                    let negatives = row["negative_controls"] as! [[String: Any]]
                    check(negatives.map { $0["kind"] as! String } == ["wrong_domain", "unknown_code", "outer_cancellation"],
                          "all three finite-domain and cancellation negative controls reach host")
                    for negative in negatives {
                        let kind = negative["kind"] as! String
                        do {
                            _ = try V3CatalogRequestContext.classifyReply(negative["response"] as! Data,
                                operation: "certPortalList", id: id)
                            preconditionFailure("negative control must remain a failure")
                        } catch let controlled as CombinedFailure {
                            let negativeCopy = V3DiagnosticCopy.details(visibleMessage: controlled.safeMessage,
                                technical: controlled.technicalDetails)
                            check(controlled.code == (kind == "outer_cancellation" ? .cancelled : .failed),
                                  "host preserves outer cancellation and generic unknown identity failures")
                            check(controlled.signingContext["typed_error"] != typed && !negativeCopy.contains("-" + token),
                                  "host never invents a finite identity kind from unmatched or cancelled causes")
                            check(!negativeCopy.contains("SECRET_") && !negativeCopy.contains("PRIVATE"),
                                  "negative-control userInfo cannot leak to Copy")
                        }
                    }
                    if candidate {
                        check(failure.retryable == false && failure.safeCause == nil, "local failure cannot gain retry or provider cause")
                        check(copy.contains("stage=authentication") && copy.contains("source_step=anisetteFetch"),
                              "finite local identity responsibility reaches actual Copy")
                        check(failure.signingContext["provider_code"] == nil && failure.signingContext["http_status"] == "418" &&
                              failure.signingContext["server_code"] == "42" && copy.contains("http_status=418") && copy.contains("server_code=42"),
                              "validated observed HTTP and server facts survive without provider inference")
                    }
                } else if name == "network_primary_preserved" {
                    check(failure.underlyingDomain == NSURLErrorDomain && failure.underlyingCode == NSURLErrorTimedOut, "network error not converted to portal server error")
                    check(failure.signingContext["provider_code"] == nil, "no fabricated provider evidence for transport")
                } else {
                    check(failure.underlyingDomain == "SideSign.ServerError" && failure.underlyingCode == row["ordinal"] as! Int, "original ServerError ordinal remains distinct from Apple result code")
                    check(failure.signingContext["typed_error"] == row["typed"] as? String, "typed primary preserved")
                    let http = row["http"] as! String
                    let provider = row["provider"] as! String
                    check(failure.signingContext["http_status"] == http && copy.contains("http_status=\(http)"), "finite HTTP reaches Copy")
                    if provider == "absent" {
                        check(failure.signingContext["provider_code"] == nil, "delivered omission reproduced")
                    } else {
                        check(failure.signingContext["provider_code"] == provider && copy.contains("provider_code=\(provider)"), "allowlisted provider code reaches Copy")
                    }
                    check(!copy.contains("server_code=-1"), "detail-only sentinel must not masquerade as Apple result code")
                    if row["ordinal"] as! Int == 3 {
                        check(copy.contains("server_code=\(row["server"] as! String)"), "numeric result semantics preserved")
                    }
                    if name == "known_entity_422" {
                        let diagnosticRecovered = copy.contains("http_status=422") && copy.contains("provider_code=ENTITY_ERROR")
                        check(diagnosticRecovered == candidate, "same desired evidence assertion fails before and passes after")
                    }
                }
                reports.append(["name": name, "copy": copy, "candidate": candidate])
            }
            print("PASS portal_host_\(name)")
        }
        check(names.count == 19, "complete original 15-row portal plus four local identity JSON-to-IPC-to-Copy cases")
        let report: [String: Any] = ["schema": "portal-evidence-runtime-v1", "status": "pass",
            "candidate": rows[0]["candidate"] as! Bool, "case_count": names.count,
            "cases": names.sorted(), "diagnostics": reports, "fake_only": true,
            "native_provider_executed": false, "network_executed": false]
        try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys, .prettyPrinted])
            .write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
        print("PASS portal_json_ipc_copy cases=\(names.count)")
    }
}
