# AIHuMo desktop packages

The desktop application is built natively for each operating system. PyInstaller
packages contain native Python, Qt, OpenCV, MediaPipe, and PyArrow libraries, so
a Windows package cannot be converted into a macOS or Linux package.

```text
AI Humo EXE pipeline/
├── Windows/   Windows 10/11 x64
├── macOS/     Intel x64 and Apple Silicon arm64
└── Linux/     Linux x64
```

Published downloads and SHA-256 files are available on the
[AIHuMo releases page](https://github.com/JacksonJ01/aihumo/releases).
The platform folders contain the native build recipe and platform-specific
instructions. Large generated packages are ignored by Git and remain release
assets rather than source files.

The packages are unsigned preview builds. Windows SmartScreen and macOS
Gatekeeper can therefore show an unknown-developer warning. Production
distribution should add Authenticode signing, Apple Developer ID signing and
notarization, and a Linux package format such as AppImage or Flatpak.
