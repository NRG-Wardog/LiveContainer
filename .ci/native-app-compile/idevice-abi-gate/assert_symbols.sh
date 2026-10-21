#!/usr/bin/env bash
set -euo pipefail
archive=${1:?Pass the generated or staged libidevice_ffi.a}
output=${2:?Pass a symbol-evidence output path}
xcrun nm -arch arm64 -gUj "$archive" > "$output"
for symbol in \
  _pairable_host_prepare \
  _pairable_host_accept_fd \
  _pairable_host_free \
  _rppairing_peer_device_free \
  _tunnel_create_rppairing_with_options \
  _rppairing_pair_network
do
  grep -Fqx -- "$symbol" "$output" || {
    printf 'Missing defined external symbol: %s\n' "$symbol" >&2
    exit 1
  }
done
