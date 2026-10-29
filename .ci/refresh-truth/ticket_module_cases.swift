import Foundation
import SideStoreSupport
let runID = "11111111-1111-4111-8111-111111111111"
let ticket = V3RefreshUncertaintyTicket(runID: runID, updatedAt: 1)
let record: [String: Any] = ["run_id": runID, "state": "failed", "updated_at": 1.0]
func permits(_ value: V3RefreshUncertaintyTicket) -> Bool {
    V3RefreshUncertaintyAcknowledgmentPolicy.canAcknowledge(ticket: value, marker: runID, record: record,
        activeRunID: nil, hostHandoffPending: false, directClaimPresent: false)
}
precondition(permits(ticket))
precondition(!permits(V3RefreshUncertaintyTicket(runID: "invalid", updatedAt: 1)))
precondition(!permits(V3RefreshUncertaintyTicket(runID: runID, updatedAt: .nan)))
precondition(!permits(V3RefreshUncertaintyTicket(runID: runID, updatedAt: 2)))
print("TICKET_CROSS_MODULE_PASS")
