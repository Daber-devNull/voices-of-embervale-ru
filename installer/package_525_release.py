"""Build and verify the offline 525-entry Nexus package without touching the game."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "release/ru-voice-f3-0.1.0/payload"
DLL = ROOT / "local/ru_voice_525_native/shroudtopia.dll"
PUBLISH = ROOT / "installer/publish-525"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.1.2-beta")
    parser.add_argument("--mod", type=Path, default=ROOT / "local/ru_voice_separate_525_numeric")
    args = parser.parse_args()
    mod = args.mod.resolve()
    dest = ROOT / "release" / f"Voices-of-Embervale-RU-{args.version}-Nexus"
    if dest.exists() or dest.with_name(dest.name + ".zip").exists():
        raise FileExistsError("Release output already exists")
    mod_manifest = json.loads((mod / "manifest.json").read_text(encoding="utf-8"))
    if len(mod_manifest["entries"]) != 525:
        raise ValueError("Mod must contain 525 entries")
    for entry in mod_manifest["entries"]:
        audio = mod / "audio" / entry["audio"]
        if audio.stat().st_size != entry["bytes"] or sha(audio) != entry["sha256"]:
            raise ValueError(f"Audio mismatch: {audio}")

    payload = dest / "payload"
    shutil.copytree(mod, payload / "mod")
    shutil.copytree(OLD / "native", payload / "native")
    shutil.copytree(OLD / "tools", payload / "tools")
    shutil.copy2(DLL, payload / "native/shroudtopia.dll")
    files = sorted(path for path in payload.rglob("*") if path.is_file())
    hashes = {path.relative_to(payload).as_posix(): sha(path) for path in files}
    if len(hashes) != 532:
        raise ValueError(f"Expected 532 payload files, got {len(hashes)}")
    (payload / "manifest.json").write_text(
        json.dumps({"files": hashes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for path in PUBLISH.iterdir():
        if path.is_file() and path.suffix.lower() != ".pdb":
            shutil.copy2(path, dest / path.name)
    shutil.copy2(ROOT / "installer/THIRD_PARTY.md", dest / "THIRD_PARTY.md")
    shutil.copytree(ROOT / "installer/licenses", dest / "licenses")
    release_note = ("В beta 0.1.2 числа в заголовках и тексте 134 страниц произносятся словами.\n\n"
                    if args.version.startswith("0.1.2") else "")
    (dest / "README.md").write_text(
        f"# Голоса Эмбервейла — beta {args.version}\n\n"
        "Русская озвучка всех 525 найденных страниц дневника. "
        "Распакуйте архив целиком. При закрытой игре запустите VoiceInstaller.exe, "
        "укажите папку с enshrouded.exe и нажмите «Проверить состояние», затем «Установить мод». "
        "В игре F3 включает и выключает русскую озвучку при любом выбранном языке.\n\n"
        "Если уже установлена прежняя версия, сначала откройте её установщик "
        "и нажмите «Отключить · копию сохранить». Затем запускайте новый установщик.\n\n"
        + release_note +
        "«Отключить · копию сохранить» возвращает игровые индексы и сохраняет резервную копию. "
        "«Удалить мод и копию» также удаляет резервную копию. "
        "Обе операции требуют закрыть игру. Поддерживается проверенная сборка Enshrouded 1.0 "
        "(SHA-256 enshrouded.exe: 82e5020a8736348cd0374f004b2f5e5ef456b5bd27aa5420df34c7dd241cfeeb). "
        "Установщик не имеет цифровой подписи. "
        "Исходники: https://github.com/Daber-devNull/voices-of-embervale-ru\n",
        encoding="utf-8",
    )

    archive = dest.with_name(dest.name + ".zip")
    members = sorted(path for path in dest.rglob("*") if path.is_file())
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as out:
        for path in members:
            out.write(path, f"{dest.name}/{path.relative_to(dest).as_posix()}")
    with zipfile.ZipFile(archive) as check:
        if check.testzip() is not None or len(check.namelist()) != len(members):
            raise ValueError("ZIP verification failed")
    digest = sha(archive)
    archive.with_name(archive.name + ".sha256.txt").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii"
    )
    print(json.dumps({"entries": 525, "payload_files": len(hashes), "archive": str(archive),
                      "archive_bytes": archive.stat().st_size, "sha256": digest}))


if __name__ == "__main__":
    main()
