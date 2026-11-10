#!/usr/bin/env bash
set -euo pipefail

version="${1:-0.1.5}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Version must use MAJOR.MINOR.PATCH." >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pipeline_dir="$(cd "$script_dir/.." && pwd)"
project_root="$(cd "$pipeline_dir/.." && pwd)"
if [[ ! -f "$project_root/main.py" && -f "$project_root/mainApp/main.py" ]]; then
  project_root="$project_root/mainApp"
fi
python_bin="${PYTHON_BIN:-python3}"
architecture="$(uname -m)"
if [[ "$architecture" != "x86_64" ]]; then
  echo "This recipe currently supports Linux x86_64 only; found $architecture." >&2
  exit 2
fi

work_dir="$script_dir/build/v${version}-x64"
dist_dir="$script_dir/dist/v${version}-x64"
release_dir="$script_dir/release"
archive="$release_dir/AIHuMo-Data-Studio-Linux-x64-v${version}.tar.gz"
app_dir="$dist_dir/AIHuMo Data Studio"

if [[ -e "$app_dir" || -e "$archive" ]]; then
  echo "Build output already exists for v${version} Linux x64." >&2
  exit 2
fi
mkdir -p "$work_dir" "$dist_dir" "$release_dir"

"$python_bin" -m PyInstaller --noconfirm --clean \
  --workpath "$work_dir" --distpath "$dist_dir" \
  "$pipeline_dir/AIHuMoDataStudio.spec"

if [[ ! -d "$app_dir" ]]; then
  echo "PyInstaller did not create $app_dir" >&2
  exit 1
fi
mkdir -p "$app_dir/data/processed"
cp "$script_dir/README.md" "$app_dir/README.md"
{
  echo "Version: $version"
  echo "Platform: Linux"
  echo "Architecture: x86_64"
  if command -v git >/dev/null 2>&1; then
    git -C "$project_root" rev-parse HEAD 2>/dev/null | sed 's/^/Source commit: /' || true
  fi
} > "$app_dir/BUILD-INFO.txt"

tar -C "$dist_dir" -czf "$archive" "AIHuMo Data Studio"
checksum="$(sha256sum "$archive" | awk '{print $1}')"
printf '%s  %s\n' "$checksum" "$(basename "$archive")" > "$archive.sha256"
echo "Created $archive"
