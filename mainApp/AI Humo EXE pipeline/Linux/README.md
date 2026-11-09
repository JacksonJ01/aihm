# Linux x64

Download `AIHuMo-Data-Studio-Linux-x64-v0.1.1.tar.gz` from the
[v0.1.1 release](https://github.com/JacksonJ01/aihm/releases/tag/desktop-v0.1.1),
verify its SHA-256 sidecar, and extract it. Then run:

```bash
chmod +x "AIHuMo Data Studio/AIHuMo Data Studio"
./"AIHuMo Data Studio/AIHuMo Data Studio"
```

The preview build targets 64-bit Ubuntu/Linux systems using glibc. Some
distributions may need the standard OpenGL, XCB, and XKB runtime libraries used
by Qt and OpenCV.

## Native build

Use Python 3.11 on Linux x64. From this directory:

```bash
chmod +x build_portable.sh
./build_portable.sh 0.1.1
```

GitHub Actions builds and smoke-tests the package on Ubuntu 22.04 x64.
