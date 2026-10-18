"""Regenerate every numbered journal page, retaining title and section pauses."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import html
import json
from pathlib import Path
import re
import shutil
import sys

import numpy as np
import soundfile as sf
import torch

PROJECT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT / "local/journal-voice-catalog-001.json"
MODEL = PROJECT / "local/tts-runtime/silero/v5_6_ru.pt"
OUT = PROJECT / "local/numeric-pages-001"
RATE = 48000
sys.path.insert(0, str(PROJECT / "scripts"))
from batch_voice import encode_one  # noqa: E402
from russian_numbers import verbalize  # noqa: E402


def parts_for(entry: dict) -> list[str]:
    if entry["sound_index"] == 51370:
        saved = PROJECT / "local/numeric-letter-51370/metadata.json"
        return json.loads(saved.read_text(encoding="utf-8"))["spoken_parts"]
    raw = re.sub(r"<br\s*/?>", "\n", entry["body"], flags=re.IGNORECASE)
    raw = html.unescape(re.sub(r"<[^>]+>", "", raw)).replace("*", "")
    chunks = [entry["title"], *[p.strip() for p in raw.split("\n\n") if p.strip()]]
    result = [verbalize(part) for part in chunks]
    if entry["sound_index"] == 24314:
        # This page is one 873-character paragraph; Silero rejects it as one request.
        sentences = re.split(r"(?<=[.!?])\s+", result[1])
        segments: list[str] = []
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) + 1 > 280:
                segments.append(current)
                current = ""
            current = (current + " " + sentence).strip()
        if current:
            segments.append(current)
        result = [result[0], *segments]
    if any(re.search(r"\d", part) for part in result):
        raise ValueError(f"Digits remain in {entry['sound_index']}")
    return result


def trim_edges(audio: np.ndarray) -> np.ndarray:
    active = np.flatnonzero(np.abs(audio) > .001)
    if not len(active):
        raise ValueError("TTS returned silence")
    margin = round(.08 * RATE)
    return audio[max(0, int(active[0])-margin):min(len(audio), int(active[-1])+margin+1)]


def synthesize(model: object, parts: list[str], rate: str) -> list[np.ndarray]:
    clips = []
    for part in parts:
        ssml = f'<speak><prosody rate="{rate}" pitch="low">{html.escape(part)}</prosody></speak>'
        try:
            generated = model.apply_tts(ssml_text=ssml, speaker="eugene", sample_rate=RATE)
        except ValueError:
            generated = model.apply_tts(text=part, speaker="eugene", sample_rate=RATE)
        clips.append(trim_edges(generated.detach().cpu().numpy().reshape(-1)))
    return clips


def assemble(clips: list[np.ndarray], parts: list[str], max_samples: int) -> tuple[np.ndarray, list[float]]:
    pauses = []
    for index, part in enumerate(parts[:-1]):
        pauses.append(2.0 if index == 0 else
                      1.2 if re.match(r"^[–—-]|^(Дата|Подпись)\s*:", parts[index+1]) else .65)
    speech = sum(len(clip) for clip in clips)
    pause_samples = [round(p*RATE) for p in pauses]
    overflow = speech + sum(pause_samples) - max_samples + round(.02*RATE)
    if overflow > 0:
        floors = [1.1 if index == 0 else .65 if pause >= 1.2 else .22
                  for index, pause in enumerate(pauses)]
        for index in reversed(range(len(pauses))):
            available = pause_samples[index] - round(floors[index]*RATE)
            take = min(max(0, available), overflow)
            pause_samples[index] -= take
            overflow -= take
            if overflow <= 0:
                break
    if overflow > 0:
        raise ValueError(f"Speech still exceeds slot by {overflow/RATE:.3f}s")
    chunks = []
    for index, clip in enumerate(clips):
        chunks.append(clip)
        if index < len(pause_samples):
            chunks.append(np.zeros(pause_samples[index], dtype=np.float32))
    return np.concatenate(chunks), [round(p/RATE, 3) for p in pause_samples]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["entries"]
    selected = [entry for entry in catalog if re.search(r"\d", entry["title"] + entry["body"])]
    if len(selected) != 134:
        raise ValueError(f"Expected 134 pages containing digits, got {len(selected)}")
    prepared = [(entry, parts_for(entry)) for entry in selected]
    if args.dry_run:
        print(json.dumps({"selected": len(prepared), "parts": sum(len(parts) for _, parts in prepared),
                          "remaining_digits": 0}))
        return
    OUT.mkdir(exist_ok=True)
    torch.set_num_threads(2)
    model = torch.package.PackageImporter(str(MODEL)).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    jobs = {}
    failures = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        for number, (entry, parts) in enumerate(prepared, 1):
            directory = OUT / f"{entry['sound_index']:05d}"
            directory.mkdir(exist_ok=True)
            wav = directory / "voice.wav"
            try:
                if (directory / "encoding.json").is_file() and \
                        (directory / "russian.frameless-qoa.bin").is_file():
                    continue
                if not wav.exists():
                    if entry["sound_index"] == 51370:
                        shutil.copy2(PROJECT / "local/numeric-letter-51370/carter-flint-numbers-preview.wav", wav)
                        chosen_rate, pauses = "approved-preview", [2.0] + [.65]*(len(parts)-2)
                    else:
                        clips = synthesize(model, parts, "slow")
                        try:
                            audio, pauses = assemble(clips, parts, entry["frame_count"])
                            chosen_rate = "slow"
                        except ValueError:
                            clips = synthesize(model, parts, "medium")
                            audio, pauses = assemble(clips, parts, entry["frame_count"])
                            chosen_rate = "medium"
                        sf.write(wav, audio, RATE, subtype="PCM_16")
                    (directory / "spoken-text.txt").write_text("\n\n".join(parts)+"\n", encoding="utf-8")
                    (directory / "preparation.json").write_text(json.dumps({
                        "sound_index": entry["sound_index"], "title": entry["title"],
                        "parts": parts, "rate": chosen_rate, "pauses_seconds": pauses,
                        "source_slot_seconds": round(entry["frame_count"]/RATE, 3),
                    }, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
                jobs[pool.submit(encode_one, entry, directory)] = (entry, directory)
                print(f"Prepared {number}/{len(prepared)} sound={entry['sound_index']}", flush=True)
            except Exception as exc:
                failures.append({"sound_index": entry["sound_index"], "stage": "synthesis", "error": str(exc)})
                print(f"FAILED synthesis {entry['sound_index']}: {exc}", flush=True)
        for future in as_completed(jobs):
            entry, directory = jobs[future]
            try:
                result = future.result()
                if result.get("status") != "encoded":
                    raise ValueError(str(result))
                (directory / "encoding.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n",
                                                           encoding="utf-8")
                print(f"Encoded sound={entry['sound_index']}", flush=True)
            except Exception as exc:
                failures.append({"sound_index": entry["sound_index"], "stage": "encoding", "error": str(exc)})
                print(f"FAILED encoding {entry['sound_index']}: {exc}", flush=True)
    (OUT / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"selected": len(prepared), "failures": len(failures)}))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
