"""Render localized NPC greeting/farewell lines into every original sound slot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import librosa
import soundfile as sf
import torch

PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "local/npc-multi-001"
sys.path.insert(0, str(PROJECT / "scripts"))
from batch_voice import encode_one  # noqa: E402
from generate_npc_voices import MODEL, RATE, VOICE, split_text, synthesize  # noqa: E402

VOICE.update({"Collector": ("baya", "low"), "Trader": ("xenia", "medium")})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    groups = json.loads((PROJECT / "local/npc-multi-catalog-001.json").read_text(encoding="utf-8"))["entries"]
    groups = [group for group in groups if group["loca_tag"] != 591080302]
    if args.limit:
        groups = groups[:args.limit]
    OUT.mkdir(exist_ok=True)
    torch.set_num_threads(2)
    model = torch.package.PackageImporter(str(MODEL)).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    failed = []
    completed = 0
    assigned = {}
    for number, group in enumerate(groups, 1):
        pending = [take for take in group["takes"] if not (
            (OUT / f"{take['sound_index']:05d}" / "metadata.json").is_file() and
            json.loads((OUT / f"{take['sound_index']:05d}" / "metadata.json").read_text(encoding="utf-8")).get("status") == "encoded")]
        if not pending:
            for take in group["takes"]:
                assigned[take["sound_index"]] = group["russian_text"]
                completed += 1
            continue
        speaker, pitch = VOICE[group["speaker_group"]]
        parts = split_text(group["russian_text"])
        if not parts:
            raise ValueError(f"Empty dialogue: {group['voiceover_guid']}")
        # Each randomized English take receives the same localized line.
        # Build both paces once per line, then fit each original slot.
        base = {pace: synthesize(model, parts, speaker, pitch, pace)
                for pace in ("medium", "fast")}
        for take in group["takes"]:
            index = take["sound_index"]
            previous = assigned.get(index)
            if previous is not None:
                if previous != group["russian_text"]:
                    failed.append(dict(sound_index=index, error="Shared sound has conflicting localization"))
                continue
            assigned[index] = group["russian_text"]
            directory = OUT / f"{index:05d}"
            directory.mkdir(exist_ok=True)
            report = directory / "metadata.json"
            if report.is_file() and json.loads(report.read_text(encoding="utf-8")).get("status") == "encoded":
                completed += 1
                continue
            try:
                frames = take["frame_count"]
                budget = frames - int(.02 * RATE)
                if budget <= 0:
                    raise ValueError("Sound slot too short")
                pace = "medium" if len(base["medium"]) <= budget else "fast"
                voice = base[pace]
                if len(voice) > budget:
                    ratio = len(voice) / budget
                    if ratio > 1.65:
                        raise ValueError(f"Speech exceeds slot: {len(voice)/RATE:.2f}s > {frames/RATE:.2f}s")
                    voice = librosa.effects.time_stretch(voice, rate=ratio * 1.006)
                    pace += f"+stretch{ratio:.3f}"
                sf.write(directory / "voice.wav", voice, RATE, subtype="PCM_16")
                (directory / "spoken-text.txt").write_text("\n".join(parts) + "\n", encoding="utf-8")
                encoded = encode_one(take, directory)
                if encoded["status"] != "encoded":
                    raise ValueError(str(encoded))
                report.write_text(json.dumps(dict(sound_index=index, voiceover_guid=group["voiceover_guid"],
                                                   speaker=speaker, pitch=pitch, rate=pace, spoken_parts=parts,
                                                   **encoded), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                completed += 1
            except Exception as exc:
                failed.append(dict(sound_index=index, error=str(exc)))
                report.write_text(json.dumps(dict(sound_index=index, status="failed", error=str(exc)),
                                             ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{number}/{len(groups)} groups; {completed} takes ready; {len(failed)} failed", flush=True)
    (OUT / "failures.json").write_text(json.dumps(failed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(groups=len(groups), completed=completed, failed=len(failed))))


if __name__ == "__main__":
    main()
