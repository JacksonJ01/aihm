# macOS 64-bit

AIHuMo provides separate native packages for:

- Intel Mac x64: `AIHuMo-Data-Studio-macOS-Intel-v0.1.1.zip`
- Apple Silicon arm64: `AIHuMo-Data-Studio-macOS-Apple-Silicon-v0.1.1.zip`

Download the matching file from the
[v0.1.1 release](https://github.com/JacksonJ01/aihm/releases/tag/desktop-v0.1.1),
extract it, and open `AIHuMo Data Studio.app`.

These preview packages are not yet signed or notarized. If macOS blocks the
first launch, Control-click the app, choose **Open**, and confirm once. Do not
disable Gatekeeper globally.

## Native build

Use Python 3.11 on the target Mac. From this directory:

```bash
chmod +x build_portable.sh
./build_portable.sh 0.1.1
```

The script detects `x86_64` or `arm64`, builds a native `.app`, packages it with
`ditto`, and writes a SHA-256 sidecar. Intel builds pin the last MediaPipe line
that publishes Intel wheels. Apple Silicon builds use the current native
MediaPipe wheel. GitHub Actions performs both builds on native runners.
