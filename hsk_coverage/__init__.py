# -*- coding: utf-8 -*-
"""
HSK Coverage Map — visualize how much of the HSK vocabulary your deck covers.

Word data: data/complete.json (stored as-is). Levels:
  old-1..6      HSK 2.0 (2012)
  new-1..7      HSK 3.0 (2021), 7 = bands 7-9
  newest-1..7   HSK 3.0 (2025), 7 = bands 7-9

Tools ▸ HSK Coverage Map
"""

import json
import os
import re
import html as html_mod
from collections import defaultdict

from aqt import mw
from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QLabel,
    QPushButton, qconnect,
)
from aqt.webview import AnkiWebView
from aqt.theme import theme_manager

ADDON_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(ADDON_DIR, "data", "complete.json")

VERSIONS = [
    ("old", "HSK 2.0 (2012)", 6),
    ("new", "HSK 3.0 (2021)", 7),
    ("newest", "HSK 3.0 (2025)", 7),
]
VERSION_MAX = {k: mx for k, _l, mx in VERSIONS}

LEVEL_COLORS = {
    1: "#34d399",  # green
    2: "#38bdf8",  # sky
    3: "#a78bfa",  # violet
    4: "#fbbf24",  # amber
    5: "#fb7185",  # rose
    6: "#f97316",  # orange
    7: "#6366f1",  # indigo (HSK 7-9)
}

def level_label(lvl: int) -> str:
    return "HSK 7–9" if lvl == 7 else "HSK %d" % lvl


_TAG_RE = re.compile(r"<[^>]+>")
_SOUND_RE = re.compile(r"\[sound:[^\]]+\]")
_BRACKET_RE = re.compile(r"[\(\（\[【].*?[\)\）\]】]")
_NON_HAN_RE = re.compile(r"[^\u3400-\u9fff\u3007]")


def _clean(text: str) -> str:
    text = _SOUND_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = html_mod.unescape(text)
    return text.strip()


def _hanzi_only(text: str) -> str:
    return _NON_HAN_RE.sub("", _BRACKET_RE.sub("", text))


def _chunks(seq, n=4000):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------------- vocab data

class Vocab:
    """Parsed view of complete.json.

    levels[version][lvl] -> list of simplified words, most frequent first
    words[simplified]    -> {forms, trad, freq, pos, levels}
    """

    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        self.words = {}
        self.levels = {v: {l: [] for l in range(1, mx + 1)}
                       for v, _lbl, mx in VERSIONS}
        seen = {v: {l: set() for l in range(1, mx + 1)}
                for v, _lbl, mx in VERSIONS}

        for e in raw:
            s = e.get("simplified", "").strip()
            if not s:
                continue
            info = self.words.setdefault(s, {
                "forms": [], "_fkeys": set(), "trad": [],
                "freq": 10 ** 9, "pos": set(), "levels": set(),
            })
            freq = e.get("frequency")
            if isinstance(freq, (int, float)):
                info["freq"] = min(info["freq"], freq)
            info["pos"] |= set(e.get("pos") or [])
            for form in e.get("forms") or []:
                t = (form.get("traditional") or "").strip()
                py = (form.get("transcriptions") or {}).get("pinyin", "")
                meanings = form.get("meanings") or []
                key = (t, py)
                if key in info["_fkeys"]:
                    continue
                info["_fkeys"].add(key)
                info["forms"].append({"t": t, "p": py, "m": meanings})
                if t and t != s and t not in info["trad"]:
                    info["trad"].append(t)
            for tag in e.get("level") or []:
                try:
                    ver, num = tag.split("-")
                    num = int(num)
                except ValueError:
                    continue
                if ver in self.levels and num in self.levels[ver]:
                    info["levels"].add(tag)
                    if s not in seen[ver][num]:
                        seen[ver][num].add(s)
                        self.levels[ver][num].append(s)

        for ver in self.levels:
            for lvl in self.levels[ver]:
                self.levels[ver][lvl].sort(key=lambda w: self.words[w]["freq"])

    def aliases(self, word):
        return [word] + self.words[word]["trad"]


_vocab = None

def get_vocab():
    global _vocab
    if _vocab is None:
        _vocab = Vocab(DATA_PATH)
    return _vocab


# ---------------------------------------------------------------- deck scan

def _deck_query(deck_name):
    try:
        from anki.collection import SearchNode
        return mw.col.build_search_string(SearchNode(deck=deck_name))
    except Exception:
        return 'deck:"%s"' % deck_name.replace('"', '\\"')


def deck_field_names(deck_name):
    """Union of field names of note types that occur in this deck."""
    col = mw.col
    nids = col.find_notes(_deck_query(deck_name))
    mids = set()
    for chunk in _chunks(nids):
        ph = ",".join("?" * len(chunk))
        mids.update(r[0] for r in col.db.all(
            "select distinct mid from notes where id in (%s)" % ph, *chunk))
    names = []
    for mid in mids:
        model = col.models.get(mid)
        if not model:
            continue
        for fld in model["flds"]:
            if fld["name"] not in names:
                names.append(fld["name"])
    return names


def scan_deck(deck_name, field_name):
    """Match against a single chosen field.

    Returns (field_map, reviewed_nids):
      field_map     cleaned field value -> set of note ids
                    (plus a hanzi-only variant, so `爱 (ài)` matches 爱)
      reviewed_nids note ids with at least one reviewed card in this deck
    """
    col = mw.col
    query = _deck_query(deck_name)

    field_idx = {}  # mid -> index of chosen field, or None

    def idx_for(mid):
        if mid not in field_idx:
            model = col.models.get(mid)
            pos = None
            if model:
                for i, fld in enumerate(model["flds"]):
                    if fld["name"] == field_name:
                        pos = i
                        break
            field_idx[mid] = pos
        return field_idx[mid]

    field_map = defaultdict(set)
    nids = col.find_notes(query)
    for chunk in _chunks(nids):
        ph = ",".join("?" * len(chunk))
        for nid, mid, flds in col.db.all(
                "select id, mid, flds from notes where id in (%s)" % ph, *chunk):
            pos = idx_for(mid)
            if pos is None:
                continue
            parts = flds.split("\x1f")
            if pos >= len(parts):
                continue
            txt = _clean(parts[pos])
            if not txt:
                continue
            field_map[txt].add(nid)
            hz = _hanzi_only(txt)
            if hz and hz != txt:
                field_map[hz].add(nid)

    reviewed = set()
    cids = col.find_cards(query)
    for chunk in _chunks(cids):
        ph = ",".join("?" * len(chunk))
        for nid, max_reps in col.db.all(
                "select nid, max(reps) from cards where id in (%s) group by nid"
                % ph, *chunk):
            if max_reps and max_reps > 0:
                reviewed.add(nid)
    return field_map, reviewed


# ---------------------------------------------------------------- html

CSS = """
:root {
  --bg:#fafaf9; --panel:#ffffff; --border:#e7e5e4; --text:#1c1917;
  --muted:#78716c; --tile:#ebe9e8; --tiletext:#57534e; --overlay:#00000073;
}
body.night {
  --bg:#171717; --panel:#1f1f1f; --border:#343434; --text:#f5f5f4;
  --muted:#a8a29e; --tile:#2c2c2c; --tiletext:#9c9894; --overlay:#000000a8;
}
* { box-sizing:border-box; }
body { margin:0; padding:18px; background:var(--bg); color:var(--text);
  font-family:-apple-system,"Segoe UI","Helvetica Neue","PingFang SC",
  "Hiragino Sans GB","Microsoft YaHei",sans-serif; }
.summary { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
  margin:0 2px 14px 2px; }
.summary .big { font-size:30px; font-weight:700; letter-spacing:-0.5px; }
.summary .sub { color:var(--muted); font-size:13px; }
.board { display:grid; gap:12px; align-items:start;
  grid-template-columns:repeat(auto-fill, minmax(430px, 1fr)); }
@media (max-width: 480px) { .board { grid-template-columns:1fr; } }
.panel { background:var(--panel); border:1px solid var(--border);
  border-radius:12px; padding:12px 14px 14px 14px; min-width:0; }
.panel-head { display:flex; align-items:baseline; gap:10px; margin-bottom:4px; }
.lvl { font-weight:700; font-size:13px; letter-spacing:0.04em; color:var(--c); }
.pct { font-size:12px; font-weight:700; color:var(--c);
  font-variant-numeric:tabular-nums; }
.stat { color:var(--muted); font-size:11.5px; margin-left:auto;
  font-variant-numeric:tabular-nums; }
.bar { height:3px; border-radius:2px; background:var(--tile);
  margin:6px 0 10px 0; display:flex; overflow:hidden; }
.bar .r { background:var(--c); }
.bar .d { background:var(--c); opacity:0.35; }
.tiles { display:flex; flex-wrap:wrap; gap:4px; }
.t { font-size:12px; line-height:1; padding:4px 5px; border-radius:5px;
  cursor:pointer; white-space:nowrap; position:relative;
  border:1.5px solid transparent;
  transition:transform .16s cubic-bezier(.2,.8,.3,1.2); }
.t:hover { transform:scale(1.55); z-index:6; }
.t.st-r { background:var(--c); color:#fff; }
.t.st-d { background:var(--panel); color:var(--text); border-color:var(--c); }
.t.st-a { background:var(--tile); color:var(--tiletext); }
.legend { display:flex; gap:16px; align-items:center; flex-wrap:wrap;
  margin-top:14px; color:var(--muted); font-size:12px; }
.legend .t { cursor:default; --c:#94a3b8; }
.legend .t:hover { transform:none; }

/* info modal */
#ov { position:fixed; inset:0; background:var(--overlay); display:none;
  align-items:center; justify-content:center; z-index:50; }
#ov.show { display:flex; }
#card { background:var(--panel); border:1px solid var(--border);
  border-radius:14px; padding:22px 26px; max-width:440px; width:88%;
  max-height:80%; overflow-y:auto; box-shadow:0 18px 50px #00000055; }
#card .hz { font-size:46px; line-height:1.15; margin-bottom:2px; }
#card .py { font-size:17px; color:var(--c,#888); font-weight:600;
  margin-bottom:2px; }
#card .trad { color:var(--muted); font-size:13px; margin-bottom:8px; }
#card ul { margin:6px 0 10px 0; padding-left:20px; font-size:13.5px; }
#card li { margin:2px 0; }
#card .badges { display:flex; gap:6px; flex-wrap:wrap; margin:10px 0 4px 0; }
#card .badge { font-size:11px; font-weight:600; padding:3px 8px;
  border-radius:99px; background:var(--tile); color:var(--muted); }
#card .badge.lv { color:#fff; }
#card .status { font-size:12.5px; color:var(--muted); margin-top:8px; }
#card .btns { display:flex; gap:8px; margin-top:14px; }
#card button { border:1px solid var(--border); background:var(--tile);
  color:var(--text); font-size:12.5px; padding:6px 12px; border-radius:8px;
  cursor:pointer; }
#card button.primary { background:var(--c,#555); border-color:transparent;
  color:#fff; }
#card .formsep { border:0; border-top:1px solid var(--border); margin:10px 0; }
"""

JS = r"""
var LEVEL_COLORS = %(colors)s;
var VER_LABELS = {"old":"HSK 2.0","new":"HSK 3.0 (2021)","newest":"HSK 3.0 (2025)"};
document.addEventListener('click', function(e){
  var t = e.target.closest('.t[data-w]');
  if (t) { pycmd('hskinfo:' + t.dataset.w, showInfo); return; }
  if (e.target.id === 'ov') hideInfo();
});
document.addEventListener('keydown', function(e){
  if (e.key === 'Escape') hideInfo();
});
function esc(s){ var d=document.createElement('div'); d.textContent=s;
  return d.innerHTML; }
function hideInfo(){ document.getElementById('ov').classList.remove('show'); }
function showInfo(raw){
  var d = (typeof raw === 'string') ? JSON.parse(raw) : raw;
  var c = document.getElementById('card');
  c.style.setProperty('--c', d.color);
  var h = '<div class="hz">' + esc(d.word) + '</div>';
  d.forms.forEach(function(f, i){
    if (i > 0) h += '<hr class="formsep">';
    h += '<div class="py">' + esc(f.p) + '</div>';
    if (f.t && f.t !== d.word)
      h += '<div class="trad">traditional: ' + esc(f.t) + '</div>';
    if (f.m.length){
      h += '<ul>';
      f.m.forEach(function(m){ h += '<li>' + esc(m) + '</li>'; });
      h += '</ul>';
    }
  });
  h += '<div class="badges">';
  d.levels.forEach(function(lv){
    var parts = lv.split('-'); var n = parseInt(parts[1]);
    var col = LEVEL_COLORS[n] || '#888';
    var name = (n === 7 ? '7–9' : n);
    h += '<span class="badge lv" style="background:' + col + '">' +
         VER_LABELS[parts[0]] + ' · ' + name + '</span>';
  });
  h += '</div>';
  h += '<div class="status">' + esc(d.status_text) + '</div>';
  h += '<div class="btns">';
  if (d.in_deck)
    h += '<button class="primary" onclick="pycmd(\'hskfind:' +
         esc(d.word) + '\')">Open in browser</button>';
  h += '<button onclick="hideInfo()">Close</button></div>';
  c.innerHTML = h;
  document.getElementById('ov').classList.add('show');
}
"""


def _panel_html(lvl, words, status):
    color = LEVEL_COLORS[lvl]
    n = len(words)
    reviewed = sum(1 for w in words if status.get(w) == 2)
    indeck = sum(1 for w in words if status.get(w) == 1)
    covered = reviewed + indeck
    pct = 100.0 * covered / n if n else 0.0
    tiles = []
    for w in words:
        st = status.get(w, 0)
        cls = ("st-r", "st-d")[st == 1] if st else "st-a"
        we = html_mod.escape(w, quote=True)
        tiles.append('<span class="t %s" data-w="%s">%s</span>'
                     % (cls, we, html_mod.escape(w)))
    return """
<div class="panel" style="--c:%s">
  <div class="panel-head">
    <span class="lvl">%s</span>
    <span class="pct">%.0f%%</span>
    <span class="stat">%d reviewed · %d unreviewed · %d missing</span>
  </div>
  <div class="bar">
    <div class="r" style="width:%.2f%%"></div>
    <div class="d" style="width:%.2f%%"></div>
  </div>
  <div class="tiles">%s</div>
</div>""" % (
        color, level_label(lvl), pct,
        reviewed, indeck, n - covered,
        100.0 * reviewed / n if n else 0,
        100.0 * indeck / n if n else 0,
        "".join(tiles),
    )


def build_html(levels_words, status, version_label, deck_name, field_name,
               night=False):
    total = sum(len(v) for v in levels_words.values())
    reviewed = sum(1 for ws in levels_words.values()
                   for w in ws if status.get(w) == 2)
    indeck = sum(1 for ws in levels_words.values()
                 for w in ws if status.get(w) == 1)
    covered = reviewed + indeck
    pct = 100.0 * covered / total if total else 0.0

    panels = "".join(_panel_html(lvl, ws, status)
                     for lvl, ws in sorted(levels_words.items()))
    js = JS % {"colors": json.dumps(LEVEL_COLORS)}

    return """<!doctype html><html><head><meta charset="utf-8">
<style>%s</style></head>
<body class="%s">
  <div class="summary">
    <span class="big">%.1f%%</span>
    <span class="sub"><b>%d</b> of <b>%d</b> %s words in <b>%s</b>
      (%d reviewed) · matching field “%s”</span>
  </div>
  <div class="board">%s</div>
  <div class="legend">
    <span><span class="t st-r" style="background:#94a3b8;color:#fff">爱</span>
      in deck, reviewed</span>
    <span><span class="t st-d" style="border-color:#94a3b8">爱</span>
      in deck, not yet reviewed</span>
    <span><span class="t st-a">爱</span> not in deck</span>
    <span>hover to zoom · click for details</span>
  </div>
  <div id="ov"><div id="card"></div></div>
  <script>%s</script>
</body></html>""" % (
        CSS, "night" if night else "",
        pct, covered, total,
        html_mod.escape(version_label), html_mod.escape(deck_name),
        reviewed, html_mod.escape(field_name),
        panels, js,
    )


# ---------------------------------------------------------------- dialog

class HSKCoverageDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("HSK Coverage Map")
        self.resize(1250, 860)
        self.vocab = get_vocab()
        self._scan_cache = {}  # (deck, field) -> (field_map, reviewed)
        self._loading = True

        cfg = mw.addonManager.getConfig(__name__) or {}

        top = QHBoxLayout()
        top.addWidget(QLabel("Deck:"))
        self.deck_box = QComboBox()
        names = sorted(d.name for d in mw.col.decks.all_names_and_ids())
        self.deck_box.addItems(names)
        if cfg.get("deck") in names:
            self.deck_box.setCurrentText(cfg["deck"])
        self.deck_box.setMinimumWidth(220)
        top.addWidget(self.deck_box)

        top.addSpacing(10)
        top.addWidget(QLabel("Field:"))
        self.field_box = QComboBox()
        self.field_box.setMinimumWidth(150)
        top.addWidget(self.field_box)

        top.addSpacing(10)
        top.addWidget(QLabel("Word list:"))
        self.ver_box = QComboBox()
        for key, label, _mx in VERSIONS:
            self.ver_box.addItem(label, key)
        idx = self.ver_box.findData(cfg.get("version", "newest"))
        if idx >= 0:
            self.ver_box.setCurrentIndex(idx)
        top.addWidget(self.ver_box)

        top.addSpacing(10)
        self.chk79 = QCheckBox("Include HSK 7–9")
        self.chk79.setChecked(bool(cfg.get("include79", False)))
        top.addWidget(self.chk79)

        top.addStretch()
        refresh = QPushButton("Rescan deck")
        qconnect(refresh.clicked, self.rescan)
        top.addWidget(refresh)

        self.web = AnkiWebView(self)
        self.web.set_bridge_command(self.on_bridge, self)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.web)

        self._preferred_field = cfg.get("field", "")
        self.populate_fields()
        self._loading = False

        qconnect(self.deck_box.currentIndexChanged, self.on_deck_changed)
        qconnect(self.field_box.currentIndexChanged, self.render)
        qconnect(self.ver_box.currentIndexChanged, self.on_version_changed)
        qconnect(self.chk79.stateChanged, self.render)

        self.on_version_changed()

    # -- ui state

    def populate_fields(self):
        deck = self.deck_box.currentText()
        current = self.field_box.currentText() or self._preferred_field
        self.field_box.blockSignals(True)
        self.field_box.clear()
        names = deck_field_names(deck) if deck else []
        self.field_box.addItems(names)
        if current in names:
            self.field_box.setCurrentText(current)
        self.field_box.blockSignals(False)

    def on_deck_changed(self, *_):
        self.populate_fields()
        self.render()

    def on_version_changed(self, *_):
        ver = self.ver_box.currentData()
        has79 = VERSION_MAX.get(ver, 6) >= 7
        self.chk79.setEnabled(has79)
        self.chk79.setToolTip(
            "" if has79 else "HSK 2.0 has no bands 7–9")
        self.render()

    def rescan(self):
        deck = self.deck_box.currentText()
        for key in [k for k in self._scan_cache if k[0] == deck]:
            del self._scan_cache[key]
        self.populate_fields()
        self.render()

    # -- bridge

    def on_bridge(self, cmd):
        if cmd.startswith("hskinfo:"):
            return self.word_info(cmd[len("hskinfo:"):])
        if cmd.startswith("hskfind:"):
            word = cmd[len("hskfind:"):]
            deck = self.deck_box.currentText()
            from aqt import dialogs
            browser = dialogs.open("Browser", mw)
            browser.search_for('deck:"%s" "%s"' % (deck, word))
        return None

    def word_info(self, word):
        info = self.vocab.words.get(word)
        if not info:
            return json.dumps({"word": word, "forms": [], "levels": [],
                               "in_deck": False, "status_text": "",
                               "color": "#888"})
        status = self._status_for(word)
        ver = self.ver_box.currentData()
        my_levels = sorted(t for t in info["levels"] if t.startswith(ver + "-"))
        other = sorted(t for t in info["levels"] if not t.startswith(ver + "-"))
        lvl_num = int(my_levels[0].split("-")[1]) if my_levels else 0
        status_text = {
            2: "In your deck — reviewed.",
            1: "In your deck — not reviewed yet.",
            0: "Not in your deck.",
        }[status]
        return json.dumps({
            "word": word,
            "forms": info["forms"],
            "levels": my_levels + other,
            "in_deck": status > 0,
            "status_text": status_text,
            "color": LEVEL_COLORS.get(lvl_num, "#888"),
        })

    # -- scanning / status

    def _scan(self):
        deck = self.deck_box.currentText()
        field = self.field_box.currentText()
        key = (deck, field)
        if key not in self._scan_cache:
            self._scan_cache[key] = scan_deck(deck, field)
        return self._scan_cache[key]

    def _status_for(self, word):
        field_map, reviewed = self._scan()
        nids = set()
        for alias in self.vocab.aliases(word):
            nids |= field_map.get(alias, set())
        if not nids:
            return 0
        return 2 if nids & reviewed else 1

    # -- render

    def render(self, *_):
        if self._loading:
            return
        deck = self.deck_box.currentText()
        field = self.field_box.currentText()
        ver = self.ver_box.currentData()
        if not deck or not field:
            self.web.setHtml(
                "<html><body style='font-family:sans-serif;padding:30px;"
                "color:#888'>Select a deck with notes, then pick the field "
                "containing the Chinese word.</body></html>")
            return

        max_lvl = VERSION_MAX[ver]
        top = 7 if (max_lvl >= 7 and self.chk79.isChecked()) else 6
        levels_words = {lvl: self.vocab.levels[ver][lvl]
                        for lvl in range(1, top + 1)
                        if lvl in self.vocab.levels[ver]}

        field_map, reviewed = self._scan()
        status = {}
        for ws in levels_words.values():
            for w in ws:
                if w in status:
                    continue
                nids = set()
                for alias in self.vocab.aliases(w):
                    nids |= field_map.get(alias, set())
                status[w] = 0 if not nids else (2 if nids & reviewed else 1)

        page = build_html(levels_words, status, self.ver_box.currentText(),
                          deck, field, night=theme_manager.night_mode)
        self.web.setHtml(page)

        mw.addonManager.writeConfig(__name__, {
            "deck": deck, "field": field, "version": ver,
            "include79": self.chk79.isChecked(),
        })


# ---------------------------------------------------------------- menu

_dialog = None

def show_dialog():
    global _dialog
    _dialog = HSKCoverageDialog(mw)
    _dialog.show()

def setup_menu():
    from aqt.qt import QAction
    action = QAction("HSK Coverage Map", mw)
    qconnect(action.triggered, show_dialog)
    mw.form.menuTools.addAction(action)

setup_menu()
