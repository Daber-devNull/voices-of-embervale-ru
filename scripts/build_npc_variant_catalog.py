"""Catalog Loraine Crim greetings with several randomly selected sound takes."""
from __future__ import annotations

import json
import re
import struct
import sys
import uuid
from collections import defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools/inspector"))
import find_sound  # noqa: E402


def main() -> None:
    find_sound.ROOT = PROJECT / "local/game-backup-eml-001"
    reader = find_sound.Reader()
    sounds = json.loads((PROJECT / "local/sound-catalog-001.json").read_text(encoding="utf-8"))["short_descriptors"]
    loraine = {reader.keys[x["index"]][:16]: x for x in sounds
               if x["name"].startswith("EN_NPC_Townsfolk_villager_female_06")}
    containers = {}
    for i, key in enumerate(reader.keys):
        if struct.unpack_from("<I", key, 16)[0] != 0xf257640c:
            continue
        data = reader.resource(i)
        linked = [(pos, loraine[data[pos:pos+16]]) for pos in range(0, len(data)-15, 4)
                  if data[pos:pos+16] in loraine]
        if len(linked) > 1:
            containers[key[:16]] = (i, linked)
    voiceovers = {}
    for i, key in enumerate(reader.keys):
        if struct.unpack_from("<I", key, 16)[0] != 0x53e9cf8a:
            continue
        container_guid = reader.resource(i)[:16]
        if container_guid in containers:
            voiceovers[key[:16]] = (i, *containers[container_guid])
    pattern = re.compile(b"|".join(re.escape(g) for g in voiceovers))
    ru = json.loads((PROJECT / "local/loc-9-tags.json").read_text(encoding="utf-8"))
    en = json.loads((PROJECT / "local/loc-1-tags.json").read_text(encoding="utf-8"))
    hits = defaultdict(set)
    for i, key in enumerate(reader.keys):
        if struct.unpack_from("<I", key, 16)[0] != 0x39768775:
            continue
        data = reader.resource(i)
        for match in pattern.finditer(data):
            if match.start() >= 4:
                tag = struct.unpack_from("<I", data, match.start()-4)[0]
                if str(tag) in ru:
                    hits[match.group()].add(tag)
    result = []
    for voice_guid, (vi, ci, linked) in voiceovers.items():
        tags = hits[voice_guid]
        if len(tags) != 1:
            raise ValueError(f"Ambiguous text for voiceover {vi}: {tags}")
        tag = next(iter(tags))
        variants = []
        for _, sound in linked:
            source = reader.resource(sound["index"])
            channels, codec, rate, frames = struct.unpack_from("<BBHI", source)
            if (channels, codec, rate) != (0, 1, 48000) or len(sound["links"]) != 1:
                raise ValueError(f"Unsupported sound variant: {sound['name']}")
            link = sound["links"][0]
            if link["size"] != ((frames + 19) // 20) * 8:
                raise ValueError(f"Invalid QOA size: {sound['name']}")
            variants.append(dict(sound_index=sound["index"], sound_name=sound["name"],
                                 frame_count=frames, original_duration=frames/rate,
                                 source_file=f"enshrouded_{link['container']:03d}.dat",
                                 source_offset=link["offset"], source_size=link["size"]))
        result.append(dict(voiceover_guid=str(uuid.UUID(bytes_le=voice_guid)),
                           original_container_guid=str(uuid.UUID(bytes_le=reader.keys[ci][:16])),
                           loca_tag=tag, russian_text=ru[str(tag)], english_text=en.get(str(tag)),
                           speaker_group="LoraineCrim", variants=variants))
    result.sort(key=lambda x: x["voiceover_guid"])
    if len(result) != 24 or sum(len(x["variants"]) for x in result) != 81:
        raise ValueError("Unexpected variant count")
    out = PROJECT / "local/npc-variant-catalog-001.json"
    out.write_text(json.dumps({"entries": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"voiceovers": len(result), "sound_variants": sum(len(x["variants"]) for x in result)}))


if __name__ == "__main__":
    main()
