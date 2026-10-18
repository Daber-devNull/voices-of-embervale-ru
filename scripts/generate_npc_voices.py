"""Synthesize text-backed NPC dialogue with stable per-character voices."""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

PROJECT = Path(__file__).resolve().parents[1]
MODEL = PROJECT / "local/tts-runtime/silero/v5_6_ru.pt"
OUT = PROJECT / "local/npc-voices-001"
RATE = 48000
sys.path.insert(0, str(PROJECT / "scripts"))
from batch_voice import encode_one  # noqa: E402
from russian_numbers import verbalize  # noqa: E402

VOICE = {
    "Alchemist": ("eugene", "low"),
    "Barber": ("aidar", "medium"),
    "Bard": ("xenia", "medium"),
    "Blacksmith": ("aidar", "low"),
    "Carpenter": ("eugene", "medium"),
    "Farmer": ("baya", "medium"),
    "Huntress": ("kseniya", "low"),
    "Townsfolk": ("xenia", "high"),
    "MeiYinChen": ("xenia", "high"),
    "LoraineCrim": ("kseniya", "medium"),
    "MelvilleFontane": ("aidar", "medium"),
    "cryptKeeper": ("baya", "low"),
}


def split_text(value: str) -> list[str]:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = html.unescape(re.sub(r"<[^>]+>", "", value)).replace("*", "")
    value = verbalize(value)
    if re.search(r"\d", value):
        raise ValueError("Unspoken digits remain")
    segments = []
    for paragraph in value.splitlines():
        pending = ""
        for sentence in re.split(r"(?<=[.!?…])\s+", paragraph.strip()):
            if not sentence:
                continue
            if pending and len(pending) + len(sentence) + 1 > 260:
                segments.append(pending)
                pending = ""
            pending = (pending + " " + sentence).strip()
        if pending:
            segments.append(pending)
    return segments


def trim(audio: np.ndarray) -> np.ndarray:
    active = np.flatnonzero(np.abs(audio) > .001)
    if not len(active):
        raise ValueError("TTS produced silence")
    margin = int(.06 * RATE)
    return audio[max(0, int(active[0]) - margin):min(len(audio), int(active[-1]) + margin + 1)]


def synthesize(model: object, parts: list[str], speaker: str, pitch: str, rate: str) -> np.ndarray:
    clips = []
    for part in parts:
        markup = f'<speak><prosody rate="{rate}" pitch="{pitch}">{html.escape(part)}</prosody></speak>'
        try:
            samples = model.apply_tts(ssml_text=markup, speaker=speaker, sample_rate=RATE)
        except ValueError:
            samples = model.apply_tts(text=part, speaker=speaker, sample_rate=RATE)
        clips.append(trim(samples.detach().cpu().numpy().reshape(-1)))
    pieces = []
    for i, clip in enumerate(clips):
        pieces.append(clip)
        if i < len(clips) - 1:
            pieces.append(np.zeros(int(.28 * RATE), dtype=np.float32))
    return np.concatenate(pieces)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--shard-id", type=int, default=0)
    parser.add_argument("--only-extra", action="store_true")
    parser.add_argument("--only-group", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    entries = json.loads((PROJECT / "local/npc-voice-catalog-001.json").read_text(encoding="utf-8"))["entries"]
    entries = [x for x in entries if x["russian_text"]]
    if args.only_extra:
        entries = [x for x in entries if x["sound_name"].startswith("VO_")]
    else:
        entries = [x for x in entries if x["sound_name"].startswith("EN_NPC_")]
    if args.only_group:
        entries = [x for x in entries if x.get("speaker_group") == args.only_group]
    entries.sort(key=lambda x: (x.get("speaker_group", x["sound_name"].split("_")[2]), x["sound_index"]))
    if args.limit:
        entries = entries[:args.limit]
    if not 0 <= args.shard_id < args.shards:
        raise ValueError("Invalid shard id")
    entries = [entry for index, entry in enumerate(entries) if index % args.shards == args.shard_id]
    OUT.mkdir(exist_ok=True)
    torch.set_num_threads(2)
    model = torch.package.PackageImporter(str(MODEL)).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    failures = []
    for number, entry in enumerate(entries, 1):
        group = entry.get("speaker_group", entry["sound_name"].split("_")[2])
        speaker, pitch = VOICE[group]
        directory = OUT / f"{entry['sound_index']:05d}"
        directory.mkdir(exist_ok=True)
        report = directory / "metadata.json"
        if report.is_file():
            saved = json.loads(report.read_text(encoding="utf-8"))
            if saved.get("status") == "encoded" and not args.force:
                continue
        try:
            parts = split_text(entry["russian_text"])
            if not parts:
                raise ValueError("Empty dialogue text")
            source_frames = entry["frame_count"]
            voice = None
            rate_name = None
            for pace in ("medium", "fast"):
                candidate = synthesize(model, parts, speaker, pitch, pace)
                if len(candidate) <= source_frames - int(.02 * RATE):
                    voice, rate_name = candidate, pace
                    break
                voice = candidate
                rate_name = pace
            if len(voice) > source_frames - int(.02 * RATE):
                ratio = len(voice) / (source_frames - int(.02 * RATE))
                if ratio > 1.22:
                    raise ValueError(f"Speech exceeds original slot: {len(voice)/RATE:.2f}s > {source_frames/RATE:.2f}s")
                import librosa
                voice = librosa.effects.time_stretch(voice, rate=ratio * 1.005)
                rate_name += f"+stretch{ratio:.3f}"
            sf.write(directory / "voice.wav", voice, RATE, subtype="PCM_16")
            (directory / "spoken-text.txt").write_text("\n".join(parts) + "\n", encoding="utf-8")
            encoded = encode_one(entry, directory)
            if encoded["status"] != "encoded":
                raise ValueError(str(encoded))
            details = dict(sound_index=entry["sound_index"], sound_name=entry["sound_name"],
                           speaker=speaker, pitch=pitch, rate=rate_name,
                           slot_seconds=round(source_frames/RATE, 3),
                           spoken_parts=parts, **encoded)
            report.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{number}/{len(entries)} encoded {entry['sound_index']} {group}", flush=True)
        except Exception as exc:
            item = dict(sound_index=entry["sound_index"], name=entry["sound_name"], error=str(exc))
            failures.append(item)
            report.write_text(json.dumps(dict(item, status="failed"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{number}/{len(entries)} FAILED {entry['sound_index']}: {exc}", flush=True)
    suffix = "-extra" if args.only_extra else ""
    (OUT / f"failures{suffix}-{args.shard_id}.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(selected=len(entries), failed=len(failures)), ensure_ascii=False))


if __name__ == "__main__":
    main()
