# Comprehensive authentication diagnostic wire gate

Reconstructed after workspace rollback. This is a new source review and hash freeze, not recovery of old approval or runtime evidence.

## Execution contract

Run the authentication-request and profile-provenance fake executables once to create their actual-model `cases.json` exports. Then:

1. `python3 -B test_generator.py --sources <acquired graph>`
2. `python3 -B generate_wire_fixture.py --sources <acquired graph> --output <output>`
3. Compile `service.swift` and `host.swift` independently with `swiftc -swift-version 5`.
4. Run `<output>/service <output>/wire-cases.plist auth-request/cases.json profile/cases.json` once.
5. Run `<output>/host <output>/wire-cases.plist` once.

The acquired graph contains LiveContainer, SideStore, and SideSign at SideStore/Dependencies/SideSign. Explicit `--sidestore-root`, `--livecontainer-root` and `--sidesign-root` options support export layouts. Optional `--run` additionally requires both `--auth-cases` and `--profile-cases`.

Exact required success lines:

- `PASS wire_service_real_codec_and_imported_cases`
- `PASS wire_host_real_decode_and_copy`

Additional lines report actual producer cases, exactly twice as many imported wire cases, total cases, and maximum observed binary/JSON failure bytes. `sources.json` hashes every production input and generated Swift file. Source generation is not compilation or runtime success.

## Actual source boundaries

The fixture extracts complete production service and host failure models, independent finite validators, the real lifecycle export helper, binary-plist encoder, nested result classifier, `CombinedFailure.decode`, the real visible renderer and Copy Details function body. It asserts that both actual lifecycle call sites take coherent collector snapshots and invoke the tested helper. Queued SignInOperation captures and rebinds the session collector. The exact UI terminal-transient clearing block is tested for six terminal and two ongoing states.

Every actual auth/profile exported snapshot traverses both previousFailure and terminal paths. Exact ar1/hp2/ap1 string equality is checked after service export and after host decode, not just the presence of display labels. The original primary error is deliberately stable in this wire suite. Actual parser behavior and typed-error mapping remain responsibilities of the auth suite and retained historical mapper/parser/context core, not a claim made by stable-primary wire vectors.

No collector execution is duplicated here: the service imports the outputs of the separately compiled actual-source auth/profile suites. No app, UIKit IPC runtime, clipboard, HTTP task, provider, Apple authentication, SRP, native library or guest is executed by this fixture.

## Privacy, capacity and scope

ar1 is bounded to 1024 bytes, hp2 to 512, ap1 to 256: at most 1792 bytes of new finite snapshot values. The entire failure, including primary fields, context keys, JSON escaping and binary-plist overhead, must fit 4096 bytes in both encodings; context must fit 20 keys. The existing chronological trace is at most 2048 bytes, but it has no unconditional reservation. Its oldest whole rows and then explicitly ancillary fields are trimmed first. Older probe and recovery annotations are evicted atomically only after chronology and fingerprints when required to reserve primary/native and current observations. Decisive request/profile/acquisition observations, original error identity and native constructor evidence are not displaced by old chronology or fingerprints. Trimming/rejection is explicit. Unknown keys are not silently discarded to make an invalid context validate.

Valid, malformed and wrong-type new optional values are tested at a full original 20-key context through init, decode, nested IPC and copy. Additional vectors include maximum finite native/profile/request fields, repeated ordinals, duplicate history, unknown schema, malformed/out-of-range/overlong values, hostile sentinels, fresh attempts, timeout/cancellation after an accepted request, each new diagnostic retained independently without the old trace, dense native20 capacity, 35 legacy shape/MIME pairs, invalid labels/HTTP/typed associations and absent-context HTTP418.

Only finite enum, shape, primitive-type, bounded count and relative-time observations are copied. No raw request/body/header/account/device/credential/blob/proof values or hashes of those values are introduced. Provenance library identity/verification is generation-selected/verified, not loaded mapping or Apple acceptance. Cache-return input equality is a historical UTF-8 comparison of requested versus cached client-info, separate from family relation and any later-mutated header. Acquisition events remain separate with request association explicitly unobserved. An earlier or accepted request is not labelled the cause of a later failure.
