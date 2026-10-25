import Foundation

let upgrades = [
    ("0.4.21-beta", "0.4.26"), ("1.0.0-beta.2", "1.0.0-beta.10"),
    ("1.0.0-beta", "1.0.0"), ("1.2", "1.3"), ("1", "2"),
    ("1.0.0-alpha", "1.0.0-beta"), ("1.0.0-1", "1.0.0-alpha"),
    ("1.0.0-alpha", "1.0.0-alpha.1"),
    ("1.0.0-beta.99999999999999999999999", "1.0.0-beta.100000000000000000000000")
]
for (installed, available) in upgrades {
    precondition(V3SourceVersionPolicy.isUpgrade(installed: installed, available: available), "Missing upgrade: \(installed) -> \(available)")
    precondition(!V3SourceVersionPolicy.isUpgrade(installed: available, available: installed), "Downgrade advertised as upgrade")
}
for (installed, available) in [
    ("1.0", "1.0.0"), ("1.2.3+abc", "1.2.3+xyz"), ("1.0", "1.0"),
    ("", "1.0"), ("1.0", "Unavailable"), ("v1.0", "v2.0"),
    ("1.0", "2.0-"), ("1.0", "2.0+"), ("1.0", "2.0+bad+metadata"),
    ("1.0", "2.0-beta.01"), ("1.0", "2..0"), ("1.0", "2.0.0.1"), ("1.0", "99999999999999999999999999.0")
] {
    precondition(!V3SourceVersionPolicy.isUpgrade(installed: installed, available: available), "Unknown/equal scheme marked upgrade")
}
let now = Date(timeIntervalSince1970: 1000)
let future = now.addingTimeInterval(90)
let row = V3DeveloperAppID(["identifier": "test", "name": "Synthetic", "bundleID": "example.synthetic", "expirationDate": future])!
precondition(row.expirationDate == future)
precondition(row.remainingSeconds(at: now) == 90)
precondition(row.remainingSeconds(at: future) == 0)
precondition(row.remainingSeconds(at: future.addingTimeInterval(1)) == 0)
precondition(V3DeveloperAppID(["identifier": "unknown"])!.remainingSeconds(at: now) == nil)
precondition(V3DeveloperAppID(["identifier": "invalid", "expirationDate": "tomorrow"])!.expirationDate == nil)
precondition(V3DeveloperAppID(["identifier": "nonfinite", "expirationDate": Date(timeIntervalSinceReferenceDate: .infinity)])!.expirationDate == nil)
precondition(V3DeveloperAppID(["identifier": ""]) == nil)
precondition(V3DeveloperAppID([:]) == nil)
print("SOURCE_APP_PRESENTATION_PASS")
