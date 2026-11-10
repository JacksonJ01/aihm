# Windows x64

Download the current Windows ZIP from the
[AIHuMo releases page](https://github.com/JacksonJ01/aihumo/releases),
extract the complete ZIP, and run `AIHuMo Data Studio.exe`.

To rebuild on Windows, open PowerShell in this directory and run:

```powershell
.\build_portable.ps1 -Version 0.1.3
```

The wrapper calls the maintained Windows recipe in the parent directory.
Windows packages must be built on Windows x64.
