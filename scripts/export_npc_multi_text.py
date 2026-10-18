"""Make a local review sheet of NPC greetings and farewells."""
from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    groups = json.loads((PROJECT / "local/npc-multi-catalog-001.json").read_text(encoding="utf-8"))["entries"]
    by_speaker = defaultdict(list)
    for group in groups:
        if group["loca_tag"] == 591080302:
            continue
        by_speaker[group["speaker_group"]].append(group)
    lines = ["Реплики персонажей — приветствия и прощания", "",
             "299 фраз с русским текстом; для каждой озвучены случайные варианты оригинальной дорожки.",
             "Ремарка Барда «(Напевает)» исключена: она делит дорожку с другой репликой.", ""]
    for speaker in sorted(by_speaker):
        lines += [f"## {speaker} — {len(by_speaker[speaker])}", ""]
        for index, group in enumerate(by_speaker[speaker], 1):
            lines += [f"{index}. {group['russian_text']}",
                      f"   loca_tag={group['loca_tag']} · дублей: {len(group['takes'])}", ""]
    target = PROJECT / "local/npc-greetings-ru.txt"
    target.write_text("\n".join(lines), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
