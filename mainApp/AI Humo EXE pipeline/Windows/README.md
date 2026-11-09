# Windows x64

Download `AIHuMo-Data-Studio-Windows-v0.1.1.zip` from the
[v0.1.1 release](https://github.com/JacksonJ01/aihm/releases/tag/desktop-v0.1.1),
extract the complete ZIP, and run `AIHuMo Data Studio.exe`.

To rebuild on Windows, open PowerShell in this directory and run:

```powershell
.\build_portable.ps1 -Version 0.1.1
```

The wrapper calls the maintained Windows recipe in the parent directory.
Windows packages must be built on Windows x64.
