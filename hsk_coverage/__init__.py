# -*- coding: utf-8 -*-
"""
HSK Coverage Map — visualize how much of the HSK vocabulary your deck covers.

Level membership and counts come from the official per-level lists in
data/HSK2.0, data/HSK3.0 (2021) and data/HSK3.1 (2025). The dictionary for
the detail card is CC-CEDICT, downloaded once into user_files/ on first
run. Words you right-click as "known" persist in
user_files/known_words.json. See vocab.py.

Tools ▸ HSK Coverage Map
"""

import faulthandler
import json
import os
import re
import threading
import time
import traceback
import html as html_mod
from collections import defaultdict

from aqt import mw
from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QLabel,
    QPushButton, QShortcut, QKeySequence, QMenu, QFileDialog, QTimer,
    Qt, qconnect,
)
from aqt.webview import AnkiWebView
from aqt.theme import theme_manager

from .vocab import (
    Vocab, VERSIONS, VERSION_MAX, CEDICT_PATH, download_cedict,
)
from .render import LEVEL_COLORS, build_html, panel_stats, counts

KNOWN_PATH = os.path.join(
    os.path.dirname(__file__), "user_files", "known_words.json")
USER_FILES = os.path.dirname(KNOWN_PATH)
DEBUG_LOG = os.path.join(USER_FILES, "debug.log")


# ------------------------------------------------------------- diagnostics

_debug_fh = None

def _debug_file():
    """Append-mode handle to user_files/debug.log (rotated at ~2 MB)."""
    global _debug_fh
    if _debug_fh is None:
        os.makedirs(USER_FILES, exist_ok=True)
        try:
            if (os.path.exists(DEBUG_LOG)
                    and os.path.getsize(DEBUG_LOG) > 2_000_000):
                os.replace(DEBUG_LOG, DEBUG_LOG + ".1")
        except OSError:
            pass
        _debug_fh = open(DEBUG_LOG, "a", encoding="utf-8", buffering=1)
    return _debug_fh


def debug_line(msg):
    try:
        _debug_file().write(
            "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


class _Watchdog:
    """Freeze detector: a QTimer heartbeats on the Qt main thread; a
    background thread dumps every thread's stack into debug.log when the
    heartbeat stalls, so a hang leaves evidence of exactly where it is.
    (faulthandler.enable() at the bottom of this file covers hard crashes.)
    """

    STALL_SECS = 8.0

    def __init__(self):
        self._beat = time.monotonic()
        self._reported = False
        self._timer = QTimer(mw)
        qconnect(self._timer.timeout, self._on_beat)
        self._timer.start(500)
        threading.Thread(target=self._poll, daemon=True).start()

    def _on_beat(self):
        self._beat = time.monotonic()
        self._reported = False

    def _poll(self):
        while True:
            time.sleep(2.0)
            lag = time.monotonic() - self._beat
            if lag > self.STALL_SECS and not self._reported:
                self._reported = True
                try:
                    f = _debug_file()
                    f.write(
                        "\n==== %s main thread unresponsive for %.0fs — "
                        "dumping all stacks ====\n"
                        % (time.strftime("%Y-%m-%d %H:%M:%S"), lag))
                    faulthandler.dump_traceback(file=f, all_threads=True)
                    f.write("==== end of dump ====\n")
                except OSError:
                    pass


_watchdog = None

def start_watchdog():
    global _watchdog
    if _watchdog is None:
        _watchdog = _Watchdog()

_TAG_RE = re.compile(r"<[^>]+>")
_SOUND_RE = re.compile(r"\[sound:[^\]]+\]")
_BRACKET_RE = re.compile(r"[\(\（\[【].*?[\)\）\]】]")
_NON_HAN_RE = re.compile(r"[^㐀-鿿〇]")


def _clean(text):
    text = _SOUND_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = html_mod.unescape(text)
    return text.strip()


def _hanzi_only(text):
    return _NON_HAN_RE.sub("", _BRACKET_RE.sub("", text))


def _chunks(seq, n=4000):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


_vocab = None

def get_vocab():
    """Load word data, fetching CC-CEDICT once on first ever run."""
    global _vocab
    if _vocab is None:
        if not os.path.exists(CEDICT_PATH):
            from aqt.utils import tooltip
            mw.progress.start(
                label="Downloading CC-CEDICT dictionary (one time, ~4 MB)…",
                immediate=True)
            try:
                download_cedict()
            except Exception as e:
                tooltip(
                    "Dictionary download failed (%s) — definitions and "
                    "traditional-form matching are unavailable; will retry "
                    "next time the map is opened." % e, period=5000)
            finally:
                mw.progress.finish()
        _vocab = Vocab()
    return _vocab


# ------------------------------------------------------------ known words

def known_path():
    """The known-words file: user_files/known_words.json by default, or a
    user-chosen location (config "known_file", set via the settings menu)
    survives removing/reinstalling the add-on."""
    cfg = mw.addonManager.getConfig(__name__) or {}
    return cfg.get("known_file") or KNOWN_PATH


def load_known(path=None):
    try:
        with open(path or known_path(), encoding="utf-8") as f:
            return set(json.load(f).get("words", []))
    except (OSError, ValueError):
        return set()


def save_known(words, path=None):
    path = path or known_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": sorted(words)}, f, ensure_ascii=False, indent=1)


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


# ---------------------------------------------------------------- dialog

class HSKCoverageDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("HSK Coverage Map")
        self.resize(1250, 860)
        self.vocab = get_vocab()
        self.known = load_known()
        self._scan_cache = {}  # (deck, field) -> (field_map, reviewed)
        self._tile_index = {}  # display word -> tile (current version)
        self._alias_index = {}  # alias text -> [display words]
        self._last_levels = {}
        self._last_status = {}
        self._loading = True

        cfg = mw.addonManager.getConfig(__name__) or {}
        self.collapsed = cfg.get("collapsed") or {}

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
        for key, label, _folder, _sfx in VERSIONS:
            self.ver_box.addItem(label, key)
        idx = self.ver_box.findData(cfg.get("version", "newest"))
        if idx >= 0:
            self.ver_box.setCurrentIndex(idx)
        top.addWidget(self.ver_box)

        top.addSpacing(10)
        self.chk_known = QCheckBox("Include words marked known")
        self.chk_known.setChecked(bool(cfg.get("show_known", True)))
        self.chk_known.setToolTip(
            "Right-click a word on the map to mark it as one you already "
            "know without an Anki card. Uncheck to see only real deck "
            "coverage.")
        top.addWidget(self.chk_known)

        top.addStretch()
        refresh = QPushButton("Rescan deck")
        qconnect(refresh.clicked, self.rescan)
        top.addWidget(refresh)

        self._gear = QPushButton("Options")
        self._gear.setToolTip("Known-words database & debug files")
        qconnect(self._gear.clicked, self.open_settings_menu)
        top.addWidget(self._gear)

        self.web = AnkiWebView(self)
        self.web.set_bridge_command(self.on_bridge, self)
        # let the page handle right-clicks (mark-known) itself
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        # Cmd/Ctrl +, -, 0 scale the interface (also handled in-page, so
        # they work whether the webview or a control has focus)
        self._zoom = float(cfg.get("zoom", 1.0))
        self.web.setZoomFactor(self._zoom)
        for seq, fn in (("Ctrl+=", self.zoom_in), ("Ctrl++", self.zoom_in),
                        ("Ctrl+-", self.zoom_out), ("Ctrl+_", self.zoom_out),
                        ("Ctrl+0", self.zoom_reset)):
            sc = QShortcut(QKeySequence(seq), self)
            qconnect(sc.activated, fn)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.web)

        self._known_file = cfg.get("known_file") or ""
        self._preferred_field = cfg.get("field", "")
        self.populate_fields()
        self._loading = False

        qconnect(self.deck_box.currentIndexChanged, self.on_deck_changed)
        qconnect(self.field_box.currentIndexChanged, self.render)
        qconnect(self.ver_box.currentIndexChanged, self.render)
        qconnect(self.chk_known.stateChanged, self.on_known_toggle)

        # live-update the map when a note is added in the Add dialog —
        # event-driven (no polling), patched in place (no deck rescan)
        try:
            from aqt import gui_hooks
            gui_hooks.add_cards_did_add_note.append(self._on_note_added)
        except (ImportError, AttributeError):
            pass

        self.render()

    def closeEvent(self, evt):
        try:
            from aqt import gui_hooks
            gui_hooks.add_cards_did_add_note.remove(self._on_note_added)
        except (ImportError, AttributeError, ValueError):
            pass
        super().closeEvent(evt)

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

    def rescan(self):
        deck = self.deck_box.currentText()
        for key in [k for k in self._scan_cache if k[0] == deck]:
            del self._scan_cache[key]
        self.populate_fields()
        self.render()

    # -- settings menu

    def open_settings_menu(self):
        m = QMenu(self)
        info = m.addAction("Known words: %s" % known_path())
        info.setEnabled(False)
        qconnect(m.addAction("Show known-words file in folder").triggered,
                 self.reveal_known_file)
        qconnect(m.addAction("Use existing known-words file…").triggered,
                 self.pick_known_file)
        qconnect(m.addAction("Move known words to a new file…").triggered,
                 self.create_known_file)
        m.addSeparator()
        qconnect(m.addAction("Show debug log in folder").triggered,
                 lambda: self._reveal(DEBUG_LOG))
        m.exec(self._gear.mapToGlobal(self._gear.rect().bottomLeft()))

    def _reveal(self, path):
        folder = os.path.dirname(path)
        try:
            from aqt.utils import openFolder
            openFolder(folder)
        except Exception:
            from aqt.qt import QDesktopServices, QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def reveal_known_file(self):
        save_known(self.known)   # make sure the file exists before showing it
        self._reveal(known_path())

    def _set_known_file(self, path, load):
        path = os.path.abspath(path)
        self._known_file = (
            "" if path == os.path.abspath(KNOWN_PATH) else path)
        self.write_config()
        if load:
            self.known = load_known(path)
        else:
            save_known(self.known, path)
        debug_line("known-words file -> %s" % path)
        self.render()

    def pick_known_file(self):
        """Point the add-on at an existing known-words JSON (e.g. a backup
        kept outside the add-on folder) and load it."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Use existing known-words file",
            os.path.dirname(known_path()), "JSON files (*.json)")
        if path:
            self._set_known_file(path, load=True)

    def create_known_file(self):
        """Write the current known words to a new location and use it from
        now on — keeps the list safe across add-on removal/reinstall."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Move known words to", known_path(), "JSON files (*.json)")
        if path:
            self._set_known_file(path, load=False)

    def collapsed_levels(self, ver):
        default = [7] if VERSION_MAX[ver] >= 7 else []
        return set(self.collapsed.get(ver, default))

    # -- zoom

    def set_zoom(self, z):
        self._zoom = max(0.5, min(2.5, round(z, 2)))
        self.web.setZoomFactor(self._zoom)
        self.write_config()

    def zoom_in(self):
        self.set_zoom(self._zoom + 0.1)

    def zoom_out(self):
        self.set_zoom(self._zoom - 0.1)

    def zoom_reset(self):
        self.set_zoom(1.0)

    def on_known_toggle(self, *_):
        """Patch known-word tiles and header numbers in place — no page
        rebuild, so the board doesn't shift under the user."""
        if self._loading:
            return
        if not self._last_levels:
            self.render()
            return
        changed = []
        for word in self.known:
            tile = self._tile_index.get(word)
            if tile is None:
                continue
            st = self.effective_status(word, tile["aliases"])
            if self._last_status.get(word) != st:
                self._last_status[word] = st
                changed.append({"w": word, "status": st})
        panels, summary = self.board_stats()
        self.web.eval("applyBulkPatch(%s)" % json.dumps(
            {"words": changed, "panels": panels, "summary": summary}))
        self.write_config()

    # -- live update on note add

    def _on_note_added(self, note):
        """AddCards hook: patch the new note's word into the open map
        without a deck rescan. Covers the Add dialog only — imports and
        syncs still go through the Rescan button."""
        try:
            self._apply_new_note(note)
        except Exception:
            debug_line("note-add patch error:\n" + traceback.format_exc())

    def _apply_new_note(self, note):
        deck = self.deck_box.currentText()
        field = self.field_box.currentText()
        key = (deck, field)
        if not deck or not field or key not in self._scan_cache:
            return
        # only notes landing in the selected deck or one of its subdecks
        names = (mw.col.decks.name(c.did) for c in note.cards())
        if not any(n == deck or n.startswith(deck + "::") for n in names):
            return
        pos = None
        for i, fld in enumerate(note.note_type()["flds"]):
            if fld["name"] == field:
                pos = i
                break
        if pos is None or pos >= len(note.fields):
            return
        txt = _clean(note.fields[pos])
        if not txt:
            return
        texts = {txt}
        hz = _hanzi_only(txt)
        if hz:
            texts.add(hz)
        field_map, _reviewed = self._scan_cache[key]
        changed = []
        for t in texts:
            field_map[t].add(note.id)
        for t in texts:
            for word in self._alias_index.get(t, ()):
                tile = self._tile_index.get(word)
                st = self.effective_status(word, tile["aliases"])
                if self._last_status.get(word) != st:
                    self._last_status[word] = st
                    changed.append({"w": word, "status": st})
        if not changed:
            return
        debug_line("note-add patch: %s -> %s"
                   % (txt, [c["w"] for c in changed]))
        panels, summary = self.board_stats()
        self.web.eval("applyBulkPatch(%s)" % json.dumps(
            {"words": changed, "panels": panels, "summary": summary}))

    # -- bridge

    def on_bridge(self, cmd):
        debug_line("bridge: %s" % cmd)
        try:
            return self._dispatch(cmd)
        except Exception:
            debug_line("bridge error:\n" + traceback.format_exc())
            raise

    def _dispatch(self, cmd):
        if cmd.startswith("hskinfo:"):
            return self.word_info(cmd[len("hskinfo:"):])
        if cmd.startswith("hskknown:"):
            return self.toggle_known(cmd[len("hskknown:"):])
        if cmd.startswith("hsktoggle:"):
            self.toggle_collapsed(cmd[len("hsktoggle:"):])
            return None
        if cmd.startswith("hskfind:"):
            self.open_in_browser(cmd[len("hskfind:"):])
            return None
        if cmd.startswith("hskzoom:"):
            action = cmd[len("hskzoom:"):]
            if action == "in":
                self.zoom_in()
            elif action == "out":
                self.zoom_out()
            elif action == "reset":
                self.zoom_reset()
        return None

    def open_in_browser(self, word):
        """Open the browser on the exact notes the scan matched for this
        word; falls back to a field-qualified text search."""
        tile = self._tile_index.get(word)
        aliases = tile["aliases"] if tile else [word.replace("…", "")]
        field_map, _reviewed = self._scan()
        nids = set()
        for alias in aliases:
            nids |= field_map.get(alias, set())
        if nids:
            query = "nid:" + ",".join(str(n) for n in sorted(nids)[:100])
        else:
            query = 'deck:"%s" %s' % (
                self.deck_box.currentText(),
                self._field_term(self.field_box.currentText(),
                                 word.replace("…", "")))
        from aqt import dialogs
        browser = dialogs.open("Browser", mw)
        browser.search_for(query)

    @staticmethod
    def _field_term(field, word):
        """A field-qualified search term: Hanzi:"出", quoted as a whole
        when the field name itself needs quoting."""
        word = word.replace('"', "")
        if not field:
            return '"%s"' % word
        if " " in field or ":" in field or '"' in field:
            return '"%s:%s"' % (field.replace('"', ""), word)
        return '%s:"%s"' % (field, word)

    def toggle_collapsed(self, lvl_str):
        try:
            lvl = int(lvl_str)
        except ValueError:
            return
        ver = self.ver_box.currentData()
        levels = self.collapsed_levels(ver)
        levels.symmetric_difference_update({lvl})
        self.collapsed[ver] = sorted(levels)
        self.write_config()

    def toggle_known(self, word):
        """Right-click: flip a word's known flag, persist, return a JSON
        patch (tile status + refreshed header numbers) for the page."""
        if word in self.known:
            self.known.discard(word)
        else:
            self.known.add(word)
        save_known(self.known)

        tile = self._tile_index.get(word)
        aliases = tile["aliases"] if tile else [word]
        self._last_status[word] = self.effective_status(word, aliases)
        panels, summary = self.board_stats()
        return json.dumps({
            "word": word,
            "status": self._last_status[word],
            "panels": panels,
            "summary": summary,
        })

    def word_info(self, word):
        tile = self._tile_index.get(word)
        aliases = tile["aliases"] if tile else [word]
        _key, info = self.vocab.dict_info(word, aliases)
        base = self._status(aliases)
        ver = self.ver_box.currentData()
        tags = self.vocab.tags_for(word)
        my_levels = [t for t in tags if t.startswith(ver + "-")]
        other = [t for t in tags if not t.startswith(ver + "-")]
        lvl_num = int(my_levels[0].split("-")[1]) if my_levels else 0
        if base > 0:
            state = "deck"
        elif word in self.known:
            state = "known"
        else:
            state = "unknown"
        return json.dumps({
            "word": word,
            "forms": info["forms"] if info else [],
            "bases": self.vocab.erhua_bases(info) if info else [],
            "levels": my_levels + other,
            "state": state,
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

    def _status(self, aliases):
        field_map, reviewed = self._scan()
        nids = set()
        for alias in aliases:
            nids |= field_map.get(alias, set())
        if not nids:
            return 0
        return 2 if nids & reviewed else 1

    def effective_status(self, word, aliases):
        if self.chk_known.isChecked() and word in self.known:
            return 2
        return self._status(aliases)

    def board_stats(self):
        """Per-panel header numbers + top summary (summary covers HSK 1-6
        only, matching the page header)."""
        panels = []
        reviewed = indeck = total = 0
        cum = 0
        for lvl, tiles in sorted(self._last_levels.items()):
            r, d, n = counts(tiles, self._last_status)
            cum += n
            if lvl <= 6:
                reviewed += r
                indeck += d
                total += n
            panels.append(panel_stats(lvl, tiles, self._last_status,
                                      cum_total=cum))
        covered = reviewed + indeck
        summary = {
            "pct": "%.1f%%" % (100.0 * covered / total if total else 0.0),
            "covered": str(covered),
            "reviewed": str(reviewed),
        }
        return panels, summary

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

        levels_tiles = {lvl: self.vocab.levels[ver][lvl]
                        for lvl in range(1, VERSION_MAX[ver] + 1)}

        self._tile_index = {}
        status = {}
        for tiles in levels_tiles.values():
            for t in tiles:
                self._tile_index.setdefault(t["w"], t)
                if t["w"] not in status:
                    status[t["w"]] = self.effective_status(
                        t["w"], t["aliases"])
        self._alias_index = {}
        for w, t in self._tile_index.items():
            for a in t["aliases"]:
                self._alias_index.setdefault(a, []).append(w)
        self._last_levels = levels_tiles
        self._last_status = status

        page = build_html(levels_tiles, status, self.ver_box.currentText(),
                          deck, field, night=theme_manager.night_mode,
                          collapsed_levels=self.collapsed_levels(ver))
        self.web.setHtml(page)
        self.write_config()

    def write_config(self):
        mw.addonManager.writeConfig(__name__, {
            "deck": self.deck_box.currentText(),
            "field": self.field_box.currentText(),
            "version": self.ver_box.currentData(),
            "show_known": self.chk_known.isChecked(),
            "collapsed": self.collapsed,
            "zoom": self._zoom,
            "known_file": self._known_file,
        })


# ---------------------------------------------------------------- menu

_dialog = None

def show_dialog():
    global _dialog
    start_watchdog()
    debug_line("dialog opened")
    _dialog = HSKCoverageDialog(mw)
    _dialog.show()

def setup_menu():
    from aqt.qt import QAction
    action = QAction("HSK Coverage Map", mw)
    qconnect(action.triggered, show_dialog)
    mw.form.menuTools.addAction(action)

setup_menu()

try:
    # dump Python stacks into debug.log on a hard crash (segfault etc.)
    faulthandler.enable(_debug_file())
except (OSError, RuntimeError):
    pass
