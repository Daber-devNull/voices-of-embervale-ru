"""Build an EML package with independent Russian resources for all voiced pages.

This is a staging tool. It never edits installed mods or game archives.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
GAME = PROJECT.parent
OUTPUT = PROJECT / "local/ru_voice_separate_520"
NAMESPACE = uuid.UUID("d3a5cd23-24e2-49a8-8e32-523d2680b045")
CALL = re.compile(
    r'^patch_sound\(("(?:[^"\\]|\\.)*"), (\d+), (\d+), \'audio/([^\']+)\'\)$',
    re.MULTILINE,
)
SOURCE_MODS = ("ru_voice_two_letters", "ru_voice_journal_batch")


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"Staged output already exists: {OUTPUT}")
    catalog = json.loads((PROJECT / "local/voice-slot-map-001.json").read_text(encoding="utf-8"))["entries"]
    by_name = {entry["english_sound_name"]: entry for entry in catalog}
    if len(by_name) != len(catalog):
        raise ValueError("Ambiguous sound names in voice-slot map")
    staged = []
    for mod_name in SOURCE_MODS:
        mod = GAME / "mods" / mod_name
        source = (mod / "src/mod.lua").read_text(encoding="utf-8")
        matches = list(CALL.finditer(source))
        if not matches:
            raise ValueError(f"No patch_sound calls in {mod_name}")
        for match in matches:
            name = json.loads(match.group(1))
            frames, size = int(match.group(2)), int(match.group(3))
            audio = mod / "audio" / match.group(4)
            if name not in by_name or not audio.is_file() or audio.stat().st_size != size:
                raise ValueError(f"Missing voice mapping or invalid audio: {name}")
            staged.append((name, frames, size, audio, by_name[name]))
    if len(staged) != 520 or len({x[0] for x in staged}) != 520:
        raise ValueError(f"Expected 520 unique sounds, got {len(staged)}")

    (OUTPUT / "src").mkdir(parents=True)
    (OUTPUT / "audio").mkdir()
    lua = [
        "-- Independent Russian sounds: no original language slot is modified.",
        "local game_build = tonumber(tostring(game.version):match('^(%d+)|'))",
        "assert(game_build and game_build >= 1269579 and tostring(game.version):match('|%^/game%d+/branches/release_%d+%.%d+|'),",
        "       'RU separate voice: game build is older than 1269579 or the release branch is unknown')",
        "print('RU_VOICE_GAME_VERSION ' .. tostring(game.version))",
        "local sounds = {}",
        "for _, resource in ipairs(game.assets.get_resources_by_type('keen::SoundResource')) do",
        "  local name = resource.data.debugName",
        "  if sounds[name] then sounds[name] = false else sounds[name] = resource end",
        "end",
        "local empty = '00000000-0000-0000-0000-000000000000'",
        "local function add_russian(name, voice_guid, sound_guid, container_guid, frames, bytes, file)",
        "  local english = sounds[name]",
        "  assert(english, 'RU separate voice: missing or ambiguous sound: ' .. name)",
        "  assert(english.data.framesPerSecond == 48000 and english.data.frameCount == frames, 'RU separate voice: format changed')",
        "  local original_content = game.assets.get_content(english.data.streamedData.hash)",
        "  assert(original_content and original_content.size == bytes, 'RU separate voice: source content changed')",
        "  local voice = game.assets.get_resource(voice_guid, 'keen::VoiceoverResource', 0)",
        "  assert(voice and tostring(voice.data.languages[1]) ~= empty, 'RU separate voice: missing voice resource')",
        "  local container = game.assets.get_resource(voice.data.languages[1], 'keen::SoundContainerResource', 0)",
        "  assert(container and tostring(container.data.entries[1].value.sound) == tostring(english.guid), 'RU separate voice: link changed')",
        "  local original = {}",
        "  for index = 1, 5 do original[index] = tostring(voice.data.languages[index]) end",
        "  local russian = game.assets.create_resource(english.data, 'keen::SoundResource', sound_guid, 0)",
        "  russian.data.debugName = 'RU_' .. string.sub(name, 4)",
        "  local content = game.assets.create_content(io.read(file))",
        "  assert(content.size == bytes, 'RU separate voice: replacement size changed')",
        "  russian.data.streamedData.hash = content",
        "  local russian_container = game.assets.create_resource(container.data, 'keen::SoundContainerResource', container_guid, 0)",
        "  russian_container.data.entries[1].value.sound = russian.guid",
        "  for index = 1, 5 do assert(tostring(voice.data.languages[index]) == original[index], 'RU separate voice: original slot changed') end",
        "  print('RU_VOICE_MAP ' .. voice_guid .. ' ' .. tostring(container.guid) .. ' ' .. tostring(russian_container.guid))",
        "end",
    ]
    manifest = []
    for index, (name, frames, size, audio, entry) in enumerate(staged):
        basename = f"{index:05d}.frameless-qoa.bin"
        target = OUTPUT / "audio" / basename
        shutil.copy2(audio, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        voice_guid = entry["voiceover_guid"]
        sound_guid = str(uuid.uuid5(NAMESPACE, voice_guid + "/sound"))
        container_guid = str(uuid.uuid5(NAMESPACE, voice_guid + "/container"))
        lua.append(f"add_russian({json.dumps(name)}, {json.dumps(voice_guid)}, {json.dumps(sound_guid)}, {json.dumps(container_guid)}, {frames}, {size}, 'audio/{basename}')")
        manifest.append({"name": name, "voiceover_guid": voice_guid, "audio": basename,
                         "russian_sound_guid": sound_guid, "russian_container_guid": container_guid,
                         "frames": frames, "bytes": size, "sha256": digest})
    (OUTPUT / "src/mod.lua").write_text("\n".join(lua) + "\n", encoding="utf-8")
    (OUTPUT / "mod.json").write_text(json.dumps({
        "id": "ru_voice_separate_520", "name": "Русская озвучка — отдельные ресурсы",
        "version": "0.0.1", "capabilities": ["patch"], "dependencies": [],
        "authors": ["Локальный любительский проект"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "manifest.json").write_text(json.dumps({"status": "staged_not_installed", "entries": manifest},
                                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"entries": len(manifest), "output": str(OUTPUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
