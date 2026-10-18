"""Extend the proven F3 voice mod with text-backed NPC greeting/farewell lines."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import uuid

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "local/ru_voice_separate_819"
VOICES = PROJECT / "local/npc-multi-001"
DEST = PROJECT / "local/ru_voice_separate_1118"
NATIVE = PROJECT / "local/ru_voice_1118_native"
NAMESPACE = uuid.UUID("d3a5cd23-24e2-49a8-8e32-523d2680b045")


def main() -> None:
    groups = json.loads((PROJECT / "local/npc-multi-catalog-001.json").read_text(encoding="utf-8"))["entries"]
    # Two Bard resources reuse the same three English sound takes for different
    # texts. The stage direction '(Напевает)' has no distinct source audio.
    groups = [g for g in groups if g["loca_tag"] != 591080302]
    if len(groups) != 299:
        raise ValueError("Expected 299 unambiguous NPC phrases")
    if DEST.exists() or NATIVE.exists():
        raise FileExistsError("Staging output already exists")
    shutil.copytree(SOURCE, DEST)
    NATIVE.mkdir()
    shutil.copy2(PROJECT / "local/ru_voice_819_native/voice_runtime.c", NATIVE / "voice_runtime.c")
    manifest_path = DEST / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(manifest["entries"]) != 795 or len(manifest["variant_entries"]) != 24:
        raise ValueError("Unexpected source package")
    offset = len(list((DEST / "audio").glob("*.bin")))
    if offset != 876:
        raise ValueError(f"Unexpected source audio count: {offset}")
    lua = (DEST / "src/mod.lua").read_text(encoding="utf-8").rstrip()
    lua += """

local streamed_template = assert(sounds['EN_Steppes_Ministory_05_FarmerLetter_page01_010'])
local function add_russian_multi(voice_guid, container_guid, takes)
  local voice = game.assets.get_resource(voice_guid, 'keen::VoiceoverResource', 0)
  assert(voice and tostring(voice.data.languages[1]) ~= empty, 'RU NPC multi: missing voice')
  local container = game.assets.get_resource(voice.data.languages[1], 'keen::SoundContainerResource', 0)
  assert(container and #container.data.entries == #takes, 'RU NPC multi: take count changed')
  local russian_container = game.assets.create_resource(container.data, 'keen::SoundContainerResource', container_guid, 0)
  for index, take in ipairs(takes) do
    local english = assert(sounds[take[1]], 'RU NPC multi: missing sound')
    assert(tostring(container.data.entries[index].value.sound) == tostring(english.guid), 'RU NPC multi: take order changed')
    assert(english.data.framesPerSecond == 48000 and english.data.frameCount == take[3], 'RU NPC multi: sound format changed')
    if take[6] == 'streamed' then
      local original_content = game.assets.get_content(english.data.streamedData.hash)
      assert(original_content and original_content.size == take[4], 'RU NPC multi: source content changed')
    end
    local template = take[6] == 'streamed' and english or streamed_template
    local russian = game.assets.create_resource(template.data, 'keen::SoundResource', take[2], 0)
    russian.data.debugName = 'RU_' .. take[1]
    russian.data.frameCount = take[3]
    russian.data.duration = english.data.duration
    local content = game.assets.create_content(io.read(take[5]))
    assert(content.size == take[4], 'RU NPC multi: replacement size changed')
    russian.data.streamedData.hash = content
    russian_container.data.entries[index].value.sound = russian.guid
  end
  print('RU_VOICE_MAP ' .. voice_guid .. ' ' .. tostring(container.guid) .. ' ' .. tostring(russian_container.guid))
end
"""
    multi_manifest = []
    sound_guid_to_file = {}
    for group in groups:
        voice_guid = group["voiceover_guid"]
        container_guid = str(uuid.uuid5(NAMESPACE, voice_guid + "/container"))
        takes = []
        for take in group["takes"]:
            index = take["sound_index"]
            source = VOICES / f"{index:05d}" / "russian.frameless-qoa.bin"
            meta = json.loads((source.parent / "metadata.json").read_text(encoding="utf-8"))
            if meta.get("status") != "encoded" or source.stat().st_size != take["source_size"]:
                raise ValueError(f"Unverified NPC sound: {take['sound_name']}")
            sound_guid = str(uuid.uuid5(NAMESPACE, voice_guid + "/variant/" + str(take["take_index"])))
            filename = f"{offset:05d}.frameless-qoa.bin"
            offset += 1
            shutil.copy2(source, DEST / "audio" / filename)
            takes.append(dict(name=take["sound_name"], sound_guid=sound_guid, audio=filename,
                              frames=take["frame_count"], bytes=take["source_size"], source_kind=take["source_kind"],
                              sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
            sound_guid_to_file[sound_guid] = filename
        rows = ", ".join("{" + ", ".join((json.dumps(t["name"]), json.dumps(t["sound_guid"]),
                                        str(t["frames"]), str(t["bytes"]), json.dumps("audio/"+t["audio"]),
                                        json.dumps(t["source_kind"]))) + "}" for t in takes)
        lua += f"\nadd_russian_multi({json.dumps(voice_guid)}, {json.dumps(container_guid)}, {{{rows}}})"
        multi_manifest.append(dict(voiceover_guid=voice_guid, original_container_guid=group["original_container_guid"],
                                   russian_container_guid=container_guid, loca_tag=group["loca_tag"],
                                   speaker_group=group["speaker_group"], takes=takes))
    manifest["multi_entries"] = multi_manifest
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DEST / "src/mod.lua").write_text(lua + "\n", encoding="utf-8")
    mod = json.loads((DEST / "mod.json").read_text(encoding="utf-8"))
    mod["version"] = "0.3.0"
    mod["name"] = "Голоса Эмбервейла — 525 страниц и 593 реплики NPC"
    (DEST / "mod.json").write_text(json.dumps(mod, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    header = (PROJECT / "local/ru_voice_819_native/guid_map.h").read_text(encoding="ascii")
    header = header.replace("/* Generated for 525 journal pages and 294 NPC dialogue lines. */",
                            "/* Generated for 525 journal pages and 593 NPC dialogue lines. */")
    additions = []
    from build_npc_mod import c_guid
    for group in multi_manifest:
        additions.append("  {" + c_guid(group["original_container_guid"]) + ", " +
                         c_guid(group["russian_container_guid"]) + "},")
    header = header.replace("};\n#define VOICE_GUID_MAP_COUNT 819",
                            "\n".join(additions) + "\n};\n#define VOICE_GUID_MAP_COUNT 1118")
    if "#define VOICE_GUID_MAP_COUNT 1118" not in header:
        raise ValueError("Unable to extend native GUID map")
    (NATIVE / "guid_map.h").write_text(header, encoding="ascii")
    print(json.dumps(dict(voiceovers=1118, new_npc_lines=len(multi_manifest),
                          new_audio=offset-876, total_audio=offset, mod=str(DEST), runtime=str(NATIVE))))


if __name__ == "__main__":
    main()
