"""Create a local preview of a journal page with all numeric values spoken."""
from __future__ import annotations

import html
import json
from pathlib import Path
import re
import sys

import numpy as np
import soundfile as sf
import torch

PROJECT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT / "local/journal-voice-catalog-001.json"
MODEL = PROJECT / "local/tts-runtime/silero/v5_6_ru.pt"
OUTPUT = PROJECT / "local/numeric-letter-51370"
SAMPLE_RATE = 48000


def spoken_text(entry: dict) -> list[str]:
    title = entry["title"].replace("\xa0", " ")
    title = title.replace(" — ", ". ").replace("отчет номер А.053", "отчёт номер А, ноль пятьдесят три")
    body = html.unescape(re.sub(r"<[^>]+>", "", entry["body"])).replace("*", "")
    body = body.replace("3-й день расцветья, 500 год Эпохи зари",
                        "третий день расцветья, пятисотый год Эпохи Зари")
    body = body.replace("1 минута", "одна минута")
    body = body.replace("2, 3, 5, 8 и в последнем случае 13 минут",
                        "две, три, пять, восемь и в последнем случае тринадцать минут")
    parts = [title, *[part.strip() for part in body.split("\n\n") if part.strip()]]
    if re.search(r"[0-9]", " ".join(parts)):
        raise ValueError("Unspoken digits remain")
    return parts


def trim_edges(audio: np.ndarray) -> np.ndarray:
    """Remove generated edge silence while keeping a short breath at each end."""
    active = np.flatnonzero(np.abs(audio) > 0.001)
    if not len(active):
        raise ValueError("TTS returned silence")
    margin = int(0.08 * SAMPLE_RATE)
    return audio[max(0, int(active[0]) - margin):min(len(audio), int(active[-1]) + margin + 1)]


def main() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["entries"]
    entry = next(e for e in catalog if e["sound_index"] == 51370)
    parts = spoken_text(entry)
    OUTPUT.mkdir(exist_ok=True)
    torch.set_num_threads(2)
    model = torch.package.PackageImporter(str(MODEL)).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    audio_parts: list[np.ndarray] = []
    durations = []
    for index, part in enumerate(parts):
        print(f"Synthesizing {index + 1}/{len(parts)}", flush=True)
        ssml = f'<speak><prosody rate="slow" pitch="low">{html.escape(part)}</prosody></speak>'
        try:
            generated = model.apply_tts(ssml_text=ssml, speaker="eugene", sample_rate=SAMPLE_RATE)
        except ValueError:
            generated = model.apply_tts(text=part, speaker="eugene", sample_rate=SAMPLE_RATE)
        clip = trim_edges(generated.detach().cpu().numpy().reshape(-1))
        audio_parts.append(clip)
        durations.append(round(len(clip) / SAMPLE_RATE, 3))
        if index < len(parts) - 1:
            pause = 2.0 if index == 0 else (1.0 if part.startswith("Дата:") else 0.65)
            audio_parts.append(np.zeros(round(pause * SAMPLE_RATE), dtype=np.float32))
    audio = np.concatenate(audio_parts)
    wav = OUTPUT / "carter-flint-numbers-preview.wav"
    sf.write(wav, audio, SAMPLE_RATE, subtype="PCM_16")
    metadata = {"sound_index": 51370, "source_title": entry["title"],
                "spoken_parts": parts, "part_seconds": durations,
                "duration_seconds": round(len(audio) / SAMPLE_RATE, 3),
                "original_slot_seconds": round(entry["original_duration"], 3),
                "title_pause_seconds": 2.0, "section_pause_seconds": 0.65,
                "date_pause_seconds": 1.0, "edge_trim_threshold": 0.001,
                "wav": str(wav)}
    (OUTPUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    (OUTPUT / "spoken-text.txt").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    print(json.dumps({"wav": str(wav), "duration_seconds": metadata["duration_seconds"],
                      "slot_seconds": metadata["original_slot_seconds"],
                      "parts": len(parts)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
