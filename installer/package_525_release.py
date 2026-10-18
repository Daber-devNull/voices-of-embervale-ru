"""Build and verify the offline 525-entry Nexus package without touching the game."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "release/ru-voice-f3-0.1.0/payload"
MOD = ROOT / "local/ru_voice_separate_525"
DLL = ROOT / "local/ru_voice_525_native/shroudtopia.dll"
PUBLISH = ROOT / "installer/publish-525"
DEST = ROOT / "release/Voices-of-Embervale-RU-0.1.1-beta-Nexus"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if DEST.exists() or DEST.with_name(DEST.name + ".zip").exists():
        raise FileExistsError("Release output already exists")
    mod_manifest = json.loads((MOD / "manifest.json").read_text(encoding="utf-8"))
    if len(mod_manifest["entries"]) != 525:
        raise ValueError("Mod must contain 525 entries")
    for entry in mod_manifest["entries"]:
        audio = MOD / "audio" / entry["audio"]
        if audio.stat().st_size != entry["bytes"] or sha(audio) != entry["sha256"]:
            raise ValueError(f"Audio mismatch: {audio}")

    payload = DEST / "payload"
    shutil.copytree(MOD, payload / "mod")
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
            shutil.copy2(path, DEST / path.name)
    shutil.copy2(ROOT / "installer/THIRD_PARTY.md", DEST / "THIRD_PARTY.md")
    shutil.copytree(ROOT / "installer/licenses", DEST / "licenses")
    (DEST / "README.md").write_text(
        "# Голоса Эмбервейла — beta 0.1.1\n\n"
        "Русская озвучка всех 525 найденных страниц дневника. "
        "Распакуйте архив целиком. При закрытой игре запустите VoiceInstaller.exe, "
        "укажите папку с enshrouded.exe и нажмите «Проверить состояние», затем «Установить мод». "
        "В игре F3 включает и выключает русскую озвучку при любом выбранном языке.\n\n"
        "Если установлена beta 0.1.0 на 520 записей, сначала откройте прежний установщик "
        "и нажмите «Отключить · копию сохранить». Затем запускайте новый установщик.\n\n"
        "«Отключить · копию сохранить» возвращает игровые индексы и сохраняет резервную копию. "
        "«Удалить мод и копию» также удаляет резервную копию. "
        "Обе операции требуют закрыть игру. Поддерживается проверенная сборка Enshrouded 1.0 "
        "(SHA-256 enshrouded.exe: 82e5020a8736348cd0374f004b2f5e5ef456b5bd27aa5420df34c7dd241cfeeb). "
        "Установщик не имеет цифровой подписи. "
        "Исходники: https://github.com/Daber-devNull/voices-of-embervale-ru\n",
        encoding="utf-8",
    )

    archive = DEST.with_name(DEST.name + ".zip")
    members = sorted(path for path in DEST.rglob("*") if path.is_file())
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as out:
        for path in members:
            out.write(path, f"{DEST.name}/{path.relative_to(DEST).as_posix()}")
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
