# Prompt Iteration Log

Record v1→v2 changes with Failed Path / Resolution / Validation.

## boundary_arbiter: regex fallback negative samples

- **Failed Path**: Initial regex `ITEM\s+\d+` matched inline cross-references like
  "see Item 1 above" as segment headers, causing false boundary splits mid-paragraph.
- **Resolution**: Anchored `HEADER_RE` to line-start (`(?m)^[ \t]*`) in `segment.py`;
  added negative-sample assertions in `test_regex_boundary_fallback.py` to reject
  body-inline mentions. Longer item IDs match first (e.g. "10" before "1").
- **Validation**: `test_regex_boundary_fallback` green — negative sample
  `"see Item 1 above"` no longer produces a segment hit; `pytest -m unit` all pass.

## incorporation_by_reference: Citi Items 10–14

- **Failed Path**: Pipeline initially reported Items 10–14 as `extracted` with full text
  that was actually just a one-line incorporation notice, misleading eval metrics.
- **Resolution**: Added `detect_incorporation()` in `task2_sec/pipeline/incorporation.py`
  using regex to detect "incorporated by reference" language; status set to
  `incorporated_by_reference` with `text=None` to avoid hallucinating content.
- **Validation**: `test_item_status::test_incorporation_by_reference_no_fake_fulltext` green;
  `test_sec_manifest_citi_incorporation` confirms Items 10 and 14 correctly flagged.
