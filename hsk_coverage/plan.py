# -*- coding: utf-8 -*-
"""Study-order recommendations for the HSK Coverage Map (no Anki imports).

Lists the words you don't know yet (status 0 — not in the deck, not marked
known) in a suggested study order, fully offline:

  board      the order of the gray tiles on the board — level by level,
             single characters first, then official list order
  sub, book  by corpus frequency, most common first, from the table the
             caller passes in (Zipf scale): SUBTLEX-CH film/TV subtitles,
             or the BCC literature list — see vocab.py
"""

import bisect

# modes ordered purely by the frequency table the caller passes in
FREQ_MODES = ("sub", "book")


def recommend(levels_tiles, status, freq, limit=100,
              mode="board", by_level=False):
    """-> (items, total_unknown); items are dicts {w, lvl, reason}.

    With by_level, a frequency ranking is grouped strictly by ascending
    HSK level, keeping its order within each level.
    """
    unknown = []   # (word, base, lvl)
    seen = set()   # a homograph entry recurs at a later level — list it once
    for lvl in sorted(levels_tiles):
        for t in levels_tiles[lvl]:
            if status.get(t["w"], 0) == 0 and t["w"] not in seen:
                seen.add(t["w"])
                unknown.append((t["w"], t["w"].replace("…", ""), lvl))

    if mode not in FREQ_MODES:
        items = [{"w": word, "lvl": lvl, "reason": ""}
                 for word, _base, lvl in unknown]
        return items[:limit], len(unknown)

    # the note shows the word's rank among all HSK words in the table so
    # the ordering is verifiable; words sharing a rank are exactly tied
    # in the data (broken by earlier level, then text)
    asc = sorted(z for z in freq.values() if z > 0)
    n = len(asc)
    items = []
    for word, base, lvl in unknown:
        zipf = freq.get(base, 0.0)
        if zipf > 0:
            note = "rank #%d" % (n - bisect.bisect_right(asc, zipf) + 1)
            common = ("very common" if zipf >= 5 else
                      "common" if zipf >= 4 else
                      "fairly common" if zipf >= 3 else "")
            if common:
                note += ", " + common
        else:
            note = "no frequency data"
        items.append({"w": word, "lvl": lvl, "zipf": zipf, "reason": note})
    if by_level:
        items.sort(key=lambda x: (x["lvl"], -x["zipf"], x["w"]))
    else:
        items.sort(key=lambda x: (-x["zipf"], x["lvl"], x["w"]))
    for it in items:
        del it["zipf"]
    return items[:limit], len(unknown)
