# -*- coding: utf-8 -*-
"""Study-order recommendations for the HSK Coverage Map (no Anki imports).

Ranks the words you don't know yet (status 0 — not in the deck, not marked
known) into a suggested study order, fully offline, from three signals:

  frequency   how common the word is in real Chinese (Zipf scale, from the
              shipped data/word_freq.json, derived from the wordfreq
              dataset, CC BY-SA)
  components  how many of the word's characters you already know from
              words you've covered — a word made of familiar characters
              is cheap to learn
  unlocks     how many other still-unknown HSK words share this word's
              characters — learning it pays forward

plus a mild earlier-level bonus as a tie-break.
"""

import bisect
import re

_HAN_RE = re.compile(r"[㐀-鿿]")

# score weights
W_FREQ, W_COMP, W_UNLOCK, W_LEVEL = 0.45, 0.25, 0.20, 0.10
ZIPF_CAP = 6.0      # zipf >= 6 counts as maximally common
UNLOCK_CAP = 12     # sharing chars with >= 12 unknown words maxes the term


def _chars(word):
    return set(_HAN_RE.findall(word))


def recommend(levels_tiles, status, freq, limit=100,
              mode="smart", by_level=False):
    """-> (items, total_unknown); items are dicts {w, lvl, score, reason}.

    mode "board":  the unknown words exactly as the board presents them —
                   level by level, single characters first, then official
                   list order. No scoring, no reasons.
    mode "smart":  weighted-score order (best first).
    mode "freq":   purely by corpus frequency (most common first).

    With by_level, smart/freq rankings are grouped strictly by ascending
    HSK level, keeping their order within each level.
    """
    max_lvl = max(levels_tiles) if levels_tiles else 1

    covered_chars = set()
    unknown = []   # (word, base, lvl)
    seen = set()   # a homograph entry recurs at a later level — list it once
    for lvl in sorted(levels_tiles):
        for t in levels_tiles[lvl]:
            base = t["w"].replace("…", "")
            if status.get(t["w"], 0) > 0:
                covered_chars |= _chars(base)
            elif t["w"] not in seen:
                seen.add(t["w"])
                unknown.append((t["w"], base, lvl))

    if mode == "board":
        items = [{"w": word, "lvl": lvl, "score": 0, "reason": ""}
                 for word, _base, lvl in unknown]
        return items[:limit], len(unknown)

    # how many unknown words each character appears in
    char_count = {}
    for _w, base, _lvl in unknown:
        for c in _chars(base):
            char_count[c] = char_count.get(c, 0) + 1

    items = []
    for word, base, lvl in unknown:
        chars = _chars(base)
        if not chars:
            continue
        zipf = freq.get(base, 0.0)
        freq_n = min(zipf, ZIPF_CAP) / ZIPF_CAP
        known = [c for c in base if c in covered_chars]  # in word order
        comp_n = len(set(known)) / len(chars)
        unlocks = sum(char_count.get(c, 1) - 1 for c in chars)
        unlock_n = min(unlocks, UNLOCK_CAP) / UNLOCK_CAP
        level_n = (max_lvl - lvl + 1) / max_lvl
        score = (W_FREQ * freq_n + W_COMP * comp_n
                 + W_UNLOCK * unlock_n + W_LEVEL * level_n)

        freq_word = ("very common" if zipf >= 5 else
                     "common" if zipf >= 4 else
                     "fairly common" if zipf >= 3 else "")
        reason = [freq_word] if freq_word else []
        if len(chars) == 1:
            if known:
                reason.append("character appears in words you know")
        elif comp_n == 1:
            reason.append("you know every character")
        elif known:
            uniq = []
            for c in known:
                if c not in uniq:
                    uniq.append(c)
            reason.append("know %s" % "+".join(uniq))
        if unlocks >= 3:
            reason.append("shares characters with %d more words" % unlocks)
        items.append({
            "w": word, "lvl": lvl, "score": round(score, 4),
            "zipf": zipf, "reason": " · ".join(reason),
            "freq_reason": freq_word,
        })

    if mode == "freq":
        # frequency alone decides the order; the note shows the word's
        # rank among all HSK words so the ordering is verifiable — the
        # corpus data is binned at 0.01 zipf, so words sharing a rank
        # are exactly tied there (broken by earlier level, then text)
        asc = sorted(z for z in freq.values() if z > 0)
        n = len(asc)
        for it in items:
            z = it["zipf"]
            if z > 0:
                note = "#%d most common" % (
                    n - bisect.bisect_right(asc, z) + 1)
                if it["freq_reason"]:
                    note += " · " + it["freq_reason"]
            else:
                note = "no frequency data"
            it["reason"] = note
        if by_level:
            items.sort(key=lambda x: (x["lvl"], -x["zipf"], x["w"]))
        else:
            items.sort(key=lambda x: (-x["zipf"], x["lvl"], x["w"]))
    elif by_level:
        items.sort(key=lambda x: (x["lvl"], -x["score"], -x["zipf"], x["w"]))
    else:
        items.sort(key=lambda x: (-x["score"], -x["zipf"], x["w"]))
    for it in items:
        it.pop("zipf", None)
        it.pop("freq_reason", None)
    return items[:limit], len(unknown)
