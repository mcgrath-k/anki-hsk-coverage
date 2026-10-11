# -*- coding: utf-8 -*-
"""Word data for the HSK Coverage Map.

Source of truth for level membership and counts: the per-level text files in
  data/HSK2.0/HSK2.0_words_level{1..6}.txt
  data/HSK3.0/HSK3.0_words_level{1..6,7-9}.txt
  data/HSK3.1/HSK3.1_words_level{1..6,7-9}.txt
Each file lists the words *new* at that level, one entry per line.

The dictionary (pinyin, meanings, traditional forms for matching
traditional-character decks) is CC-CEDICT, downloaded once from MDBG into
user_files/ the first time the add-on runs and parsed on demand. Only the
entries for HSK words are kept in memory. CC-CEDICT is licensed CC BY-SA 4.0.

Entry syntax found in the lists:
  爸爸|爸        variants — either form counts
  好（不）容易   optional insertion — 好容易 or 好不容易
  第（第二）     usage example — the word is 第
  喂（叹词）     part-of-speech disambiguation — the word is 喂
  …极了          pattern — matched with the ellipsis stripped
  称1 / 称2      homograph index — the word is 称
"""

import gzip
import json
import math
import os
import re
import zipfile

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
USER_FILES = os.path.join(os.path.dirname(__file__), "user_files")
CEDICT_URL = ("https://www.mdbg.net/chinese/export/cedict/"
              "cedict_1_0_ts_utf-8_mdbg.txt.gz")
CEDICT_PATH = os.path.join(USER_FILES, "cedict.txt.gz")
# SUBTLEX-CH word frequencies (Cai & Brysbaert 2010, PLoS ONE; film/TV
# subtitles, 33.5 M words) — the word-frequency file, not the character one
SUBTLEX_URL = ("https://www.ugent.be/pp/experimentele-psychologie/en/"
               "research/documents/subtlexch/subtlexchwf.zip")
SUBTLEX_PATH = os.path.join(USER_FILES, "subtlex-ch-wf.zip")
# BCC corpus (BLCU; Xun et al. 2016) literature channel, by word
BCC_URL = ("https://bcc.blcu.edu.cn/api/datasets/"
           "literature_word_freq.txt/download")
BCC_PATH = os.path.join(USER_FILES, "bcc-literature-word-freq.zip")
# one-time downloads on first launch: (label, url, path)
DOWNLOADS = [
    ("CC-CEDICT dictionary (~4 MB)", CEDICT_URL, CEDICT_PATH),
    ("SUBTLEX-CH subtitle word frequencies (~4 MB)", SUBTLEX_URL,
     SUBTLEX_PATH),
    ("BCC literature word frequencies (~1 MB)", BCC_URL, BCC_PATH),
]

# (key, label, data folder, level-file suffixes)
VERSIONS = [
    ("old", "HSK 2.0 (2012)", "HSK2.0",
     ("1", "2", "3", "4", "5", "6")),
    ("new", "HSK 3.0 (2021)", "HSK3.0",
     ("1", "2", "3", "4", "5", "6", "7-9")),
    ("newest", "HSK 3.0 (2025)", "HSK3.1",
     ("1", "2", "3", "4", "5", "6", "7-9")),
]
VERSION_MAX = {key: len(sfx) for key, _l, _f, sfx in VERSIONS}
VERSION_LABELS = {key: label for key, label, _f, _s in VERSIONS}

_PAREN_RE = re.compile(r"（([^）]*)）")
_POS_NOTES = {
    "名词", "动词", "形容词", "副词", "量词", "助词", "叹词", "介词",
    "助动词", "连词", "代词", "数词",
}


def _strip_marks(text, keep_ellipsis=False):
    """Remove homograph digits (称1) and, unless kept, ellipses."""
    text = re.sub(r"[0-9０-９]", "", text)
    if keep_ellipsis:
        return text.replace("……", "…")
    return text.replace("……", "").replace("…", "")


def parse_entry(raw):
    """One list line -> (display form, set of matchable variants).

    Variants have ellipses stripped, so a pattern entry like 因为……所以……
    matches a field whose hanzi-only text is 因为所以.
    """
    variants = set()
    display = None
    for part in raw.strip().split("|"):
        part = part.strip()
        if not part:
            continue
        insides = _PAREN_RE.findall(part)
        outer = _PAREN_RE.sub("", part)
        forms = {outer}
        if insides:
            if all(x in _POS_NOTES for x in insides):
                pass  # POS note: the word is the outer text
            elif len(insides) == 1 and outer and outer in insides[0]:
                pass  # usage example containing the headword
            else:
                # optional insertion: also match with the content kept
                forms.add(_PAREN_RE.sub(lambda m: m.group(1), part))
        for f in forms:
            stripped = _strip_marks(f)
            if stripped:
                variants.add(stripped)
        if display is None:
            display = _strip_marks(outer, keep_ellipsis=True) or part
    return display, variants


# ---------------------------------------------------------------- CC-CEDICT

def download(url, path, timeout=60, progress=None, cancelled=None):
    """Fetch url to path atomically (via a .part file). progress(done,
    total_or_None) is called after every chunk; cancelled() returning
    True aborts the transfer, in which case False is returned."""
    import urllib.request
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    req = urllib.request.Request(
        url, headers={"User-Agent": "anki-hsk-coverage-addon"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, \
            open(tmp, "wb") as f:
        total = resp.headers.get("Content-Length")
        total = int(total) if total and total.isdigit() else None
        done = 0
        while True:
            if cancelled and cancelled():
                f.close()
                os.remove(tmp)
                return False
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    os.replace(tmp, path)
    return True


def _zipf(per_million):
    """Zipf scale (log10 of frequency per billion words): 6 ≈ one word in
    a thousand, 3 ≈ one in a million."""
    return round(math.log10(per_million) + 3, 4)


def parse_subtlex(path, keep):
    """word -> Zipf from the SUBTLEX-CH-WF zip (GBK text: Word, WCount,
    W/million, ...), restricted to the words in keep."""
    with zipfile.ZipFile(path) as z:
        name = [n for n in z.namelist() if n.endswith("SUBTLEX-CH-WF")][0]
        text = z.read(name).decode("gbk", errors="replace")
    out = {}
    for line in text.splitlines():
        p = line.split("\t")
        if len(p) >= 3 and p[0] in keep:
            try:
                out[p[0]] = _zipf(float(p[2]))
            except ValueError:
                pass
    return out


def parse_bcc(path, keep):
    """word -> Zipf from a BCC download-center word list (zip holding a
    'token,count' CSV), restricted to the words in keep. Per-million
    rates come from the file's own token total."""
    with zipfile.ZipFile(path) as z:
        text = z.read(z.namelist()[0]).decode("utf-8", errors="replace")
    counts, total = {}, 0
    for line in text.splitlines():
        w, _, c = line.rpartition(",")
        try:
            c = int(c)
        except ValueError:
            continue
        total += c
        if w in keep:
            counts[w] = c
    if not total:
        return {}
    return {w: _zipf(c / total * 1e6) for w, c in counts.items()}


_TONE_MARKS = {
    "a": "āáǎà", "e": "ēéěè", "i": "īíǐì",
    "o": "ōóǒò", "u": "ūúǔù", "ü": "ǖǘǚǜ",
}
_SYL_RE = re.compile(r"^([A-Za-zü]+)([1-5])$")


def pinyin_marks(numbered):
    """CC-CEDICT numbered pinyin -> tone marks: 'ni3 hao3' -> 'nǐ hǎo'."""
    out = []
    for syl in numbered.replace("u:", "ü").replace("U:", "Ü").split():
        m = _SYL_RE.match(syl)
        if not m:
            out.append(syl)
            continue
        base, tone = m.group(1), int(m.group(2))
        if tone == 5:
            out.append(base)
            continue
        lower = base.lower()
        if "a" in lower:
            idx = lower.index("a")
        elif "e" in lower:
            idx = lower.index("e")
        elif "ou" in lower:
            idx = lower.index("o")
        else:
            idx = max(lower.rfind(v) for v in "iouü")
            if idx < 0:
                out.append(base)
                continue
        mark = _TONE_MARKS[lower[idx]][tone - 1]
        if base[idx].isupper():
            mark = mark.upper()
        out.append(base[:idx] + mark + base[idx + 1:])
    return " ".join(out)


_CEDICT_LINE = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.+)/\s*$")


def parse_cedict(path, keep):
    """Parse the gzipped CC-CEDICT file, keeping only simplified forms in
    `keep`. Returns {simplified: {"forms": [{t,p,m}...], "trad": [...]}}."""
    words = {}
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                continue
            m = _CEDICT_LINE.match(line)
            if not m:
                continue
            trad, simp, py, defs = m.groups()
            if simp not in keep:
                continue
            info = words.setdefault(simp, {"forms": [], "trad": []})
            meanings = [d for d in defs.split("/") if d]
            info["forms"].append(
                {"t": trad, "p": pinyin_marks(py), "m": meanings})
            if trad != simp and trad not in info["trad"]:
                info["trad"].append(trad)
    return words


class Vocab:
    """levels[version][lvl] -> list of tiles.

    A tile is {"w": display, "aliases": [...], "n": weight}. Duplicate
    surface forms within a level (e.g. 花（动词）+ 花（名词）) merge into
    one tile whose weight n is the number of official entries it stands
    for — so per-level totals always equal the official counts.

    Tiles are ordered single-character words first, then multi-character
    words, each group in official list order.

    words[simplified] -> {"forms": [{t,p,m}...], "trad": [...]}
    tags[display]     -> set of "version-level" strings across all lists
    """

    def __init__(self, data_dir=DATA_DIR, cedict_path=CEDICT_PATH):
        self._load_lists(data_dir)
        self._load_dictionary(cedict_path)
        self._finish_tiles()
        self._load_freq()

    def _load_freq(self):
        """Word -> Zipf frequency tables used by plan.py to order the study
        plan: freq_sub (film/TV subtitles, SUBTLEX-CH) and freq_book
        (novels and other literature, BCC), from the files fetched on
        first launch — empty if a download hasn't succeeded yet."""
        keep = self._needed | {w.replace("…", "") for w in self._needed}
        self.freq_sub = self._load_corpus(SUBTLEX_PATH, parse_subtlex, keep)
        self.freq_book = self._load_corpus(BCC_PATH, parse_bcc, keep)

    @staticmethod
    def _load_corpus(path, parser, keep):
        try:
            return parser(path, keep)
        except (OSError, ValueError, IndexError, zipfile.BadZipFile):
            return {}

    # -- word lists (txt files)

    def _load_lists(self, data_dir):
        self.levels = {}
        self.tags = {}
        self._needed = set()
        for key, _label, folder, suffixes in VERSIONS:
            self.levels[key] = {}
            for lvl, sfx in enumerate(suffixes, start=1):
                path = os.path.join(
                    data_dir, folder, "%s_words_level%s.txt" % (folder, sfx))
                tiles = {}   # display -> tile (insertion-ordered)
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        display, variants = parse_entry(line)
                        tile = tiles.get(display)
                        if tile is None:
                            tile = tiles[display] = {
                                "w": display, "_v": set(), "n": 0}
                            self.tags.setdefault(display, set()).add(
                                "%s-%d" % (key, lvl))
                        tile["_v"] |= variants
                        tile["n"] += 1
                        self._needed.add(display)
                        self._needed |= variants
                self.levels[key][lvl] = list(tiles.values())
        # keep dictionary entries for erhua bases too (面条 for 面条儿),
        # so the info card can show the base word's definition even when
        # the base itself is not an HSK entry
        for w in list(self._needed):
            if len(w) > 1 and w.endswith("儿"):
                self._needed.add(w[:-1])

    # -- dictionary (CC-CEDICT)

    def _load_dictionary(self, cedict_path):
        if cedict_path and os.path.exists(cedict_path):
            self.words = parse_cedict(cedict_path, self._needed)
        else:
            self.words = {}
        self.has_dictionary = bool(self.words)

    def _finish_tiles(self):
        for ver_levels in self.levels.values():
            for lvl, tiles in ver_levels.items():
                for i, tile in enumerate(tiles):
                    tile["aliases"] = self._aliases(tile.pop("_v"))
                    tile["_k"] = (len(tile["w"]) > 1, i)
                tiles.sort(key=lambda t: t.pop("_k"))

    def _aliases(self, variants):
        """Variants plus their traditional forms, for deck matching."""
        out = list(variants)
        for v in variants:
            info = self.words.get(v)
            if info:
                for t in info["trad"]:
                    if t not in out:
                        out.append(t)
        return out

    # -- lookups

    _ERHUA_RE = re.compile(
        r"erhua variant of (?:[^|\[\s]+\|)?([^|\[\s]+)\[")

    def erhua_bases(self, info):
        """Base-word entries referenced by "erhua variant of 麵條|面条[...]"
        meanings, as [{"word": simplified, "forms": [...]}, ...]."""
        bases = []
        seen = set()
        for form in info["forms"]:
            for meaning in form["m"]:
                m = self._ERHUA_RE.search(meaning)
                if not m or m.group(1) in seen:
                    continue
                seen.add(m.group(1))
                base = self.words.get(m.group(1))
                if base:
                    bases.append(
                        {"word": m.group(1), "forms": base["forms"]})
        return bases

    _XREF_RE = re.compile(
        r"^(?:(?:old |archaic )?variant of |see (?:also )?|used in |CL:"
        r"|surname )")

    def best_gloss(self, info):
        """(pinyin, meaning) for a one-line summary (study plan). CC-CEDICT
        often lists cross-references ("variant of 著[zhao1]") or minor
        senses ("surname Cong") first, so pick the reading with the most
        substantive meanings and take its first one."""
        if not info or not info["forms"]:
            return "", ""
        best = None   # (meaning count, pinyin, first meaning)
        for form in info["forms"]:
            good = [m for m in form["m"] if not self._XREF_RE.search(m)]
            if good and (best is None or len(good) > best[0]):
                best = (len(good), form["p"], good[0])
        if best:
            return best[1], best[2]
        form = info["forms"][0]
        return form["p"], form["m"][0] if form["m"] else ""

    def dict_info(self, display, aliases=()):
        """Dictionary entry for a tile, trying sensible fallbacks."""
        for cand in (display, display.replace("…", ""), *aliases):
            if cand in self.words:
                return cand, self.words[cand]
        return display, None

    def tags_for(self, display):
        return sorted(self.tags.get(display, ()))
