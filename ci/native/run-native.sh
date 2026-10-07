#!/usr/bin/env bash
# Test-only acquisition, build and account-free execution. No owner mutation.
set -euo pipefail
CI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:?new scratch parent required}"
EVIDENCE="${2:?evidence directory required}"
MAP="$CI_DIR/owner-reference-map.json"
ASSEMBLER="$CI_DIR/assemble_isolated_workspace.py"
: "${APPROVED_OWNER_REFERENCE_MAP_SHA256:?independently reviewed map hash required}"
: "${APPROVED_ASSEMBLER_SHA256:?reviewed assembler hash required}"
test ! -e "$WORK"
test ! -L "$WORK"
mkdir -p "$WORK" "$EVIDENCE/logs" "$EVIDENCE/provenance"
WORK="$(cd "$WORK" && pwd)"
EVIDENCE="$(cd "$EVIDENCE" && pwd)"
SOURCES="$WORK/pristine"
W="$WORK/assembled"
R="$WORK/results"
mkdir -p "$R"
MAP_ARGS=(--owner-reference-map "$MAP" --owner-reference-map-sha256 "$APPROVED_OWNER_REFERENCE_MAP_SHA256")
INPUT_ARGS=(--map "$MAP" --approved-sha256 "$APPROVED_OWNER_REFERENCE_MAP_SHA256")
PHASE=approval
finish() {
  local code=$?
  trap - EXIT
  python3 -B "$CI_DIR/collect_provenance.py" "$W" "$R" "$EVIDENCE/provenance" "$PHASE" "$code" || true
  exit "$code"
}
trap finish EXIT
log_run() {
  local name="$1"
  shift
  "$@" 2>&1 | tee "$EVIDENCE/logs/$name.log"
}
offline() {
  # Compiler/dependency preparation occurs separately. Actual test processes and
  # descendants cannot contact Apple, local devices, VPNs or any network endpoint.
  /usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)' "$@"
}
export -f offline
verify_inputs() {
  python3 -B "$ASSEMBLER" verify-inputs --workspace "$W" "${MAP_ARGS[@]}"
}
verify_resolution() {
  local scope="$1" state="$2" lock="$3"
  python3 -B "$ASSEMBLER" verify-resolution --workspace "$W" --scope "$scope" \
    --state "$state" --lock "$lock" "${MAP_ARGS[@]}"
}
check_tests() {
  python3 -B "$CI_DIR/verify_test_results.py" "$1" "$EVIDENCE/logs/$1.log" "$EVIDENCE/provenance/$1-tests.json"
}

python3 -B "$CI_DIR/validate_inputs.py" approve "${INPUT_ARGS[@]}" \
  --assembler "$ASSEMBLER" --assembler-sha256 "$APPROVED_ASSEMBLER_SHA256"
cp "$MAP" "$EVIDENCE/provenance/owner-reference-map.json"
PHASE=toolchain
test "$(uname -s)" = Darwin
test "$(uname -m)" = arm64
for tool in swift swiftc xcrun rustc cargo rustup cmake c++ python3 ruby brew; do command -v "$tool"; done
test -x /usr/bin/sandbox-exec
python3 -B "$CI_DIR/verify_toolchain.py" "$EVIDENCE/provenance/reviewed-toolchain.json"
xcrun --sdk iphoneos --show-sdk-path
# Future CI setup only: exact commands from the frozen integration workflow.
# No tool installer was executed while preparing this local candidate.
if ! command -v bindgen >/dev/null 2>&1 || [ "$(bindgen --version)" != 'bindgen 0.72.1' ]; then
  log_run setup-bindgen cargo install --locked --force bindgen-cli --version 0.72.1
fi
log_run setup-rust-target rustup target add aarch64-apple-ios
test "$(bindgen --version)" = 'bindgen 0.72.1'
# Homebrew's macOS library is a host prerequisite only. Never export its include
# or library paths into iOS compilation, which uses pinned XCFrameworks/AWS-LC.
if ! brew list --versions openssl@3 >/dev/null 2>&1; then
  log_run setup-host-openssl env HOMEBREW_NO_AUTO_UPDATE=1 brew install openssl@3
fi
NATIVE_OPENSSL_PREFIX="$(brew --prefix openssl@3)"
test -s "$NATIVE_OPENSSL_PREFIX/include/openssl/x509.h"
test -e "$NATIVE_OPENSSL_PREFIX/lib/libcrypto.dylib"
test -x "$NATIVE_OPENSSL_PREFIX/bin/openssl"
{
  xcodebuild -version
  xcrun --sdk iphoneos --show-sdk-version
  xcrun clang --version
  swift --version
  rustc --version --verbose
  cargo --version --verbose
  rustup show active-toolchain
  rustup target list --installed
  bindgen --version
  cmake --version
  python3 --version
  ruby --version
  brew --version
  brew list --versions openssl@3
  printf 'native_host_openssl_prefix=%s\n' "$NATIVE_OPENSSL_PREFIX"
  "$NATIVE_OPENSSL_PREFIX/bin/openssl" version
  printf 'image_os=%s\nimage_version=%s\n' "${ImageOS:-unknown}" "${ImageVersion:-unknown}"
  sw_vers
  uname -a
} > "$EVIDENCE/provenance/tool-versions.txt" 2>&1

PHASE=offline-network-preflight
log_run network-sandbox-preflight python3 -B "$CI_DIR/verify_network_sandbox.py" "$EVIDENCE/provenance/network-sandbox-proof.json"

PHASE=acquire-exact-owners
log_run owner-fetch python3 -B "$CI_DIR/validate_inputs.py" fetch "${INPUT_ARGS[@]}" \
  --root "$SOURCES" --report "$EVIDENCE/provenance/remote-owner-proof.json"
PHASE=pristine-native-suites
log_run pristine-gate python3 -B "$CI_DIR/run_pristine_gate.py" \
  --source-root "$SOURCES" --evidence "$EVIDENCE" "${INPUT_ARGS[@]}"
PHASE=assemble
log_run assembly python3 -B "$ASSEMBLER" assemble --source-root "$SOURCES" --out "$W" "${MAP_ARGS[@]}"
verify_inputs
S="$W/SideStore/Dependencies/SideSign"
M="$W/SideStore/Dependencies/minimuxer"
export CARGO_TARGET_DIR="$R/cargo-target"

PHASE=jktcp-offline-unit-tests
log_run jktcp-fetch cargo fetch --locked --manifest-path "$W/jktcp/Cargo.toml"
log_run jktcp-build cargo test --frozen --manifest-path "$W/jktcp/Cargo.toml" --lib --no-run --verbose
for group in adapter packets; do
  log_run "jktcp-$group" offline cargo test --frozen \
    --manifest-path "$W/jktcp/Cargo.toml" --lib "$group::tests::" -- --test-threads=1
  check_tests "jktcp-$group"
done

PHASE=idevice-ffi-and-local-xcframework
log_run idevice-fetch cargo fetch --locked --manifest-path "$W/idevice/ffi/Cargo.toml"
cargo metadata --frozen --format-version 1 --manifest-path "$W/idevice/ffi/Cargo.toml" \
  > "$EVIDENCE/provenance/idevice-cargo-metadata.json"
log_run idevice-check cargo check --frozen --manifest-path "$W/idevice/ffi/Cargo.toml" --features obfuscate --verbose
log_run idevice-build env BINDGEN_EXTRA_CLANG_ARGS="--sysroot=$(xcrun --sdk iphoneos --show-sdk-path)" \
  IPHONEOS_DEPLOYMENT_TARGET=15.0 cargo build --frozen --release --target aarch64-apple-ios \
  --features obfuscate --manifest-path "$W/idevice/ffi/Cargo.toml" --verbose
LIB="$CARGO_TARGET_DIR/aarch64-apple-ios/release/libidevice_ffi.a"
test -s "$LIB"
for symbol in tunnel_create_usb tunnel_heartbeat_is_active idevice_set_transport_log_callback; do
  grep -Fq "$symbol" "$W/idevice/ffi/idevice.h"
done
cp "$W/idevice/ffi/idevice.h" "$W/idevice/swift/include/idevice.h"
log_run create-xcframework xcodebuild -create-xcframework -library "$LIB" \
  -headers "$W/idevice/swift/include" -output "$W/idevice/swift/IDevice.xcframework"
mkdir -p "$M/DeviceGateway/LocalBinary"
cp -R "$W/idevice/swift/IDevice.xcframework" "$M/DeviceGateway/LocalBinary/"
diff -qr "$W/idevice/swift/IDevice.xcframework" "$M/DeviceGateway/LocalBinary/IDevice.xcframework"
cmp "$W/idevice/ffi/idevice.h" "$W/idevice/swift/include/idevice.h"
log_run idevice-symbol-reader python3 -B "$CI_DIR/verify_archive_symbols.py" \
  "$LIB" "$EVIDENCE/provenance"
verify_inputs

PHASE=anisette-offline-tests
log_run anisette-build swift build --package-path "$W/AnisetteKit" --scratch-path "$R/anisette" --build-tests -v
log_run anisette offline swift test --package-path "$W/AnisetteKit" --scratch-path "$R/anisette" \
  --skip-build --disable-sandbox --disable-automatic-resolution \
  --filter 'anisetteRequestHeadersCustomization|anisetteDataResponseStructure|anisetteHeadersDTORoundtrip'
check_tests anisette
verify_inputs

python3 -B "$CI_DIR/capture_binary_artifacts.py" "$R/anisette/workspace-state.json" "$W" "$R" \
  "$EVIDENCE/provenance/anisette-binary-artifacts.json"

PHASE=sidesign-resolution-and-offline-tests
log_run sidesign-resolve swift package --package-path "$S" --scratch-path "$R/sidesign" resolve
verify_resolution sidesign "$R/sidesign/workspace-state.json" "$S/Package.resolved"
python3 -B "$CI_DIR/capture_binary_artifacts.py" "$R/sidesign/workspace-state.json" "$W" "$R" \
  "$EVIDENCE/provenance/sidesign-binary-artifacts.json"
log_run sidesign-build swift build --package-path "$S" --scratch-path "$R/sidesign" \
  --disable-automatic-resolution --build-tests -v
log_run sidesign offline swift test --package-path "$S" --scratch-path "$R/sidesign" \
  --skip-build --disable-sandbox --disable-automatic-resolution \
  --filter 'deviceInitializationAndFiltering|certificateRequestCSRGeneration|developerPortalSingleton|archiveStoreRoundtrip|archiveDeflateRoundtrip'
check_tests sidesign
verify_resolution sidesign "$R/sidesign/workspace-state.json" "$S/Package.resolved"

PHASE=sidestore-unsigned-build
APP_LOCK="$W/SideStore/AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
log_run sidestore-resolve xcodebuild -resolvePackageDependencies -disablePackageRepositoryCache \
  -project "$W/SideStore/AltStore.xcodeproj" -scheme SideStore -derivedDataPath "$R/sidestore-derived"
verify_resolution sidestore "$R/sidestore-derived/SourcePackages/workspace-state.json" "$APP_LOCK"
python3 -B "$CI_DIR/capture_binary_artifacts.py" "$R/sidestore-derived/SourcePackages/workspace-state.json" "$W" "$R" \
  "$EVIDENCE/provenance/sidestore-binary-artifacts.json"
log_run sidestore-build xcodebuild -project "$W/SideStore/AltStore.xcodeproj" -scheme SideStore \
  -sdk iphoneos -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath "$R/sidestore-derived" -onlyUsePackageVersionsFromResolvedFile -disableAutomaticPackageResolution \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY= DEVELOPMENT_TEAM= build
verify_resolution sidestore "$R/sidestore-derived/SourcePackages/workspace-state.json" "$APP_LOCK"

PHASE=livecontainer-unsigned-build
# Keep frozen submodule commits; use the same litehook mirror as the baseline.
log_run livecontainer-submodules git -C "$W/LiveContainer" \
  -c submodule.litehook.url=https://github.com/LiveContainerMirror/litehook.git \
  submodule update --init --recursive -- OpenSSL litehook
test "$(git -C "$W/LiveContainer/OpenSSL" rev-parse HEAD)" = 623c84da314e85363236507ca38a4bde65df21c3
test "$(git -C "$W/LiveContainer/litehook" rev-parse HEAD)" = 8025e0c8ebdf5cdd1d2a4f45025813234bf9dc55
git -C "$W/LiveContainer" submodule status --recursive > "$EVIDENCE/provenance/livecontainer-submodules.txt"
python3 -B "$CI_DIR/validate_inputs.py" verify-submodules "${INPUT_ARGS[@]}" \
  --root "$W/LiveContainer" --report "$EVIDENCE/provenance/livecontainer-submodules-before.json"
log_run livecontainer-build xcodebuild -project "$W/LiveContainer/LiveContainer.xcodeproj" -scheme LiveContainer \
  -sdk iphoneos -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath "$R/livecontainer-derived" \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY= DEVELOPMENT_TEAM= build

PHASE=final-provenance
verify_inputs
python3 -B "$CI_DIR/validate_inputs.py" verify-submodules "${INPUT_ARGS[@]}" \
  --root "$W/LiveContainer" --report "$EVIDENCE/provenance/livecontainer-submodules-after.json"
diff -qr "$W/idevice/swift/IDevice.xcframework" "$M/DeviceGateway/LocalBinary/IDevice.xcframework"
python3 -B "$CI_DIR/validate_inputs.py" verify-pristine "${INPUT_ARGS[@]}" \
  --root "$SOURCES" --report "$EVIDENCE/provenance/pristine-after-build.json"
python3 -B "$CI_DIR/collect_provenance.py" "$W" "$R" "$EVIDENCE/provenance" complete 0 --require-compile-inputs
PHASE=complete
