"""Voice all Loraine Crim sound variants with the same verified dialogue text."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import librosa
import soundfile as sf
import torch

PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "local/npc-variants-001"
sys.path.insert(0, str(PROJECT / "scripts"))
from batch_voice import encode_one  # noqa: E402
from generate_npc_voices import split_text, synthesize, RATE, MODEL  # noqa: E402


def main() -> None:
    entries = json.loads((PROJECT / "local/npc-variant-catalog-001.json").read_text(encoding="utf-8"))["entries"]
    OUT.mkdir(exist_ok=True)
    torch.set_num_threads(2)
    model = torch.package.PackageImporter(str(MODEL)).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    failures = []
    completed = 0
    for group in entries:
        parts = split_text(group["russian_text"])
        for variant in group["variants"]:
            directory = OUT / f"{variant['sound_index']:05d}"
            directory.mkdir(exist_ok=True)
            report = directory / "metadata.json"
            if report.is_file() and json.loads(report.read_text(encoding="utf-8")).get("status") == "encoded":
                completed += 1
                continue
            try:
                frames = variant["frame_count"]
                voice, pace = None, None
                for candidate_pace in ("medium", "fast"):
                    candidate = synthesize(model, parts, "kseniya", "medium", candidate_pace)
                    voice, pace = candidate, candidate_pace
                    if len(voice) < frames - int(.02 * RATE):
                        break
                if len(voice) > frames - int(.02 * RATE):
                    ratio = len(voice) / (frames - int(.02 * RATE))
                    if ratio > 1.40:
                        raise ValueError(f"Speech exceeds variant slot: {len(voice)/RATE:.2f}s > {frames/RATE:.2f}s")
                    voice = librosa.effects.time_stretch(voice, rate=ratio * 1.005)
                    pace += f"+stretch{ratio:.3f}"
                sf.write(directory / "voice.wav", voice, RATE, subtype="PCM_16")
                (directory / "spoken-text.txt").write_text("\n".join(parts) + "\n", encoding="utf-8")
                encoded = encode_one(variant, directory)
                if encoded["status"] != "encoded":
                    raise ValueError(str(encoded))
                details = dict(sound_index=variant["sound_index"], voiceover_guid=group["voiceover_guid"],
                               speaker="kseniya", pitch="medium", rate=pace,
                               slot_seconds=round(frames/RATE, 3), spoken_parts=parts, **encoded)
                report.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                completed += 1
                print(f"{completed}/81 encoded {variant['sound_index']}", flush=True)
            except Exception as exc:
                failures.append(dict(sound_index=variant["sound_index"], error=str(exc)))
                report.write_text(json.dumps(dict(sound_index=variant["sound_index"], status="failed", error=str(exc))),
                                  encoding="utf-8")
                print(f"FAILED {variant['sound_index']}: {exc}", flush=True)
    (OUT / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"completed": completed, "failed": len(failures)}))


if __name__ == "__main__":
    main()
