#!/usr/bin/env bash
set -euo pipefail

version="${1:-0.1.1}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Version must use MAJOR.MINOR.PATCH." >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pipeline_dir="$(cd "$script_dir/.." && pwd)"
project_root="$(cd "$pipeline_dir/.." && pwd)"
if [[ ! -f "$project_root/aihumo_data_studio.py" && -f "$project_root/mainApp/aihumo_data_studio.py" ]]; then
  project_root="$project_root/mainApp"
fi
python_bin="${PYTHON_BIN:-python3}"
architecture="$(uname -m)"
case "$architecture" in
  x86_64) label="Intel" ;;
  arm64) label="Apple-Silicon" ;;
  *) echo "Unsupported macOS architecture: $architecture" >&2; exit 2 ;;
esac

work_dir="$script_dir/build/v${version}-${architecture}"
dist_dir="$script_dir/dist/v${version}-${architecture}"
release_dir="$script_dir/release"
archive="$release_dir/AIHuMo-Data-Studio-macOS-${label}-v${version}.zip"
app_bundle="$dist_dir/AIHuMo Data Studio.app"

if [[ -e "$app_bundle" || -e "$archive" ]]; then
  echo "Build output already exists for v${version} ${architecture}." >&2
  exit 2
fi
mkdir -p "$work_dir" "$dist_dir" "$release_dir"

"$python_bin" -m PyInstaller --noconfirm --clean \
  --workpath "$work_dir" --distpath "$dist_dir" \
  "$pipeline_dir/AIHuMoDataStudio.spec"

if [[ ! -d "$app_bundle" ]]; then
  echo "PyInstaller did not create $app_bundle" >&2
  exit 1
fi

stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/aihumo-macos.XXXXXX")"
trap 'rm -rf "$stage_dir"' EXIT
cp -R "$app_bundle" "$stage_dir/"
cp "$script_dir/README.md" "$stage_dir/README.md"
{
  echo "Version: $version"
  echo "Platform: macOS"
  echo "Architecture: $architecture"
  if command -v git >/dev/null 2>&1; then
    git -C "$project_root" rev-parse HEAD 2>/dev/null | sed 's/^/Source commit: /' || true
  fi
} > "$stage_dir/BUILD-INFO.txt"

(cd "$stage_dir" && ditto -c -k --sequesterRsrc . "$archive")
checksum="$(shasum -a 256 "$archive" | awk '{print $1}')"
printf '%s  %s\n' "$checksum" "$(basename "$archive")" > "$archive.sha256"
echo "Created $archive"
