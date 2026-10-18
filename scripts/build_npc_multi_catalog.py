"""Find text-backed NPC greetings and farewells with randomized sound takes."""
from __future__ import annotations

import json
import struct
import sys
import uuid
from collections import defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools/inspector"))
import find_sound  # noqa: E402

GROUPS = {"VO_bard": "Bard", "VO_fisherman": "MelvilleFontane",
          "NPC_barber": "Barber", "VO_collector": "Collector", "NPC_trader": "Trader",
          "VO_farmer": "Farmer", "VO_carpenter": "Carpenter", "VO_huntress": "Huntress",
          "VO_blacksmith": "Blacksmith", "VO_alchemist": "Alchemist"}


def main() -> None:
    find_sound.ROOT = PROJECT / "local/game-backup-eml-001"
    reader = find_sound.Reader()
    by_guid = {key[:16]: i for i, key in enumerate(reader.keys)}
    ru = json.loads((PROJECT / "local/loc-9-tags.json").read_text(encoding="utf-8"))
    en = json.loads((PROJECT / "local/loc-1-tags.json").read_text(encoding="utf-8"))
    short = json.loads((PROJECT / "local/sound-catalog-001.json").read_text(encoding="utf-8"))["short_descriptors"]
    sound_names = {x["index"]: x["name"] for x in short}
    already = {uuid.UUID(x["voiceover_guid"]).bytes_le for x in
               json.loads((PROJECT / "local/npc-variant-catalog-001.json").read_text(encoding="utf-8"))["entries"]}
    candidates = {}
    for i, key in enumerate(reader.keys):
        if struct.unpack_from("<I", key, 16)[0] != 0x53e9cf8a or key[:16] in already:
            continue
        container_guid = reader.resource(i)[:16]
        ci = by_guid.get(container_guid)
        if ci is None or reader.resource(ci)[128:144] in by_guid:
            continue
        candidates[key[:16]] = (i, ci)
    prefix = defaultdict(list)
    for guid in candidates:
        prefix[guid[:4]].append(guid)
    hits = defaultdict(set)
    for i, key in enumerate(reader.keys):
        if struct.unpack_from("<I", key, 16)[0] != 0x39768775:
            continue
        data = reader.resource(i)
        for pos in range(4, len(data)-15, 4):
            possible = prefix.get(data[pos:pos+4])
            if possible and data[pos:pos+16] in possible:
                tag = struct.unpack_from("<I", data, pos-4)[0]
                if str(tag) in ru:
                    hits[data[pos:pos+16]].add(tag)
    result = []
    unresolved = []
    for guid, (vi, ci) in candidates.items():
        tags = hits[guid]
        if len(tags) != 1:
            unresolved.append(dict(voiceover_index=vi, reason="no_text" if not tags else "ambiguous_text", tags=sorted(tags)))
            continue
        tag = next(iter(tags))
        container = reader.resource(ci)
        takes = []
        for pos in range(0, len(container)-15, 4):
            si = by_guid.get(container[pos:pos+16])
            if si is None or struct.unpack_from("<I", reader.keys[si], 16)[0] != 0xdf74e485:
                continue
            sound = reader.sound(si)
            if not sound or len(sound["links"]) > 1:
                raise ValueError(f"Unexpected sound descriptor: {si}")
            descriptor = reader.resource(si)
            channels, codec, rate, frames = struct.unpack_from("<BBHI", descriptor)
            if sound["links"]:
                link = sound["links"][0]
                source = dict(source_kind="streamed", source_file=f"enshrouded_{link['container']:03d}.dat",
                              source_offset=link["offset"], source_size=link["size"])
            else:
                relative, size = struct.unpack_from("<II", descriptor, 16)
                source = dict(source_kind="inline", source_resource_index=si,
                              source_inline_offset=16+relative, source_size=size)
            if (channels, codec, rate) != (0, 1, 48000) or source["source_size"] != ((frames+19)//20)*8:
                raise ValueError(f"Unsupported voice sound: {si}")
            takes.append(dict(take_index=len(takes)+1, sound_index=si,
                              sound_name=sound_names.get(si, sound["name"]),
                              frame_count=frames, original_duration=frames/rate,
                              **source))
        if not takes:
            raise ValueError(f"No sound takes for voiceover {vi}")
        name = takes[0]["sound_name"]
        prefix_name = "_".join(name.split("_")[:2])
        if prefix_name not in GROUPS:
            raise ValueError(f"Unknown speaking character for {name}")
        result.append(dict(voiceover_guid=str(uuid.UUID(bytes_le=guid)),
                           original_container_guid=str(uuid.UUID(bytes_le=reader.keys[ci][:16])),
                           speaker_group=GROUPS[prefix_name], original_sound_group=prefix_name,
                           loca_tag=tag, russian_text=ru[str(tag)], english_text=en.get(str(tag)),
                           takes=takes))
    result.sort(key=lambda x: x["voiceover_guid"])
    out = PROJECT / "local/npc-multi-catalog-001.json"
    out.write_text(json.dumps({"entries": result, "unresolved": unresolved}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(voiceovers=len(result), sound_takes=sum(len(x["takes"]) for x in result),
                          no_text=sum(x["reason"] == "no_text" for x in unresolved),
                          ambiguous=sum(x["reason"] == "ambiguous_text" for x in unresolved)), ensure_ascii=False))


if __name__ == "__main__":
    main()
