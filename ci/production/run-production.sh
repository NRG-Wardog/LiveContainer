#!/usr/bin/env bash
# Run only the published source-owned graph. The test assembler is never invoked.
set -euo pipefail
CI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
NATIVE="$CI_DIR/../native"
PHASE="${1:?sidesign or sidestore}"
WORK="${2:?new work directory}"
EVIDENCE="${3:?evidence directory}"
: "${APPROVED_PRODUCTION_INPUTS_SHA256:?independent phase approval required}"
test ! -e "$WORK"
test ! -L "$WORK"
mkdir -p "$WORK" "$EVIDENCE/logs" "$EVIDENCE/provenance"
WORK="$(cd "$WORK" && pwd -P)"
EVIDENCE="$(cd "$EVIDENCE" && pwd -P)"
ROOT="$WORK/sources"
R="$WORK/results"
mkdir -p "$R"
SOURCE_BASIS="${PRODUCTION_SOURCE_BASIS:-parity}"
case "$SOURCE_BASIS" in
  parity) INPUT_FILE="$CI_DIR/inputs-$PHASE.json" ;;
  diagnostic) INPUT_FILE="$CI_DIR/inputs-adi-$PHASE.json" ;;
  *) echo 'Unreviewed production source basis' >&2; exit 1 ;;
esac
INPUT_ARGS=(--phase "$PHASE" --inputs "$INPUT_FILE" --approved-sha256 "$APPROVED_PRODUCTION_INPUTS_SHA256")
STAGE=inputs
LOCK=
STATE=
finish() {
  local code=$?
  trap - EXIT
  if [ -n "$STATE" ] && [ -f "$STATE" ]; then cp "$STATE" "$EVIDENCE/provenance/workspace-state.observed-final.json"; fi
  if [ -n "$LOCK" ] && [ -f "$LOCK" ]; then cp "$LOCK" "$EVIDENCE/provenance/Package.resolved.observed-final"; fi
  python3 -B - "$EVIDENCE/provenance/production-phase-status.json" "$PHASE" "$STAGE" "$code" <<'PY'
import json,sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'phase':sys.argv[2],'last_stage':sys.argv[3],
 'exit_code':int(sys.argv[4]),'status':'CAPTURED_FOR_REVIEW' if sys.argv[4]=='0' else 'FAILED_OR_INCOMPLETE',
 'production_ready':False,'metadata_commit_and_recheck_required':True,
 'ios_compilation':'NOT_RUN_PHASE_1' if sys.argv[2]=='sidesign' else 'REQUIRES_BUILD_LOG_PROOF'},indent=2)+'\n')
PY
  exit "$code"
}
trap finish EXIT
log_run() {
  local name="$1" code=0
  shift
  printf '%q ' "$@" > "$EVIDENCE/logs/$name.command.txt"
  printf '\n' >> "$EVIDENCE/logs/$name.command.txt"
  "$@" 2>&1 | tee "$EVIDENCE/logs/$name.log" || code=$?
  printf '%s\n' "$code" > "$EVIDENCE/logs/$name.exit-code.txt"
  return "$code"
}
offline() { /usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)' "$@"; }
export -f offline
prove() { python3 -B "$CI_DIR/prove_graph.py" "$1" "${INPUT_ARGS[@]}" --root "$ROOT" "${@:2}"; }
prove inputs
cp "$INPUT_FILE" "$EVIDENCE/provenance/reviewed-production-inputs.json"
STAGE=toolchain
python3 -B "$NATIVE/verify_toolchain.py" "$EVIDENCE/provenance/reviewed-toolchain.json"
{ xcodebuild -version; swift --version; rustc --version --verbose; cargo --version; } \
  > "$EVIDENCE/provenance/tool-versions.txt" 2>&1
STAGE=offline-network-preflight
log_run network-sandbox-preflight python3 -B "$NATIVE/verify_network_sandbox.py" "$EVIDENCE/provenance/network-sandbox-proof.json"
STAGE=fetch
log_run production-fetch prove fetch --report "$EVIDENCE/provenance/source-fetch.json"

if [ "$PHASE" = sidesign ]; then
  S="$ROOT/SideSign"
  LOCK="$S/Package.resolved"
  STATE="$R/sidesign/workspace-state.json"
  STAGE=strict-clean-proof
  if [ "$SOURCE_BASIS" = diagnostic ]; then
    log_run sidesign-pre-resolution-proof prove owner-proof --report "$EVIDENCE/provenance/diagnostic-owner-proof.json"
  else
    log_run sidesign-pre-resolution-proof python3 -B "$S/.ci/production-dependencies.py"
  fi
  prove sources --report "$EVIDENCE/provenance/source-proof-before.json"
  cp "$LOCK" "$EVIDENCE/provenance/Package.resolved.before"
  STAGE=real-remote-resolution
  log_run sidesign-production-resolve swift package --package-path "$S" --scratch-path "$R/sidesign" resolve
  cp "$LOCK" "$EVIDENCE/provenance/Package.resolved.after"
  prove snapshot --report "$EVIDENCE/provenance/files-after-resolution.json"
  prove sources --after-resolution --report "$EVIDENCE/provenance/source-proof-after-resolution.json"
  prove resolution --state "$STATE" --report "$EVIDENCE/provenance/resolution.json"
  log_run sidesign-production-frozen-resolve swift package --package-path "$S" --scratch-path "$R/sidesign" --force-resolved-versions resolve
  cmp "$LOCK" "$EVIDENCE/provenance/Package.resolved.after"
  swift package --package-path "$S" --scratch-path "$R/sidesign" --force-resolved-versions \
    show-dependencies --format json > "$EVIDENCE/provenance/resolved-graph.json"
  cmp "$LOCK" "$EVIDENCE/provenance/Package.resolved.after"
  python3 -B "$NATIVE/capture_binary_artifacts.py" "$STATE" "$ROOT" "$R" "$EVIDENCE/provenance/binary-artifacts.json"
  STAGE=selected-native-tests
  log_run sidesign-production-build swift build --package-path "$S" --scratch-path "$R/sidesign" --force-resolved-versions --build-tests -v
  log_run sidesign-production-tests offline swift test --package-path "$S" --scratch-path "$R/sidesign" --force-resolved-versions --skip-build --disable-sandbox \
    --filter 'deviceInitializationAndFiltering|certificateRequestCSRGeneration|developerPortalSingleton|archiveStoreRoundtrip|archiveDeflateRoundtrip'
  python3 -B "$NATIVE/verify_test_results.py" sidesign "$EVIDENCE/logs/sidesign-production-tests.log" "$EVIDENCE/provenance/sidesign-tests.json"
else
  test "$PHASE" = sidestore
  # Host certificate fixture prerequisite matches the current native workflow.
  if ! brew list --versions openssl@3 >/dev/null 2>&1; then
    log_run setup-host-openssl env HOMEBREW_NO_AUTO_UPDATE=1 brew install openssl@3
  fi
  NATIVE_OPENSSL_PREFIX="$(brew --prefix openssl@3)"
  test -s "$NATIVE_OPENSSL_PREFIX/include/openssl/x509.h"
  test -e "$NATIVE_OPENSSL_PREFIX/lib/libcrypto.dylib"
  { brew list --versions openssl@3; printf 'host_openssl_prefix=%s\n' "$NATIVE_OPENSSL_PREFIX"; "$NATIVE_OPENSSL_PREFIX/bin/openssl" version; } \
    > "$EVIDENCE/provenance/host-openssl.txt"
  SS="$ROOT/SideStore"
  S="$SS/Dependencies/SideSign"
  M="$SS/Dependencies/minimuxer"
  LOCK="$SS/AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
  STATE="$R/sidestore-packages/workspace-state.json"
  STAGE=strict-clean-proof
  # The default proof must already contain final committed child pins.
  log_run sidestore-pre-initialization-proof python3 -B "$SS/.ci/production-dependencies.py"
  log_run production-child-fetch git -C "$SS" submodule update --init --recursive
  prove sources --report "$EVIDENCE/provenance/source-proof-before.json"
  log_run sidestore-pre-resolution-proof python3 -B "$SS/.ci/production-dependencies.py"
  log_run final-sidesign-proof python3 -B "$S/.ci/production-dependencies.py"
  log_run sidestore-native offline python3 -B "$NATIVE/run_fork_suite.py" SideStore "$SS" "$EVIDENCE/provenance/sidestore-native-tests.json"
  prove sources --report "$EVIDENCE/provenance/source-proof-after-native-tests.json"
  # Reuse the unchanged frozen contract gate and complete owner manifest set.
  python3 -B - "$CI_DIR/contracts" <<'PY'
import hashlib,sys
from pathlib import Path
p=Path(sys.argv[1])
if hashlib.sha256((p/'validate_contracts.py').read_bytes()).hexdigest()!='0d5a5aa61dd37f566359312611826ae5dbbae00176c50b1e4c5e2143530bf520':raise SystemExit('Contract gate changed')
PY
  log_run production-contracts python3 -B "$CI_DIR/contracts/validate_contracts.py" \
    --registry "$CI_DIR/contracts/compatibility-registry.json" \
    --registry-sha256 8e7eba95b8bc69037ffed8931478cefd46984b458f767c2a067547e3cd60b467 \
    --owner "LiveContainer=$ROOT/LiveContainer" --owner "SideStore=$SS" --owner "AnisetteKit=$ROOT/AnisetteKit" \
    --owner "SideSign=$S" --owner "minimuxer=$M" --owner "idevice=$ROOT/idevice" --owner "jktcp=$ROOT/jktcp"
  STAGE=existing-ffi-product
  log_run rust-ios-target rustup target add aarch64-apple-ios
  if ! command -v bindgen >/dev/null 2>&1 || [ "$(bindgen --version)" != 'bindgen 0.72.1' ]; then
    log_run setup-bindgen cargo install --locked --force bindgen-cli --version 0.72.1
  fi
  export CARGO_TARGET_DIR="$R/cargo-target"
  log_run idevice-fetch cargo fetch --locked --manifest-path "$ROOT/idevice/ffi/Cargo.toml"
  cargo metadata --frozen --format-version 1 --manifest-path "$ROOT/idevice/ffi/Cargo.toml" > "$EVIDENCE/provenance/idevice-cargo-metadata.json"
  log_run idevice-build env BINDGEN_EXTRA_CLANG_ARGS="--sysroot=$(xcrun --sdk iphoneos --show-sdk-path)" \
    IPHONEOS_DEPLOYMENT_TARGET=15.0 cargo build --frozen --release --target aarch64-apple-ios --features obfuscate \
    --manifest-path "$ROOT/idevice/ffi/Cargo.toml" --verbose
  LIB="$CARGO_TARGET_DIR/aarch64-apple-ios/release/libidevice_ffi.a"
  cp "$ROOT/idevice/ffi/idevice.h" "$ROOT/idevice/swift/include/idevice.h"
  log_run create-xcframework xcodebuild -create-xcframework -library "$LIB" -headers "$ROOT/idevice/swift/include" \
    -output "$ROOT/idevice/swift/IDevice.xcframework"
  mkdir -p "$M/DeviceGateway/LocalBinary"
  cp -R "$ROOT/idevice/swift/IDevice.xcframework" "$M/DeviceGateway/LocalBinary/"
  diff -qr "$ROOT/idevice/swift/IDevice.xcframework" "$M/DeviceGateway/LocalBinary/IDevice.xcframework"
  log_run idevice-symbols python3 -B "$NATIVE/verify_archive_symbols.py" "$LIB" "$EVIDENCE/provenance"
  prove build-products --archive "$LIB" --report "$EVIDENCE/provenance/local-framework-before-build.json"
  prove sources --built --report "$EVIDENCE/provenance/source-proof-after-ffi.json"
  STAGE=real-xcode-resolution
  cp "$LOCK" "$EVIDENCE/provenance/Package.resolved.before"
  XCODE_ARGS=(-project "$SS/AltStore.xcodeproj" -scheme SideStore -clonedSourcePackagesDirPath "$R/sidestore-packages" -derivedDataPath "$R/sidestore-derived" -disablePackageRepositoryCache)
  log_run sidestore-production-resolve xcodebuild -resolvePackageDependencies "${XCODE_ARGS[@]}"
  cp "$LOCK" "$EVIDENCE/provenance/Package.resolved.after"
  prove snapshot --report "$EVIDENCE/provenance/files-after-resolution.json"
  prove sources --built --after-resolution --report "$EVIDENCE/provenance/source-proof-after-resolution.json"
  prove resolution --state "$STATE" --report "$EVIDENCE/provenance/resolution.json"
  log_run sidestore-production-frozen-resolve xcodebuild -resolvePackageDependencies "${XCODE_ARGS[@]}" -onlyUsePackageVersionsFromResolvedFile
  cmp "$LOCK" "$EVIDENCE/provenance/Package.resolved.after"
  python3 -B "$NATIVE/capture_binary_artifacts.py" "$STATE" "$ROOT" "$R" "$EVIDENCE/provenance/binary-artifacts.json"
  STAGE=unsigned-production-build
  log_run sidestore-production-build xcodebuild "${XCODE_ARGS[@]}" -sdk iphoneos -configuration Release \
    -destination 'generic/platform=iOS' -onlyUsePackageVersionsFromResolvedFile -disableAutomaticPackageResolution \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY= DEVELOPMENT_TEAM= build
  log_run livecontainer-submodules git -C "$ROOT/LiveContainer" -c submodule.litehook.url=https://github.com/LiveContainerMirror/litehook.git \
    submodule update --init --recursive -- OpenSSL litehook
  python3 -B - "$NATIVE" "$ROOT/LiveContainer" "$EVIDENCE/provenance/livecontainer-submodules-before.json" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from validate_inputs import verify_submodules
verify_submodules(Path(sys.argv[2]),Path(sys.argv[3]))
PY
  log_run livecontainer-production-build xcodebuild -project "$ROOT/LiveContainer/LiveContainer.xcodeproj" -scheme LiveContainer \
    -sdk iphoneos -configuration Release -destination 'generic/platform=iOS' -derivedDataPath "$R/livecontainer-derived" \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY= DEVELOPMENT_TEAM= build
fi

STAGE=final-source-and-resolver-proof
if [ "$PHASE" = sidestore ]; then
  python3 -B - "$NATIVE" "$ROOT/LiveContainer" "$EVIDENCE/provenance/livecontainer-submodules-after.json" <<'VERIFY_SUBMODULES'
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from validate_inputs import verify_submodules
verify_submodules(Path(sys.argv[2]),Path(sys.argv[3]))
VERIFY_SUBMODULES
  diff -qr "$ROOT/idevice/swift/IDevice.xcframework" "$M/DeviceGateway/LocalBinary/IDevice.xcframework"
  prove build-products --archive "$LIB" --report "$EVIDENCE/provenance/local-framework-after-build.json"
  prove generated-sources --results "$R" --report "$EVIDENCE/provenance/generated-sources-proof.json"
fi
cmp "$LOCK" "$EVIDENCE/provenance/Package.resolved.after"
prove snapshot --report "$EVIDENCE/provenance/files-after-build.json"
prove sources --built --after-resolution --report "$EVIDENCE/provenance/source-proof-after-build.json"
prove resolution --state "$STATE" --report "$EVIDENCE/provenance/resolution-after-build.json"
prove compiler-inputs --state "$STATE" --results "$R" --report "$EVIDENCE/provenance/compiler-input-proof.json"
cp "$STATE" "$EVIDENCE/provenance/workspace-state.json"
STAGE=captured-for-review
