# Russian voice runtime source

`voice_runtime.c` and `guid_map.h` implement the F3 toggle, voice redirection and status badge for the pinned Enshrouded build. `minhook/` contains the unmodified MinHook 1.3.4 source used by this DLL.

With Zig installed, a compatible x64 Windows DLL can be built from this directory:

```powershell
zig cc -target x86_64-windows-gnu -O2 -shared -Iminhook/include -Iminhook/src voice_runtime.c minhook/src/buffer.c minhook/src/hook.c minhook/src/trampoline.c minhook/src/hde/hde64.c -o shroudtopia.dll -lbcrypt -luser32 -lgdi32
```

The source is version-pinned and checks the game executable's SHA-256 before installing hooks. A different game build needs an updated mapping and addresses; do not bypass the version check.
