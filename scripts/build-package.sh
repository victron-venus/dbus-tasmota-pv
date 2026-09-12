#!/bin/bash
# Build the complete SetupHelper archive without installing or starting services.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tag="${1:?Usage: build-package.sh TAG OUTPUT_DIRECTORY}"
output="${2:?Usage: build-package.sh TAG OUTPUT_DIRECTORY}"
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$ ]] || { echo "Invalid release tag" >&2; exit 1; }
[[ "$(cat "$root/version")" == "$tag" ]] || { echo "Tag and package version differ" >&2; exit 1; }
mkdir -p "$output"
output="$(cd "$output" && pwd)"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
package="$staging/dbus-tasmota-pv"
mkdir -p "$package"
cp "$root/dbus-tasmota-pv.py" "$root/setup" "$root/gitHubInfo" "$root/version" "$root/install.sh" "$root/README.md" "$root/LICENSE" "$package/"
cp -R "$root/services" "$package/"
archive="dbus-tasmota-pv-${tag}.tar.gz"
tar -czf "$output/$archive" -C "$staging" dbus-tasmota-pv
(cd "$output" && shasum -a 256 "$archive" > SHA256SUMS)
