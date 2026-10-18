"""Generate and QOA-encode short Russian journal entries; resume safely."""
from __future__ import annotations

import argparse
from array import array
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import html
import json
import math
from pathlib import Path
import sys
import wave

import numpy as np
import soundfile as sf
import torch

PROJECT = Path(__file__).resolve().parents[1]
GAME = PROJECT.parent
MODEL = PROJECT / "local/tts-runtime/silero/v5_6_ru.pt"
CATALOG = PROJECT / "local/journal-voice-catalog-001.json"
OUT = PROJECT / "local/batch-voice-001"
sys.path.insert(0, str(PROJECT / "tools/audio"))
from decode_frameless_qoa import decode, statistics  # noqa: E402
from encode_frameless_qoa import encode  # noqa: E402


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_one(entry: dict, directory: Path) -> dict:
    wav = directory / "voice.wav"
    with wave.open(str(wav), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 48000):
            raise ValueError("Unexpected WAV format")
        samples = array("h")
        samples.frombytes(stream.readframes(stream.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    frames = entry["frame_count"]
    if len(samples) > frames:
        return {"status": "too_long", "speech_seconds": len(samples) / 48000,
                "original_seconds": frames / 48000}
    path = GAME / entry["source_file"]
    with path.open("rb") as stream:
        stream.seek(entry["source_offset"])
        original_qoa = stream.read(entry["source_size"])
    if len(original_qoa) != entry["source_size"]:
        raise ValueError("Original sound range changed")
    original_rms = statistics(decode(original_qoa, frames), 48000)["rms"]
    energy = sum(value * value for value in samples)
    if not energy:
        raise ValueError("Generated WAV is silent")
    gain = min(original_rms / math.sqrt(energy / frames), 30000 / max(abs(value) for value in samples))
    speech_frames = len(samples)
    samples = array("h", (round(value * gain) for value in samples))
    samples.extend([0] * (frames - len(samples)))
    encoded = encode(samples)
    if len(encoded) != entry["source_size"]:
        raise ValueError("QOA size differs from original")
    roundtrip = decode(encoded, frames)
    error = math.sqrt(sum((a-b)**2 for a, b in zip(samples, roundtrip)) / frames)
    signal = math.sqrt(sum(s*s for s in samples) / frames)
    snr = 20 * math.log10(signal/error) if error else None
    if snr is not None and snr < 25:
        raise ValueError(f"Poor QOA roundtrip SNR: {snr}")
    (directory / "russian.frameless-qoa.bin").write_bytes(encoded)
    return {"status": "encoded", "speech_seconds": speech_frames / 48000,
            "original_seconds": frames / 48000, "gain": gain,
            "qoa_sha256": digest(encoded), "qoa_size": len(encoded), "snr_db": snr}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=114)
    parser.add_argument("--max-chars", type=int, default=400)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["entries"]
    eligible = [e for e in catalog if len(e["title"]) + len(e["body"]) < args.max_chars
                and e["sound_index"] not in (15940, 75978)]
    eligible.sort(key=lambda e: (len(e["title"]) + len(e["body"]), e["sound_index"]))
    eligible = eligible[:args.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    model = torch.package.PackageImporter(str(MODEL)).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    pending = {}
    finished = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for number, entry in enumerate(eligible, 1):
            directory = OUT / f"{entry['sound_index']:05d}"
            report = directory / "metadata.json"
            if report.exists():
                finished.append(json.loads(report.read_text(encoding="utf-8")))
                continue
            directory.mkdir(exist_ok=True)
            wav = directory / "voice.wav"
            parts = [entry["title"], *[p.strip().replace("**", "") for p in entry["body"].split("\n\n") if p.strip()]]
            if not wav.exists():
                try:
                    chunks = []
                    for i, part in enumerate(parts):
                        ssml = f'<speak><prosody rate="slow" pitch="low">{html.escape(part)}</prosody></speak>'
                        try:
                            audio = model.apply_tts(ssml_text=ssml, speaker="eugene", sample_rate=48000)
                        except ValueError:
                            audio = model.apply_tts(text=part, speaker="eugene", sample_rate=48000)
                        chunks.append(audio.detach().cpu().numpy().reshape(-1))
                        if i < len(parts) - 1:
                            next_is_signature = i == len(parts) - 2 and parts[-1].lstrip().startswith(("–", "—", "-"))
                            pause = 2.0 if i == 0 or next_is_signature else 0.65
                            chunks.append(np.zeros(int(pause * 48000), dtype=np.float32))
                    sf.write(wav, np.concatenate(chunks), 48000, subtype="PCM_16")
                except Exception as exc:
                    report = {"sound_index": entry["sound_index"], "sound_name": entry["sound_name"],
                              "title": entry["title"], "body": entry["body"],
                              "frame_count": entry["frame_count"], "source_size": entry["source_size"],
                              "status": "tts_error", "error": str(exc)}
                    (directory / "metadata.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    finished.append(report)
                    print(f"TTS failed {number}/{len(eligible)} sound={entry['sound_index']}: {exc}", flush=True)
                    continue
            pending[pool.submit(encode_one, entry, directory)] = (entry, directory, number)
            print(f"Generated {number}/{len(eligible)} sound={entry['sound_index']}", flush=True)
        for future in as_completed(pending):
            entry, directory, number = pending[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"status": "error", "error": str(exc)}
            report = {"sound_index": entry["sound_index"], "sound_name": entry["sound_name"],
                      "title": entry["title"], "body": entry["body"],
                      "frame_count": entry["frame_count"], "source_size": entry["source_size"], **result}
            (directory / "metadata.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            finished.append(report)
            print(f"Completed {number}/{len(eligible)} sound={entry['sound_index']} {result['status']}", flush=True)
    counts = {status: sum(item["status"] == status for item in finished)
              for status in sorted({item["status"] for item in finished})}
    print(json.dumps({"eligible": len(eligible), "outcomes": counts, "directory": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
