let fixtureRun = "11111111-1111-1111-1111-111111111111"
let fixtureRequest = "22222222-2222-2222-2222-222222222222"

@main struct ColdVPNObservationCases {
    @MainActor
    static func timeline(wifiAt: Double? = 0, tunnelAt: Double? = 0,
                         backgroundAt: Double? = nil, loseOwnership: String? = nil,
                         cancelDuringSleep: Bool = false, frozenClock: Bool = false,
                         reverseClock: Bool = false) async -> (String, Double, Int, Int) {
        let task = Task { @MainActor () -> (String, Double, Int, Int) in
            var clock = 0.0, observations = 0, sleeps = 0
            var owned = loseOwnership != "initial"
            do {
                let outcome = try await LiveContainerVPNPostActivationPolicy.wait(now: { clock }, observe: {
                    observations += 1
                    if loseOwnership == "observation" { owned = false }
                    return .init(wifi: wifiAt.map { clock >= $0 }, tunnel: tunnelAt.map { clock >= $0 } ?? false,
                                 background: backgroundAt.map { clock >= $0 } ?? false)
                }, ownsRun: { owned }, sleep: { nanoseconds in
                    sleeps += 1
                    precondition(nanoseconds <= 250_000_000)
                    if cancelDuringSleep { withUnsafeCurrentTask { $0?.cancel() }; try Task.checkCancellation() }
                    if loseOwnership == "sleep" { owned = false }
                    if reverseClock { clock = -1 }
                    else if !frozenClock { clock += Double(nanoseconds) / 1_000_000_000 }
                })
                return (String(describing: outcome), clock, observations, sleeps)
            } catch is CancellationError { return ("cancelled", clock, observations, sleeps) }
            catch { return ("unexpected", clock, observations, sleeps) }
        }
        return await task.value
    }
    @MainActor static func main() async throws {
        var names = [String]()
        func check(_ name: String, _ value: Bool) { precondition(value, name); names.append(name) }
        let immediate = await timeline()
        check("immediate_interface_observation_has_no_fixed_sleep", immediate.0 == "observed" && immediate.1 == 0 && immediate.3 == 0)
        let delayed = await timeline(wifiAt: 1.25, tunnelAt: 2.5)
        check("delayed_wifi_and_interface_observed_in_same_attempt", delayed.0 == "observed" && delayed.1 == 2.5)
        let missingTunnel = await timeline(tunnelAt: nil)
        check("missing_interface_stops_at_monotonic_deadline", missingTunnel.0 == "tunnelUnavailable" && missingTunnel.1 == 10 && missingTunnel.3 == 40)
        let unknownWiFi = await timeline(wifiAt: nil)
        check("unknown_wifi_remains_pending_then_times_out", unknownWiFi.0 == "wifiUnavailable" && unknownWiFi.1 == 10)
        let missingWiFi = await timeline(wifiAt: 20)
        check("unavailable_wifi_remains_pending_then_times_out", missingWiFi.0 == "wifiUnavailable" && missingWiFi.1 == 10)
        let late = await timeline(tunnelAt: 10)
        check("readiness_at_expired_deadline_not_accepted", late.0 == "tunnelUnavailable" && late.1 == 10)
        let initialStale = await timeline(loseOwnership: "initial")
        check("initial_stale_owner_never_observed", initialStale.0 == "cancelled" && initialStale.2 == 0)
        let changedDuringObservation = await timeline(loseOwnership: "observation")
        check("ownership_lost_during_observation_cannot_succeed", changedDuringObservation.0 == "cancelled" && changedDuringObservation.3 == 0)
        let changedDuringSleep = await timeline(tunnelAt: 2, loseOwnership: "sleep")
        check("ownership_lost_during_sleep_stops_next_probe", changedDuringSleep.0 == "cancelled" && changedDuringSleep.2 == 1)
        let cancelled = await timeline(tunnelAt: 2, cancelDuringSleep: true)
        check("task_cancellation_during_wait_is_terminal", cancelled.0 == "cancelled" && cancelled.3 == 1)
        let background = await timeline(tunnelAt: 2, backgroundAt: 0.5)
        check("host_background_after_return_cancels_predispatch", background.0 == "cancelled" && background.1 == 0.5)
        let frozen = await timeline(tunnelAt: nil, frozenClock: true)
        check("broken_clock_has_finite_observation_bound", frozen.0 == "tunnelUnavailable" && frozen.2 == 128)
        let reversed = await timeline(tunnelAt: nil, reverseClock: true)
        check("reversed_clock_fails_closed", reversed.0 == "cancelled")
        var record: [String:Any] = ["run_id":fixtureRun,"request_id":fixtureRequest,"source":"manual","state":"running"]
        func owned(memory:String? = fixtureRun, stored:String? = fixtureRun, expected:String? = fixtureRun,
                   request:String? = fixtureRequest, finished:Bool = false, handoff:Bool = false,
                   uncertain:String? = nil) -> Bool {
            LiveContainerVPNPostActivationOwnership.matches(runID:fixtureRun,requestID:fixtureRequest,
                source:"manual",inMemoryRunID:memory,storedRunID:stored,expectedRunID:expected,
                storedRequestID:request,record:record,gateFinished:finished,
                hostHandoffPending:handoff,uncertainMutationRunID:uncertain)
        }
        check("exact_current_run_and_request_owned", owned())
        check("different_in_memory_run_rejected", !owned(memory:fixtureRequest))
        check("different_persisted_run_rejected", !owned(stored:fixtureRequest))
        check("different_expected_run_rejected", !owned(expected:fixtureRequest))
        check("different_request_rejected", !owned(request:fixtureRun))
        check("finished_completion_gate_rejected", !owned(finished:true))
        check("pending_host_handoff_rejected", !owned(handoff:true))
        check("uncertain_mutation_rejected", !owned(uncertain:fixtureRun))
        record["state"]="failed"
        check("terminal_ledger_rejected", !owned())
        record["state"]="running";record["source"]="bgprocessing"
        check("changed_trigger_source_rejected", !owned())
        record["source"]="manual";record["request_id"]=fixtureRun
        check("changed_ledger_request_rejected", !owned())
        record["request_id"]=fixtureRequest;record["run_id"]=fixtureRequest
        check("changed_ledger_run_rejected", !owned())
        let data: [String:Any] = ["status":"PASS", "cases":names,"case_count":names.count,
            "network_executed":false,"device_executed":false,"transport_readiness_proven":false,
            "mutation_dispatched":false]
        try JSONSerialization.data(withJSONObject:data,options:[.sortedKeys,.prettyPrinted])
            .write(to:URL(fileURLWithPath:CommandLine.arguments[1]))
        print("COLD_VPN_TIMELINES_PASS cases=\(names.count)")
    }
}
