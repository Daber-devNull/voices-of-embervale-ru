"""Combine the 525 journal pages with verified text-backed NPC dialogue."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import uuid

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "local/ru_voice_separate_525_numeric"
VOICES = PROJECT / "local/npc-voices-001"
VARIANTS = PROJECT / "local/npc-variants-001"
DEST = PROJECT / "local/ru_voice_separate_819"
NATIVE = PROJECT / "local/ru_voice_819_native"
NAMESPACE = uuid.UUID("d3a5cd23-24e2-49a8-8e32-523d2680b045")
sys.path.insert(0, str(PROJECT / "tools/inspector"))
import find_sound  # noqa: E402


def c_guid(value: str) -> str:
    parsed = uuid.UUID(value)
    a, b, c, *_ = parsed.fields
    return "{0x%08x,0x%04x,0x%04x,{%s}}" % (a, b, c, ",".join(f"0x{x:02x}" for x in parsed.bytes[8:]))


def main() -> None:
    catalog = json.loads((PROJECT / "local/npc-voice-catalog-001.json").read_text(encoding="utf-8"))["entries"]
    selected = [x for x in catalog if x["russian_text"]]
    variant_catalog = json.loads((PROJECT / "local/npc-variant-catalog-001.json").read_text(encoding="utf-8"))["entries"]
    if len(selected) != 270:
        raise ValueError(f"Expected 270 text-backed NPC voiceovers; got {len(selected)}")
    for entry in selected:
        directory = VOICES / f"{entry['sound_index']:05d}"
        meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        audio = directory / "russian.frameless-qoa.bin"
        if meta["status"] != "encoded" or audio.stat().st_size != entry["source_size"]:
            raise ValueError(f"Unverified NPC audio: {entry['sound_name']}")
    for group in variant_catalog:
        for entry in group["variants"]:
            directory = VARIANTS / f"{entry['sound_index']:05d}"
            meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
            audio = directory / "russian.frameless-qoa.bin"
            if meta["status"] != "encoded" or audio.stat().st_size != entry["source_size"]:
                raise ValueError(f"Unverified NPC variant: {entry['sound_name']}")
    if DEST.exists() or NATIVE.exists():
        raise FileExistsError("NPC staging output already exists")
    shutil.copytree(SOURCE, DEST)
    manifest_doc = json.loads((DEST / "manifest.json").read_text(encoding="utf-8"))
    manifest = manifest_doc["entries"]
    if len(manifest) != 525:
        raise ValueError("Expected 525 original journal voices")
    lua = (DEST / "src/mod.lua").read_text(encoding="utf-8").rstrip("\n")
    for entry in selected:
        voice_guid = entry["voiceover_guid"]
        sound_guid = str(uuid.uuid5(NAMESPACE, voice_guid + "/sound"))
        container_guid = str(uuid.uuid5(NAMESPACE, voice_guid + "/container"))
        source = VOICES / f"{entry['sound_index']:05d}" / "russian.frameless-qoa.bin"
        basename = f"{len(manifest):05d}.frameless-qoa.bin"
        shutil.copy2(source, DEST / "audio" / basename)
        lua += (f"\nadd_russian({json.dumps(entry['sound_name'])}, {json.dumps(voice_guid)}, "
                f"{json.dumps(sound_guid)}, {json.dumps(container_guid)}, "
                f"{entry['frame_count']}, {entry['source_size']}, 'audio/{basename}')")
        manifest.append(dict(name=entry["sound_name"], voiceover_guid=voice_guid,
                             audio=basename, russian_sound_guid=sound_guid,
                             russian_container_guid=container_guid,
                             frames=entry["frame_count"], bytes=entry["source_size"],
                             sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                             speaker_group=entry["speaker_group"], loca_tag=entry["loca_tag"]))
    (DEST / "src/mod.lua").write_text(lua + "\n", encoding="utf-8")
    mod = json.loads((DEST / "mod.json").read_text(encoding="utf-8"))
    mod["version"] = "0.2.0"
    mod["name"] = "Голоса Эмбервейла — 525 страниц и 294 реплики NPC"
    (DEST / "mod.json").write_text(json.dumps(mod, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len({x["voiceover_guid"] for x in manifest}) != 795 or len({x["name"] for x in manifest}) != 795:
        raise ValueError("Duplicate voiceover or sound name")

    lua += """
local function add_russian_variants(voice_guid, container_guid, takes)
  local voice = game.assets.get_resource(voice_guid, 'keen::VoiceoverResource', 0)
  assert(voice and tostring(voice.data.languages[1]) ~= empty, 'RU NPC variants: missing voice')
  local container = game.assets.get_resource(voice.data.languages[1], 'keen::SoundContainerResource', 0)
  assert(container and #container.data.entries == #takes, 'RU NPC variants: changed take count')
  local russian_container = game.assets.create_resource(container.data, 'keen::SoundContainerResource', container_guid, 0)
  for index, take in ipairs(takes) do
    local english = sounds[take[1]]
    assert(english and tostring(container.data.entries[index].value.sound) == tostring(english.guid), 'RU NPC variants: changed source take')
    assert(english.data.framesPerSecond == 48000 and english.data.frameCount == take[3], 'RU NPC variants: changed format')
    local original_content = game.assets.get_content(english.data.streamedData.hash)
    assert(original_content and original_content.size == take[4], 'RU NPC variants: changed source content')
    local russian = game.assets.create_resource(english.data, 'keen::SoundResource', take[2], 0)
    russian.data.debugName = 'RU_' .. take[1]
    local content = game.assets.create_content(io.read(take[5]))
    assert(content.size == take[4], 'RU NPC variants: changed replacement size')
    russian.data.streamedData.hash = content
    russian_container.data.entries[index].value.sound = russian.guid
  end
  print('RU_VOICE_MAP ' .. voice_guid .. ' ' .. tostring(container.guid) .. ' ' .. tostring(russian_container.guid))
end
"""
    variant_manifest = []
    for group in variant_catalog:
        voice_guid = group["voiceover_guid"]
        container_guid = str(uuid.uuid5(NAMESPACE, voice_guid + "/container"))
        takes = []
        for entry in group["variants"]:
            source = VARIANTS / f"{entry['sound_index']:05d}" / "russian.frameless-qoa.bin"
            basename = f"{525 + 270 + sum(len(v['takes']) for v in variant_manifest) + len(takes):05d}.frameless-qoa.bin"
            shutil.copy2(source, DEST / "audio" / basename)
            sound_guid = str(uuid.uuid5(NAMESPACE, voice_guid + "/variant/" + entry["sound_name"]))
            takes.append(dict(name=entry["sound_name"], audio=basename, sound_guid=sound_guid,
                              frames=entry["frame_count"], bytes=entry["source_size"],
                              sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        lua_takes = ", ".join("{" + ", ".join((json.dumps(t["name"]), json.dumps(t["sound_guid"]),
                                              str(t["frames"]), str(t["bytes"]),
                                              json.dumps("audio/" + t["audio"]))) + "}" for t in takes)
        lua += f"\nadd_russian_variants({json.dumps(voice_guid)}, {json.dumps(container_guid)}, {{{lua_takes}}})"
        variant_manifest.append(dict(voiceover_guid=voice_guid, original_container_guid=group["original_container_guid"],
                                     russian_container_guid=container_guid, loca_tag=group["loca_tag"], takes=takes))
    manifest_doc["variant_entries"] = variant_manifest
    (DEST / "src/mod.lua").write_text(lua + "\n", encoding="utf-8")
    (DEST / "manifest.json").write_text(json.dumps(manifest_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len(variant_manifest) != 24 or sum(len(x["takes"]) for x in variant_manifest) != 81:
        raise ValueError("Incomplete variant manifest")

    find_sound.ROOT = PROJECT / "local/game-backup-eml-001"
    reader = find_sound.Reader()
    by_guid = {key[:16]: index for index, key in enumerate(reader.keys)}
    sound_catalog = json.loads((PROJECT / "local/sound-catalog-001.json").read_text(encoding="utf-8"))["short_descriptors"]
    sound_guid_by_name = {x["name"]: reader.keys[x["index"]][:16] for x in sound_catalog}
    NATIVE.mkdir()
    shutil.copy2(PROJECT / "local/ru_voice_525_native/voice_runtime.c", NATIVE / "voice_runtime.c")
    lines = ["/* Generated for 525 journal pages and 294 NPC dialogue lines. */", "#pragma once", "#include <windows.h>",
             "typedef struct { GUID english; GUID russian; } VoiceGuidMap;",
             "static const VoiceGuidMap kVoiceGuidMap[] = {"]
    for item in manifest:
        voice = reader.resource(by_guid[uuid.UUID(item["voiceover_guid"]).bytes_le])
        original_guid = voice[:16]
        if original_guid not in by_guid:
            raise ValueError(f"Missing original English container: {item['name']}")
        container = reader.resource(by_guid[original_guid])
        sound_index = by_guid.get(container[128:144])
        if sound_index is None or reader.sound(sound_index)["name"] != item["name"]:
            raise ValueError(f"Unexpected original sound for {item['name']}")
        lines.append("  {" + c_guid(str(uuid.UUID(bytes_le=original_guid))) + ", " + c_guid(item["russian_container_guid"]) + "},")
    for item in variant_manifest:
        original = uuid.UUID(item["original_container_guid"]).bytes_le
        voice = reader.resource(by_guid[uuid.UUID(item["voiceover_guid"]).bytes_le])
        if voice[:16] != original:
            raise ValueError("Variant original container changed")
        container = reader.resource(by_guid[original])
        expected = [sound_guid_by_name[take["name"]] for take in item["takes"]]
        actual = [container[p:p+16] for p in range(0, len(container)-15, 4) if container[p:p+16] in expected]
        if actual != expected:
            raise ValueError("Variant sound order changed")
        lines.append("  {" + c_guid(item["original_container_guid"]) + ", " + c_guid(item["russian_container_guid"]) + "},")
    lines += ["};", "#define VOICE_GUID_MAP_COUNT 819", ""]
    (NATIVE / "guid_map.h").write_text("\n".join(lines), encoding="ascii")
    print(json.dumps(dict(entries=len(manifest) + len(variant_manifest), npc_lines=len(selected) + len(variant_manifest),
                          audio_files=len(manifest) + sum(len(x["takes"]) for x in variant_manifest),
                          mod=str(DEST), runtime=str(NATIVE))))


if __name__ == "__main__":
    main()
