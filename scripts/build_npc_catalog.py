"""Match original English NPC sound, voiceover, and Russian dialogue text."""
from __future__ import annotations

import json
import re
import struct
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools/inspector"))
import find_sound  # noqa: E402


def main() -> None:
    find_sound.ROOT = PROJECT / "local/game-backup-eml-001"
    reader = find_sound.Reader()
    by_guid = {key[:16]: i for i, key in enumerate(reader.keys)}
    sounds = json.loads((PROJECT / "local/sound-catalog-001.json").read_text(encoding="utf-8"))["short_descriptors"]
    npc = {x["index"]: x for x in sounds if x["name"].startswith(("EN_NPC_", "VO_"))}
    container_for_sound = defaultdict(list)
    for i, key in enumerate(reader.keys):
        if struct.unpack_from("<I", key, 16)[0] != 0xf257640c:
            continue
        data = reader.resource(i)
        if len(data) >= 144 and data[128:144] in by_guid:
            container_for_sound[by_guid[data[128:144]]].append(i)
    voice_for_container = defaultdict(list)
    for i, key in enumerate(reader.keys):
        if struct.unpack_from("<I", key, 16)[0] != 0x53e9cf8a:
            continue
        data = reader.resource(i)
        if data[:16] in by_guid:
            voice_for_container[by_guid[data[:16]]].append(i)
    voice_to_sound = {}
    for sound_index in npc:
        for ci in container_for_sound[sound_index]:
            for vi in voice_for_container[ci]:
                voice_to_sound[reader.keys[vi][:16]] = sound_index
    if not voice_to_sound:
        raise ValueError("No NPC voiceovers found")

    # In ECS templates each dialogue LocaTagId immediately precedes its VoiceoverResource reference.
    pattern = re.compile(b"|".join(re.escape(g) for g in voice_to_sound))
    localization = json.loads((PROJECT / "local/loc-9-tags.json").read_text(encoding="utf-8"))
    english = json.loads((PROJECT / "local/loc-1-tags.json").read_text(encoding="utf-8"))
    hits = defaultdict(list)
    for i, key in enumerate(reader.keys):
        if struct.unpack_from("<I", key, 16)[0] != 0x39768775:
            continue
        data = reader.resource(i)
        for match in pattern.finditer(data):
            pos = match.start()
            if pos < 4:
                continue
            tag = struct.unpack_from("<I", data, pos - 4)[0]
            if str(tag) not in localization:
                continue
            hits[match.group()].append((tag, i, pos))
    result = []
    for voice_guid, sound_index in voice_to_sound.items():
        sound = npc[sound_index]
        source = reader.resource(sound_index)
        channels, codec, rate, frames = struct.unpack_from("<BBHI", source)
        if (channels, codec, rate) != (0, 1, 48000) or len(sound["links"]) != 1:
            continue
        link = sound["links"][0]
        if link["size"] != ((frames + 19) // 20) * 8:
            continue
        all_hits = hits[voice_guid]
        tags = sorted({x[0] for x in all_hits})
        if sound["name"].startswith("EN_NPC_Townsfolk_"):
            group = ("LoraineCrim" if "LoraineCrim" in sound["name"] else
                     "MeiYinChen" if "MeiYinChen" in sound["name"] else
                     "MelvilleFontane" if "MelvilleFontane" in sound["name"] else "Townsfolk")
        else:
            group = sound["name"].split("_")[2] if sound["name"].startswith("EN_NPC_") else sound["name"].split("_")[1].capitalize()
        result.append(dict(sound_index=sound_index, sound_name=sound["name"], speaker_group=group,
                           voiceover_guid=str(uuid.UUID(bytes_le=voice_guid)),
                           russian_text=localization.get(str(tags[0])) if len(tags) == 1 else None,
                           english_text=english.get(str(tags[0])) if len(tags) == 1 else None,
                           loca_tag=tags[0] if len(tags) == 1 else None,
                           candidate_tags=tags, template_hits=[dict(tag=t, resource_index=i, offset=p) for t, i, p in all_hits],
                           frame_count=frames, original_duration=frames / rate,
                           source_file=f"enshrouded_{link['container']:03d}.dat",
                           source_offset=link["offset"], source_size=link["size"]))
    result.sort(key=lambda x: x["sound_name"])
    out = PROJECT / "local/npc-voice-catalog-001.json"
    out.write_text(json.dumps({"entries": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(sound_count=len(npc), mapped_voiceovers=len(voice_to_sound), entries=len(result),
                          unique_text=sum(bool(x["russian_text"]) for x in result),
                          missing_text=sum(not x["candidate_tags"] for x in result),
                          ambiguous_text=sum(len(x["candidate_tags"]) > 1 for x in result),
                          groups=Counter(x["speaker_group"] for x in result)), ensure_ascii=False))


if __name__ == "__main__":
    main()
