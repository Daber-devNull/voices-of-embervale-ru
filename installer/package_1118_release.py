"""Build and verify the offline NPC-and-journal Nexus package without touching the game."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "release/ru-voice-f3-0.1.0/payload"
DLL = ROOT / "local/ru_voice_1118_native/shroudtopia.dll"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.3.2-beta")
    parser.add_argument("--publish", type=Path, default=ROOT / "installer/publish-0.3.2")
    parser.add_argument("--mod", type=Path, default=ROOT / "local/ru_voice_separate_1118")
    args = parser.parse_args()
    mod = args.mod.resolve()
    dest = ROOT / "release" / f"Voices-of-Embervale-RU-{args.version}-Nexus"
    if dest.exists() or dest.with_name(dest.name + ".zip").exists():
        raise FileExistsError("Release output already exists")
    mod_manifest = json.loads((mod / "manifest.json").read_text(encoding="utf-8"))
    if len(mod_manifest["entries"]) != 795 or len(mod_manifest["variant_entries"]) != 24 or len(mod_manifest["multi_entries"]) != 299:
        raise ValueError("Mod must contain 525 journal pages and 593 NPC lines")
    for entry in mod_manifest["entries"]:
        audio = mod / "audio" / entry["audio"]
        if audio.stat().st_size != entry["bytes"] or sha(audio) != entry["sha256"]:
            raise ValueError(f"Audio mismatch: {audio}")
    for group in mod_manifest["variant_entries"]:
        for entry in group["takes"]:
            audio = mod / "audio" / entry["audio"]
            if audio.stat().st_size != entry["bytes"] or sha(audio) != entry["sha256"]:
                raise ValueError(f"Variant audio mismatch: {audio}")

    for group in mod_manifest["multi_entries"]:
        for entry in group["takes"]:
            audio = mod / "audio" / entry["audio"]
            if audio.stat().st_size != entry["bytes"] or sha(audio) != entry["sha256"]:
                raise ValueError(f"Multi-variant audio mismatch: {audio}")
    if len(list((mod / "audio").glob("*.bin"))) != 1711:
        raise ValueError("Expected 1711 audio files")

    payload = dest / "payload"
    shutil.copytree(mod, payload / "mod")
    shutil.copytree(OLD / "native", payload / "native")
    shutil.copytree(OLD / "tools", payload / "tools")
    shutil.copy2(DLL, payload / "native/shroudtopia.dll")
    files = sorted(path for path in payload.rglob("*") if path.is_file())
    hashes = {path.relative_to(payload).as_posix(): sha(path) for path in files}
    if len(hashes) != 1718:
        raise ValueError(f"Expected 1718 payload files, got {len(hashes)}")
    (payload / "manifest.json").write_text(
        json.dumps({"files": hashes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for path in args.publish.iterdir():
        if path.is_file() and path.suffix.lower() != ".pdb":
            shutil.copy2(path, dest / path.name)
    shutil.copy2(ROOT / "installer/THIRD_PARTY.md", dest / "THIRD_PARTY.md")
    shutil.copytree(ROOT / "installer/licenses", dest / "licenses")
    release_note = ("В beta 0.3.2 добавлена диагностика в ru_voice_installer.log и поддержка сборок игры начиная с 1269579 "
                    "при условии совместимости аудиофункций. В 134 страницах с цифрами числа произносятся словами.\n\n")
    (dest / "README.md").write_text(
        f"# Голоса Эмбервейла — версия {args.version}\n\n"
        "Русская озвучка всех 525 найденных страниц дневника и 593 реплик персонажей. "
        "Распакуйте архив целиком. При закрытой игре запустите VoiceInstaller.exe, "
        "укажите папку с enshrouded.exe и нажмите «Проверить состояние», затем «Установить мод». "
        "В игре F3 включает и выключает русскую озвучку при любом выбранном языке.\n\n"
        "Если уже установлена прежняя версия, в новом установщике нажмите "
        "«Отключить · копию сохранить», затем «Установить мод».\n\n"
        + release_note +
        "«Отключить · копию сохранить» возвращает игровые индексы и сохраняет резервную копию. "
        "«Удалить мод и копию» также удаляет резервную копию. "
        "Обе операции требуют закрыть игру. Минимальная сборка Enshrouded — 1269579. "
        "Установщик проверяет аудиофункции и останавливается, если они изменились. "
        "При проблеме пришлите ru_voice_installer.log и ru_voice_runtime.log из папки игры. "
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
    print(json.dumps({"entries": 1118, "audio_files": 1711, "payload_files": len(hashes), "archive": str(archive),
                      "archive_bytes": archive.stat().st_size, "sha256": digest}))


if __name__ == "__main__":
    main()
