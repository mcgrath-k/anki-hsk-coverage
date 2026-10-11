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
from collections import defaultdict, deque

from aqt import mw
from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QLabel,
    QPushButton, QLineEdit, QFrame, QToolButton, QWidget, QSizePolicy,
    QSpacerItem, QProgressBar, QShortcut, QKeySequence, QFileDialog, QFontMetrics, QTimer, QEvent, Qt,
    qconnect,
)
from aqt.webview import AnkiWebView
from aqt.theme import theme_manager

from .vocab import (
    Vocab, VERSIONS, VERSION_MAX, CEDICT_PATH, DOWNLOADS, download,
)
from .render import (
    LEVEL_COLORS, build_html, panel_stats, counts, level_label,
)
from .plan import recommend, FREQ_MODES

PLAN_MODES = ("board",) + FREQ_MODES

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
        now = time.monotonic()
        if self._reported:
            # the stall a dump was written for has ended — record for how
            # long the main thread was actually gone
            debug_line("watchdog: main thread recovered after %.1fs stall"
                       % (now - self._beat))
            self._reported = False
        self._beat = now

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


def _env_line():
    """One line of version/context info, so every debug.log correlates a
    problem with the environment it happened in."""
    try:
        from aqt import appVersion
    except Exception:
        appVersion = "?"
    try:
        from aqt.qt import QT_VERSION_STR
    except Exception:
        QT_VERSION_STR = "?"
    import platform
    return "env: anki=%s qt=%s os=%s night=%s" % (
        appVersion, QT_VERSION_STR, platform.platform(),
        theme_manager.night_mode)


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
    """Load word data. On first ever run (or after a failed attempt) fetch
    the dictionary and the corpus frequency lists first, behind a panel
    that shows each transfer's progress and speed."""
    global _vocab
    if _vocab is None:
        missing = [d for d in DOWNLOADS if not os.path.exists(d[2])]
        if missing:
            dlg = DownloadDialog(mw, missing)
            dlg.exec()
            if dlg.failed:
                from aqt.utils import tooltip
                tooltip(
                    "Download failed: %s. The map works without it; the "
                    "download is retried next time the map opens, or from "
                    "the study plan." % ", ".join(dlg.failed), period=6000)
        _vocab = Vocab()
    return _vocab


def reload_vocab():
    """Drop the cached data and load again (retrying any downloads)."""
    global _vocab
    _vocab = None
    return get_vocab()


def _fmt_bytes(n):
    if n >= 1 << 20:
        return "%.1f MB" % (n / (1 << 20))
    return "%d KB" % (n / (1 << 10))


class DownloadDialog(QDialog):
    """The one-time downloads, one row each with a progress bar and a
    'done of total · speed' line. Transfers run on a worker thread that
    only writes to self._state; a timer on the Qt thread paints it."""

    def __init__(self, parent, items):
        super().__init__(parent)
        self.setWindowTitle("HSK Coverage Map — downloading data")
        self.setMinimumWidth(480)
        self._items = items
        # per item: [bytes done, total or None, bytes/s, status]
        self._state = [[0, None, 0.0, ""] for _ in items]
        self._cancel = False
        self.failed = []
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Fetching the dictionary and word-frequency lists the map "
            "needs. This happens once; everything is offline afterwards.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self._rows = []
        for label, _url, _path in items:
            lay.addSpacing(8)
            lay.addWidget(QLabel("<b>%s</b>" % html_mod.escape(label)))
            bar = QProgressBar()
            bar.setRange(0, 1000)
            lay.addWidget(bar)
            st = QLabel("waiting…")
            lay.addWidget(st)
            self._rows.append((bar, st))
        lay.addSpacing(8)
        cancel = QPushButton("Cancel")
        qconnect(cancel.clicked, self._on_cancel)
        lay.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignRight)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        qconnect(self._timer.timeout, self._refresh)
        self._timer.start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        for i, (label, url, path) in enumerate(self._items):
            if self._cancel:
                self._state[i][3] = "cancelled"
                continue
            samples = deque()   # (time, bytes) over the last ~1.5 s

            def progress(done, total, i=i, samples=samples):
                now = time.monotonic()
                samples.append((now, done))
                while now - samples[0][0] > 1.5 and len(samples) > 1:
                    samples.popleft()
                dt = now - samples[0][0]
                speed = (done - samples[0][1]) / dt if dt > 0.2 else 0.0
                self._state[i][0:3] = [done, total, speed]
            try:
                ok = download(url, path, progress=progress,
                              cancelled=lambda: self._cancel)
                self._state[i][3] = "done" if ok else "cancelled"
            except Exception as e:
                self._state[i][3] = "failed: %s" % e
                debug_line("download failed %s: %s" % (url, e))

    def _refresh(self):
        for (bar, st), (done, total, speed, status) in zip(
                self._rows, self._state):
            if status == "done":
                bar.setRange(0, 1000)
                bar.setValue(1000)
                st.setText("done · %s" % _fmt_bytes(done))
            elif status:
                st.setText(status)
            elif not done:
                st.setText("waiting…")
            else:
                if total:
                    bar.setValue(int(1000 * done / total))
                    text = "%s of %s" % (_fmt_bytes(done), _fmt_bytes(total))
                else:
                    bar.setRange(0, 0)      # size unknown: busy bar
                    text = _fmt_bytes(done)
                if speed:
                    text += " · %s/s" % _fmt_bytes(speed)
                st.setText(text)
        if not self._thread.is_alive():
            self._timer.stop()
            self.failed = [item[0] for item, state in
                           zip(self._items, self._state)
                           if state[3] != "done"]
            self.accept()

    def _on_cancel(self):
        self._cancel = True

    def reject(self):          # window close button
        self._cancel = True
        super().reject()


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

class FindBar(QFrame):
    """Floating find panel over the map (Cmd/Ctrl+F). The text field is a
    native Qt widget on purpose: an HTML input inside the webview brings
    up the macOS input-method popup in QtWebEngine, which freezes Anki
    (same mechanism as the old <select> bug). It is a plain child widget
    of the dialog, not a popup window, so there is no native popup at
    all. Enter/↓ next match, Shift+Enter/↑ previous, Escape closes."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setObjectName("hskfind")
        self.setStyleSheet(
            "#hskfind { background: palette(base); "
            "border: 1px solid palette(mid); border-radius: 8px; } "
            "QToolButton { border: none; border-radius: 4px; } "
            "QToolButton:hover { background: palette(midlight); }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 4, 4)
        lay.setSpacing(2)
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Find word")
        self.edit.setFixedWidth(170)
        self.edit.setFrame(False)
        qconnect(self.edit.textChanged, owner.find_set)
        lay.addWidget(self.edit)
        self.count = QLabel("")
        lay.addSpacing(6)
        lay.addWidget(self.count)
        lay.addSpacing(4)
        h = self.edit.sizeHint().height()
        for text, tip, fn in (
                ("‹", "previous (shift+enter)", lambda: owner.find_go(-1)),
                ("›", "next (enter)", lambda: owner.find_go(1)),
                ("×", "close (esc)", self.close_)):
            b = QToolButton(self)
            b.setText(text)
            b.setAutoRaise(True)
            b.setFixedSize(h, h)
            f = b.font()
            f.setPointSize(f.pointSize() + 5)
            b.setFont(f)
            # the glyph's ink rarely sits at the centre of the font's
            # line box (which is what gets centred in the button), so
            # pad the box to centre the ink itself
            fm = QFontMetrics(f)
            off = fm.tightBoundingRect(text).center().y() \
                - (fm.descent() - fm.ascent()) / 2.0
            pad = int(round(2 * off))     # >0: ink is low, pad below
            b.setStyleSheet("QToolButton { padding: %dpx 0 %dpx 0; }"
                            % (max(0, -pad), max(0, pad)))
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            qconnect(b.clicked, fn)
            lay.addWidget(b)
        self.hide()

    def place(self):
        web = self.owner.web
        self.adjustSize()
        self.move(web.x() + (web.width() - self.width()) // 2, web.y() + 8)

    def open(self):
        self.place()
        self.show()
        self.raise_()
        self.edit.setFocus()
        self.edit.selectAll()

    def set_count(self, text):
        self.count.setText(text)
        if self.isVisible():
            self.place()     # the label changed width: re-fit and re-center

    def close_(self):
        self.edit.clear()
        self.hide()
        self.owner.web.setFocus()

    def reset(self):
        self.edit.blockSignals(True)
        self.edit.clear()
        self.edit.blockSignals(False)
        self.count.setText("")
        self.hide()

    def keyPressEvent(self, ev):
        k = ev.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.owner.find_go(-1 if shift else 1)
        elif k == Qt.Key.Key_Down:
            self.owner.find_go(1)
        elif k == Qt.Key.Key_Up:
            self.owner.find_go(-1)
        elif k == Qt.Key.Key_Escape:
            self.close_()
        else:
            super().keyPressEvent(ev)


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
        nm = cfg.get("nav_mode", "all")
        self._nav_mode = nm if nm in ("all", "unknown", "covered") else "all"
        self._plan_open = bool(cfg.get("plan_open", False))
        pm = cfg.get("plan_mode", "book")
        self._plan_mode = pm if pm in PLAN_MODES else "book"
        pl = cfg.get("plan_levels", "level")
        self._plan_levels = pl if pl in ("blend", "level") else "level"
        self._intro_seen = bool(cfg.get("intro_seen", False))
        try:
            self._plan_width = max(240, min(640,
                                            int(cfg.get("plan_width", 332))))
        except (TypeError, ValueError):
            self._plan_width = 332

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

        # the checkbox and the two buttons drop to a second toolbar row
        # one at a time when the window gets too narrow (see _restack_top)
        top.addSpacing(10)
        self.chk_known = QCheckBox("Include words marked known")
        self.chk_known.setChecked(bool(cfg.get("show_known", True)))
        self.chk_known.setToolTip(
            "Right-click a word on the map to mark it as one you already "
            "know without an Anki card. Uncheck to see only real deck "
            "coverage.")
        top.addWidget(self.chk_known)
        self._top1_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding,
                                         QSizePolicy.Policy.Minimum)
        top.addItem(self._top1_stretch)

        self._btns = QWidget()
        self._btns.setSizePolicy(QSizePolicy.Policy.Fixed,
                                 QSizePolicy.Policy.Fixed)
        btns = QHBoxLayout(self._btns)
        btns.setContentsMargins(0, 0, 0, 0)
        refresh = QPushButton("Rescan deck")
        qconnect(refresh.clicked, self.rescan)
        btns.addWidget(refresh)
        self._gear = QPushButton("Options")
        self._gear.setToolTip(
            "Arrow-key cycling, known-words database & debug files")
        qconnect(self._gear.clicked, self.open_options)
        btns.addWidget(self._gear)
        top.addWidget(self._btns)

        self._top1 = top
        self._row2 = QWidget()
        self._row2.setSizePolicy(QSizePolicy.Policy.Preferred,
                                 QSizePolicy.Policy.Fixed)
        self._top2 = QHBoxLayout(self._row2)
        self._top2.setContentsMargins(0, 0, 0, 0)
        self._top2.addStretch()
        self._row2.hide()
        self._stack = 0

        self.web = AnkiWebView(self)
        self.web.set_bridge_command(self.on_bridge, self)
        self.find_bar = FindBar(self)
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
        # Cmd/Ctrl+F opens the in-page find bar (also handled in-page)
        qconnect(QShortcut(QKeySequence("Ctrl+F"), self).activated,
                 self.show_find)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._row2)
        layout.addWidget(self.web, 1)   # the map takes all spare height
        # let the window shrink to what the fully stacked toolbar needs;
        # without an explicit minimum the one-row layout dictates the floor
        self._place_tools(2)
        layout.activate()
        self.setMinimumWidth(layout.minimumSize().width())
        self._place_tools(0)

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

        # geometry diagnostics for the runaway-window-growth report: log
        # every size change of this dialog, the webview and the main
        # window, with whether it came from the window system
        # (spontaneous) or from Qt code calling resize()
        self._geo_last = {}
        mw.installEventFilter(self)
        self.web.installEventFilter(self)

        debug_line("dialog cfg: zoom=%.2f deck=%r field=%r list=%s"
                   % (self._zoom, self.deck_box.currentText(),
                      self.field_box.currentText(),
                      self.ver_box.currentData()))
        self.render()

    def _log_geometry(self, name, obj, evt):
        size = "%dx%d" % (obj.width(), obj.height())
        if self._geo_last.get(name) == size:
            return
        self._geo_last[name] = size
        debug_line("geo: %s resized to %s spontaneous=%s"
                   % (name, size, evt.spontaneous()))

    def eventFilter(self, obj, evt):
        if evt.type() == QEvent.Type.Resize:
            if obj is mw:
                self._log_geometry("mw", mw, evt)
            elif obj is self.web:
                self._log_geometry("web", self.web, evt)
        return False

    def resizeEvent(self, evt):
        self._log_geometry("dialog", self, evt)
        super().resizeEvent(evt)
        if self.layout() is None:        # the resize() in __init__
            return
        self._restack_top()
        if self.find_bar.isVisible():
            self.find_bar.place()

    def _restack_top(self):
        """Stack the toolbar in stages as the window narrows: first the
        checkbox drops to a second row (the buttons stay top right), then
        the buttons follow. The one-row width is rebuilt from the current
        row plus whatever has been moved down, so it stays accurate."""
        m = self.layout().contentsMargins()
        avail = self.width() - m.left() - m.right()
        sp = self._top1.spacing()
        w_chk = self.chk_known.sizeHint().width() + sp
        w_btn = self._btns.sizeHint().width() + sp
        full = self._top1.sizeHint().width() + (
            w_chk + w_btn if self._stack == 2 else
            w_chk if self._stack == 1 else 0)
        level = 0 if avail >= full else 1 if avail >= full - w_chk else 2
        if level != self._stack:
            self._place_tools(level)

    def _place_tools(self, level):
        for w, down in ((self.chk_known, level >= 1),
                        (self._btns, level >= 2)):
            if down:
                self._top1.removeWidget(w)
                if w is self.chk_known:
                    self._top2.insertWidget(0, w)
                else:
                    self._top2.addWidget(w)
            else:
                self._top2.removeWidget(w)
                if w is self.chk_known:   # back in front of the stretch
                    self._top1.insertWidget(
                        self._top1.indexOf(self._top1_stretch), w)
                else:
                    self._top1.addWidget(w)
        self._row2.setVisible(level >= 1)
        self._stack = level

    def closeEvent(self, evt):
        try:
            from aqt import gui_hooks
            gui_hooks.add_cards_did_add_note.remove(self._on_note_added)
        except (ImportError, AttributeError, ValueError):
            pass
        mw.removeEventFilter(self)
        self.web.removeEventFilter(self)
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

    # -- options popup (rendered in the page, same styling as the info card)

    def open_options(self):
        self.web.eval("if (window.showOptions) showOptions()")

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

    # -- export

    def export_text(self):
        """The current list's coverage as simple JSON, meant to be pasted
        into a chat or shared: words per level in named buckets."""
        legend = {
            "known": "reviewed in Anki, or marked known",
            "unreviewed": "in the Anki deck but not reviewed yet, so "
                          "the user does not know these words either",
            "unknown": "not in the Anki deck",
        }
        def j(x):
            return json.dumps(x, ensure_ascii=False)
        # hand-formatted so each bucket's words stay on one line: a
        # pretty-printed dump would be one word per line, thousands long
        out = ['{', ' "list": %s,' % j(self.ver_box.currentText()),
               ' "deck": %s,' % j(self.deck_box.currentText()),
               ' "legend": {']
        out += [',\n'.join('  %s: %s' % (j(k), j(v))
                           for k, v in legend.items()), ' },', ' "levels": {']
        blocks = []
        for lvl, tiles in sorted(self._last_levels.items()):
            buckets = {k: [] for k in legend}
            for t in tiles:
                st = self._last_status.get(t["w"], 0)
                if st == 2:
                    key = "known"
                elif st == 1:
                    key = "unreviewed"
                else:
                    key = "unknown"
                buckets[key].append(t["w"])
            blocks.append('  %s: {\n%s\n  }' % (
                j(level_label(lvl)),
                ',\n'.join('   %s: %s' % (j(k), j(v))
                           for k, v in buckets.items())))
        out += [',\n'.join(blocks), ' }', '}']
        return '\n'.join(out)

    def export_json(self, save):
        from aqt.utils import tooltip
        text = self.export_text()
        label = self.ver_box.currentText()
        if not save:
            mw.app.clipboard().setText(text)
            tooltip("Copied %s coverage as JSON" % label, parent=self)
            return
        name = "%s_coverage_%s.json" % (
            re.sub(r"[^\w.]+", "_", label).strip("_"),
            time.strftime("%Y-%m-%d"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Save coverage as JSON", name, "JSON files (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            tooltip("Saved %s" % os.path.basename(path), parent=self)

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
            {"words": changed, "panels": panels, "summary": summary,
             "plan": self.study_plan()}))
        self.write_config()

    # -- live update on note add

    def _on_note_added(self, note):
        """AddCards hook: patch the new note's word into the open map
        without a deck rescan. Covers the Add dialog only — imports and
        syncs still go through the Rescan button."""
        try:
            self._apply_new_note(note)
        except Exception:
            # log for correlation, then let Anki's central exception
            # handler surface the error instead of failing silently
            debug_line("note-add patch error:\n" + traceback.format_exc())
            raise

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
            {"words": changed, "panels": panels, "summary": summary,
             "plan": self.study_plan()}))

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
        if cmd.startswith("hskpane:"):
            self._plan_open = cmd[len("hskpane:"):] == "1"
            self.write_config()
            return None
        if cmd.startswith("hskpanew:"):
            try:
                w = int(cmd[len("hskpanew:"):])
            except ValueError:
                return None
            self._plan_width = max(240, min(640, w))
            self.write_config()
            return None
        if cmd.startswith("hskplan:"):
            kind, _, val = cmd[len("hskplan:"):].partition(":")
            if kind == "mode" and val in PLAN_MODES:
                self._plan_mode = val
            elif kind == "levels" and val in ("blend", "level"):
                self._plan_levels = val
            else:
                return None
            self.write_config()
            return json.dumps(self.study_plan())
        if cmd == "hskdownload":
            # retry the one-time downloads from the study plan's notice
            self.vocab = reload_vocab()
            return json.dumps(self.study_plan())
        if cmd == "hskintro:done":
            self._intro_seen = True
            self.write_config()
            return None
        if cmd.startswith("hsknav:"):
            mode = cmd[len("hsknav:"):]
            if mode in ("all", "unknown", "covered"):
                self._nav_mode = mode
                self.write_config()
            return None
        if cmd.startswith("hskopt:"):
            action = cmd[len("hskopt:"):]
            if action == "reveal":
                self.reveal_known_file()
            elif action == "pick":
                self.pick_known_file()
            elif action == "move":
                self.create_known_file()
            elif action == "debug":
                self._reveal(DEBUG_LOG)
            elif action in ("copy", "save"):
                self.export_json(save=action == "save")
            return None
        if cmd == "hsksearch:focus":
            self.show_find()
            return None
        if cmd.startswith("hsksearch:count:"):
            self.find_bar.set_count(cmd[len("hsksearch:count:"):])
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

    def show_find(self):
        self.find_bar.open()

    def find_set(self, text):
        self.web.eval("if (window.findSet) findSet(%s)" % json.dumps(text))

    def find_go(self, direction):
        self.web.eval("if (window.findGo) findGo(%d)" % direction)

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
            "plan": self.study_plan(),
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

    def study_plan(self):
        """Ranked study recommendations for the side pane, enriched with
        pinyin, a first definition and the level color."""
        freq = (self.vocab.freq_book if self._plan_mode == "book"
                else self.vocab.freq_sub)
        items, total = recommend(self._last_levels, self._last_status,
                                 freq, mode=self._plan_mode,
                                 by_level=self._plan_levels == "level")
        for it in items:
            tile = self._tile_index.get(it["w"])
            _key, info = self.vocab.dict_info(
                it["w"], tile["aliases"] if tile else ())
            it["py"], it["def"] = self.vocab.best_gloss(info)
            it["color"] = LEVEL_COLORS.get(it["lvl"], "#888")
        out = {"items": items, "total": total}
        if self._plan_mode in FREQ_MODES and not freq:
            # the corpus list never got downloaded: say so instead of
            # showing every word as "no frequency data"
            out["missing"] = ("subtitle" if self._plan_mode == "sub"
                              else "book")
        return out

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
            # headline percentage counts reviewed-or-known words only,
            # matching build_html
            "pct": "%.1f%%" % (100.0 * reviewed / total if total else 0.0),
            "reviewed": str(reviewed),
            "covered": str(covered),
            "covpct": "%.1f%%" % (100.0 * covered / total if total else 0.0),
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
                          collapsed_levels=self.collapsed_levels(ver),
                          nav_mode=self._nav_mode, known_file=known_path(),
                          plan=self.study_plan(),
                          plan_open=self._plan_open,
                          plan_mode=self._plan_mode,
                          plan_levels=self._plan_levels,
                          show_intro=not self._intro_seen,
                          plan_width=self._plan_width)
        self.web.setHtml(page)
        self.find_bar.reset()
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
            "nav_mode": self._nav_mode,
            "plan_open": self._plan_open,
            "plan_mode": self._plan_mode,
            "plan_levels": self._plan_levels,
            "intro_seen": self._intro_seen,
            "plan_width": self._plan_width,
        })


# ---------------------------------------------------------------- menu

_dialog = None

def show_dialog():
    global _dialog
    start_watchdog()
    debug_line("dialog opened · " + _env_line())
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
