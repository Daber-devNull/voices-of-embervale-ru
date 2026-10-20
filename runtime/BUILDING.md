# Russian voice runtime source

`voice_runtime.c` and `guid_map.h` implement the F3 toggle, voice redirection and status badge. `minhook/` contains the unmodified MinHook 1.3.4 source used by this DLL.

With Visual Studio 2022 C++ Build Tools installed, build the x64 DLL from this directory:

```powershell
cmd /c '"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64 && cl /nologo /utf-8 /O2 /LD /Iminhook\include /Iminhook\src voice_runtime.c minhook\src\buffer.c minhook\src\hook.c minhook\src\trampoline.c minhook\src\hde\hde64.c /link /OUT:shroudtopia.dll user32.lib gdi32.lib'
```

The runtime locates three audio functions by unique code signatures and refuses to install hooks when they are missing or ambiguous. The installer also checks the minimum game build and validates the signatures before modifying files. Runtime diagnostics go to `ru_voice_runtime.log` next to `enshrouded.exe`.
