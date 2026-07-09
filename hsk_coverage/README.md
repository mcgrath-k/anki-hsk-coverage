# HSK Coverage Map (Anki add-on)

Visualizes how much of the HSK vocabulary your deck covers, as a responsive
grid of hanzi tiles.

## Word lists
All data comes from `data/complete.json` (stored as-is). Three versions:

- **HSK 2.0 (2012)** — levels 1–6 (`old-*`)
- **HSK 3.0 (2021)** — levels 1–6 + optional 7–9 (`new-*`)
- **HSK 3.0 (2025)** — levels 1–6 + optional 7–9 (`newest-*`)

Within each level, words are ordered by corpus frequency (most common first),
so coverage naturally clusters toward the top-left of each panel.
Polyphones that appear twice in a list (e.g. 得) are shown as one tile whose
detail view lists every reading.

## Tile states
- **Filled (level color, white text)** — word is in your deck *and* at least
  one of its cards has been reviewed.
- **Colored border, plain background** — in your deck, not reviewed yet.
- **Gray, muted text** — not in your deck.

Hover a tile to zoom it; click for a detail card with the character (large),
pinyin, traditional form, meanings, level badges, and an "Open in browser"
button that jumps to the note in Anki's browser.

## Matching
You choose the **field** the add-on matches against (e.g. "Hanzi",
"Simplified"). The field list is the union of fields across the note types
present in the selected deck (subdecks included). A word counts if the
chosen field equals it after stripping HTML, `[sound:…]` tags, and
bracketed annotations — so a field like `爱 (ài)` still matches 爱.
Traditional-character fields match too (愛 counts as 爱), via the
traditional forms in complete.json.

## Layout
Level panels (HSK 1 → 6, plus 7–9 when enabled) flow in a responsive grid:
wide windows show them side by side, narrow windows stack them, always in
level order.

## Install
Tools ▸ Add-ons ▸ Install from file… ▸ `hsk_coverage.ankiaddon`, restart
Anki, then open **Tools ▸ HSK Coverage Map**. Settings (deck, field,
version, 7–9) persist between sessions. Use **Rescan deck** after editing
notes. To update the word data, replace `data/complete.json` (same schema)
and restart Anki.

Requires Anki 2.1.50+.
