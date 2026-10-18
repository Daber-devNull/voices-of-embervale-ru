"""Export every securely mapped Russian NPC line for editorial review."""
from __future__ import annotations

import html
import json
from pathlib import Path
import re

PROJECT = Path(__file__).resolve().parents[1]
NAMES = {"Alchemist": "Алхимик", "Barber": "Парикмахер", "Bard": "Бард",
         "Blacksmith": "Кузнец", "Carpenter": "Плотник", "Farmer": "Фермер",
         "Huntress": "Охотница", "MeiYinChen": "Мэй Инь Чэнь",
         "LoraineCrim": "Лорейн Крим", "MelvilleFontane": "Мелвилл Фонтейн",
         "cryptKeeper": "Хранитель склепа"}


def clean(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    return html.unescape(re.sub(r"<[^>]+>", "", value)).replace("*", "").strip()


def main() -> None:
    direct = json.loads((PROJECT / "local/npc-voice-catalog-001.json").read_text(encoding="utf-8"))["entries"]
    variants = json.loads((PROJECT / "local/npc-variant-catalog-001.json").read_text(encoding="utf-8"))["entries"]
    rows = [(x["speaker_group"], x["loca_tag"], x["russian_text"], x["voiceover_guid"], 1)
            for x in direct if x["russian_text"]]
    rows += [(x["speaker_group"], x["loca_tag"], x["russian_text"], x["voiceover_guid"], len(x["variants"]))
             for x in variants]
    rows.sort(key=lambda x: (NAMES.get(x[0], x[0]), x[1]))
    lines = ["Реплики озвученных персонажей Enshrouded 1.0 — русская локализация", "",
             "294 реплики; 81 звуковой дубль для 24 реплик Лорейн Крим.", "Текст извлечён из ресурсов игры; озвучка использует вербализацию цифр.", ""]
    current = None
    for group, tag, value, voice, takes in rows:
        if group != current:
            lines.extend([NAMES.get(group, group), "=" * 48, ""])
            current = group
        lines.extend([f"[{tag}] {clean(value)}", f"Voiceover: {voice}" + (f" | вариантов звука: {takes}" if takes > 1 else ""), ""])
    out = PROJECT / "local/npc-dialogues-ru.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"dialogues": len(rows), "characters": len({x[0] for x in rows}), "file": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
