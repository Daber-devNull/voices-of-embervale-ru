"""Stage beta 0.1.2 with revised speech for all 134 numbered pages."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "local/ru_voice_separate_525"
REVISED = PROJECT / "local/numeric-pages-001"
DEST = PROJECT / "local/ru_voice_separate_525_numeric"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if DEST.exists():
        raise FileExistsError(DEST)
    catalog = json.loads((PROJECT / "local/journal-voice-catalog-001.json").read_text(encoding="utf-8"))["entries"]
    selected = [e for e in catalog if re.search(r"\d", e["title"] + e["body"])]
    if len(selected) != 134:
        raise ValueError("Expected exactly 134 pages with numeric text")
    source_manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    by_name = {x["name"]: x for x in source_manifest["entries"]}
    if len(by_name) != 525:
        raise ValueError("Expected 525 source entries")
    for entry in selected:
        old = by_name[entry["sound_name"]]
        candidate = REVISED / f"{entry['sound_index']:05d}" / "russian.frameless-qoa.bin"
        if not candidate.is_file() or candidate.stat().st_size != old["bytes"]:
            raise ValueError(f"Missing or wrong-sized audio: {candidate}")
        if not (REVISED / f"{entry['sound_index']:05d}" / "encoding.json").is_file():
            raise ValueError(f"Missing encoding report: {candidate}")
    shutil.copytree(SOURCE, DEST)
    for entry in selected:
        item = by_name[entry["sound_name"]]
        candidate = REVISED / f"{entry['sound_index']:05d}" / "russian.frameless-qoa.bin"
        target = DEST / "audio" / item["audio"]
        shutil.copy2(candidate, target)
        item["sha256"] = sha(target)
    (DEST / "manifest.json").write_text(json.dumps(source_manifest, ensure_ascii=False, indent=2)+"\n",
                                          encoding="utf-8")
    mod = json.loads((DEST / "mod.json").read_text(encoding="utf-8"))
    mod["version"] = "0.1.2"
    mod["name"] = "Русская озвучка — 525 страниц (числа исправлены)"
    (DEST / "mod.json").write_text(json.dumps(mod, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    expected = {e["sound_name"] for e in selected}
    unchanged = [x for x in source_manifest["entries"] if x["name"] not in expected]
    if len(unchanged) != 391 or any(sha(DEST / "audio" / x["audio"]) != x["sha256"] for x in unchanged):
        raise ValueError("Unnumbered recordings unexpectedly changed")
    print(json.dumps({"total": 525, "revised": 134, "unchanged": 391, "mod": str(DEST)}))


if __name__ == "__main__":
    main()
