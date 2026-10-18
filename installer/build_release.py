"""Build the portable F3 voice-manager folder from verified local artifacts."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
GAME = PROJECT.parent
INSTALLER = PROJECT / "installer"
RELEASE = PROJECT / "release" / "ru-voice-f3-0.1.0"
PAYLOAD = RELEASE / "payload"
MOD = PROJECT / "local" / "ru_voice_separate_520"
NATIVE = PROJECT / "experiments" / "separate_russian" / "native"
EML = PROJECT / "local" / "eml-v0.2.0"
PUBLISH = INSTALLER / "publish"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if RELEASE.exists():
        raise RuntimeError(f"Release directory already exists: {RELEASE}")
    expected = json.loads((MOD / "manifest.json").read_text(encoding="utf-8"))
    for entry in expected["entries"]:
        audio = MOD / "audio" / entry["audio"]
        if sha(audio) != entry["sha256"]:
            raise RuntimeError(f"Audio source changed: {audio.name}")
    if len(expected["entries"]) != 520:
        raise RuntimeError("Expected exactly 520 audio entries")
    if sha(GAME / "enshrouded.exe") != "82e5020a8736348cd0374f004b2f5e5ef456b5bd27aa5420df34c7dd241cfeeb":
        raise RuntimeError("Unrecognized game build")
    if sha(NATIVE / "shroudtopia.dll") != sha(GAME / "shroudtopia.dll"):
        raise RuntimeError("Compiled runtime differs from the tested installation")
    if not (PUBLISH / "VoiceInstaller.exe").is_file():
        raise FileNotFoundError(PUBLISH / "VoiceInstaller.exe")
    PAYLOAD.mkdir(parents=True)
    shutil.copytree(MOD, PAYLOAD / "mod")
    for name, source in {
        "native/dbghelp.dll": EML / "dbghelp.dll",
        "native/winmm.dll": NATIVE / "winmm.dll",
        "native/shroudtopia.dll": NATIVE / "shroudtopia.dll",
        "tools/emm.exe": EML / "emm.exe",
    }.items():
        target = PAYLOAD / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    files = {file.relative_to(PAYLOAD).as_posix(): sha(file)
             for file in sorted(PAYLOAD.rglob("*")) if file.is_file()}
    (PAYLOAD / "manifest.json").write_text(
        json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for file in PUBLISH.iterdir():
        if file.is_file() and file.suffix.lower() not in {".pdb"}:
            shutil.copy2(file, RELEASE / file.name)
    shutil.copy2(INSTALLER / "README.md", RELEASE / "README.md")
    shutil.copy2(INSTALLER / "THIRD_PARTY.md", RELEASE / "THIRD_PARTY.md")
    shutil.copytree(INSTALLER / "licenses", RELEASE / "licenses")
    source = RELEASE / "installer-source"
    source.mkdir()
    for name in ("Program.cs", "DarkUi.cs", "VoiceInstaller.csproj", "app.manifest",
                 "ru_voice.ico", "build_release.py"):
        shutil.copy2(INSTALLER / name, source / name)
    print(f"Release: {RELEASE}; files: {len(files)}; voice entries: 520")


if __name__ == "__main__":
    main()
