"""Create separate source and user-facing archives without touching game files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT / "installer"
RELEASE = PROJECT / "release"
BASE = RELEASE / "ru-voice-f3-0.1.0"
VERSION = "0.1.0-beta"
NEXUS = RELEASE / f"Voices-of-Embervale-RU-{VERSION}-Nexus"
SOURCE = RELEASE / f"Voices-of-Embervale-RU-{VERSION}-Source"
EML = PROJECT / "local" / "eml-source-v0.2.0"
MINHOOK = PROJECT / "local" / "re-tools" / "minhook" / "minhook-1.3.4"
NATIVE = PROJECT / "experiments" / "separate_russian" / "native"
EML_COMMIT = "16708594d686b030d909f2d835b199d879ea9ad8"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package(directory: Path) -> tuple[int, int, str]:
    archive = directory.with_name(directory.name + ".zip")
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as output:
        for path in files:
            output.write(path, f"{directory.name}/{path.relative_to(directory).as_posix()}")
    with zipfile.ZipFile(archive) as check:
        if check.testzip() is not None or len(check.namelist()) != len(files):
            raise RuntimeError(f"Invalid ZIP: {archive}")
    digest = sha(archive)
    archive.with_name(archive.name + ".sha256.txt").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8")
    return len(files), archive.stat().st_size, digest


def main() -> None:
    for path in (NEXUS, SOURCE, NEXUS.with_name(NEXUS.name + ".zip"),
                 SOURCE.with_name(SOURCE.name + ".zip")):
        if path.exists():
            raise RuntimeError(f"Output already exists: {path}")

    manifest = json.loads((BASE / "payload" / "manifest.json").read_text(encoding="utf-8"))["files"]
    if len(manifest) != 527 or any(sha(BASE / "payload" / name) != digest
                                   for name, digest in manifest.items()):
        raise RuntimeError("Payload SHA-256 verification failed")
    commit = subprocess.check_output(["git", "-C", str(EML), "rev-parse", "HEAD"], text=True).strip()
    if commit != EML_COMMIT:
        raise RuntimeError("Unexpected EML source commit")

    NEXUS.mkdir()
    shutil.copytree(BASE / "payload", NEXUS / "payload")
    for path in (INSTALLER / "publish").iterdir():
        if path.is_file() and path.suffix.lower() != ".pdb":
            shutil.copy2(path, NEXUS / path.name)
    shutil.copy2(INSTALLER / "README_NEXUS.md", NEXUS / "README.md")
    shutil.copy2(INSTALLER / "THIRD_PARTY.md", NEXUS / "THIRD_PARTY.md")
    shutil.copytree(INSTALLER / "licenses", NEXUS / "licenses")

    SOURCE.mkdir()
    # The source tree intentionally excludes generated binaries and all audio.
    (SOURCE / "installer").mkdir(exist_ok=True)
    for name in ("Program.cs", "DarkUi.cs", "VoiceInstaller.csproj", "app.manifest",
                 "ru_voice.ico", "build_release.py", "prepare_split_release.py"):
        shutil.copy2(INSTALLER / name, SOURCE / "installer" / name)
    (SOURCE / "runtime").mkdir()
    for name in ("voice_runtime.c", "guid_map.h"):
        shutil.copy2(NATIVE / name, SOURCE / "runtime" / name)
    shutil.copy2(INSTALLER / "RUNTIME_BUILDING.md", SOURCE / "runtime" / "BUILDING.md")
    shutil.copytree(MINHOOK / "include", SOURCE / "runtime" / "minhook" / "include")
    shutil.copytree(MINHOOK / "src", SOURCE / "runtime" / "minhook" / "src")
    for name in ("LICENSE", "LICENSE.txt", "README.md", "AUTHORS.txt"):
        if (MINHOOK / name).is_file():
            shutil.copy2(MINHOOK / name, SOURCE / "runtime" / "minhook" / name)
    shutil.copytree(EML, SOURCE / "third_party" / "EML-0.2.0",
                    ignore=shutil.ignore_patterns(".git"))
    shutil.copytree(INSTALLER / "licenses", SOURCE / "licenses")
    for name in ("THIRD_PARTY.md", "NEXUS_PAGE_RU.md", "NEXUS_PAGE_EN.md"):
        shutil.copy2(INSTALLER / name, SOURCE / name)
    shutil.copy2(INSTALLER / "README_SOURCE.md", SOURCE / "README.md")
    (SOURCE / ".gitignore").write_text(
        "bin/\nobj/\npublish/\n*.pdb\n*.dll\n*.exe\npayload/\n*.wav\n*.qoa\n*.zip\n", encoding="utf-8")

    for directory in (NEXUS, SOURCE):
        files, size, digest = package(directory)
        print(f"{directory.with_name(directory.name + '.zip')} files={files} bytes={size} sha256={digest}")


if __name__ == "__main__":
    main()
