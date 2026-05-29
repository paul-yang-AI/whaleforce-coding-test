"""One-off: inspect Citi extraction and regenerate gold boundaries."""
from __future__ import annotations

import json
from pathlib import Path

from task2_sec.pipeline.fetch import fetch_filing_html
from task2_sec.pipeline.run import extract_from_html

GOLD_DIR = Path(__file__).resolve().parents[1] / "task2_sec" / "eval" / "gold"
MANIFEST = Path(__file__).resolve().parents[1] / "task2_sec" / "eval" / "manifest.json"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    train = [f for f in manifest["filings"] if f.get("split") == "train"]

    for filing in train:
        accession = filing["accession"]
        html, _, _ = fetch_filing_html(accession)
        extraction = extract_from_html(
            html, accession=accession, use_arbiter=False, use_llm_fallback=False
        )
        gold_items: dict = {}
        for item in extraction.items:
            entry: dict = {
                "status": item.status.value,
                "confidence": item.confidence,
                "text_len": len(item.text or ""),
            }
            if item.start is not None and item.end is not None:
                entry["start"] = item.start
                entry["end"] = item.end
            gold_items[item.item_id] = entry

        out = {"items": gold_items}
        path = GOLD_DIR / f"{accession}.json"
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        print(f"Updated gold: {filing['ticker']} {accession}")

    # Spot-check Citi 7A
    citi = next(f for f in train if f["ticker"] == "C")
    html, _, _ = fetch_filing_html(citi["accession"])
    r = extract_from_html(
        html, accession=citi["accession"], use_arbiter=False, use_llm_fallback=False
    )
    item7a = next(i for i in r.items if i.item_id == "7A")
    preview = (item7a.text or "")[:160].replace("\n", " ")
    print(f"Citi 7A len={len(item7a.text or '')} start={item7a.start} preview={preview!r}")


if __name__ == "__main__":
    main()
