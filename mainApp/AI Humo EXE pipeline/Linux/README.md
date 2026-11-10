# Linux x64

Download the current Linux x64 tarball from the
[AIHuMo releases page](https://github.com/JacksonJ01/aihumo/releases),
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
./build_portable.sh 0.1.4
```

GitHub Actions builds and smoke-tests the package on Ubuntu 22.04 x64.
