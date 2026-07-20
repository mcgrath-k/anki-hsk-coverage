# -*- coding: utf-8 -*-
"""HTML rendering for the HSK Coverage Map (no Anki dependencies).

Takes levels_tiles {lvl: [tile, ...]} from vocab.Vocab and a status map
{display word: 0 absent | 1 in deck | 2 reviewed-or-known}. Counts are
weighted by tile["n"] so per-level totals equal the official entry counts
even where duplicate surface forms were merged into one tile.

Panel stats are per level (the words new at that level), with the official
cumulative total shown alongside ("200 new · 500 total").

Layout: panels flow in strict level order into justified rows. Each panel's
width within a row is proportional to its content area, so panels in a row
come out roughly equal in height; a panel too big to share a row (like an
expanded HSK 7-9) takes the full width. Collapsed panels render as
full-width header bars.
"""

import json
import html as html_mod

LEVEL_COLORS = {
    1: "#34d399",  # green
    2: "#38bdf8",  # sky
    3: "#a78bfa",  # violet
    4: "#fbbf24",  # amber
    5: "#fb7185",  # rose
    6: "#f97316",  # orange
    7: "#6366f1",  # indigo (HSK 7-9)
}


def level_label(lvl):
    return "HSK 7–9" if lvl == 7 else "HSK %d" % lvl


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
.brow { display:flex; gap:12px; align-items:flex-start;
  margin-bottom:12px; }
.panel { background:var(--panel); border:1px solid var(--border);
  border-radius:12px; padding:12px 14px 14px 14px; min-width:0;
  flex:0 0 auto; }
.panel-head { display:flex; align-items:baseline; gap:10px;
  margin-bottom:4px; cursor:pointer; user-select:none;
  flex-wrap:nowrap; white-space:nowrap; }
.lvl { font-weight:700; font-size:13px; letter-spacing:0.04em; color:var(--c);
  flex:0 0 auto; }
.pct { font-size:12px; font-weight:700; color:var(--c);
  font-variant-numeric:tabular-nums; flex:0 0 auto; }
.stat { color:var(--muted); font-size:11.5px; margin-left:auto;
  font-variant-numeric:tabular-nums; flex:0 1 auto; min-width:0;
  overflow:hidden; text-overflow:ellipsis; }
.caret { color:var(--muted); font-size:10px; align-self:center;
  transition:transform .15s ease; }
.panel.collapsed .caret { transform:rotate(-90deg); }
.bar { height:3px; border-radius:2px; background:var(--tile);
  margin:6px 0 10px 0; display:flex; overflow:hidden; }
.panel.collapsed .bar { margin-bottom:0; }
.bar .r { background:var(--c); }
.bar .d { background:var(--c); opacity:0.35; }
.tiles { display:flex; flex-wrap:wrap; gap:4px; }
.panel.collapsed .tiles { display:none; }
.tiles::after { content:""; flex:999 0 auto; }
.t { font-size:11px; line-height:1; padding:4px 3px; border-radius:5px;
  cursor:pointer; white-space:nowrap; position:relative;
  flex:1 0 auto; text-align:center;
  border:1.5px solid transparent;
  transition:transform .16s cubic-bezier(.2,.8,.3,1.2); }
.t:hover { transform:scale(1.55); z-index:6; }
.t.st-r { background:var(--c); color:#fff; }
.t.st-d { background:var(--tile); color:var(--text); border-color:var(--c); }
.t.st-a { background:var(--tile); color:var(--tiletext); }
.legend { display:flex; gap:16px; align-items:center; flex-wrap:wrap;
  margin-top:14px; color:var(--muted); font-size:12px; }
.legend .t { cursor:default; --c:#94a3b8; flex:0 0 auto; }
.legend .t:hover { transform:none; }

/* info modal */
#ov { position:fixed; inset:0; background:var(--overlay); display:none;
  align-items:center; justify-content:center; z-index:50; }
#ov.show { display:flex; }
#card { background:var(--panel); border:1px solid var(--border);
  border-radius:14px; padding:22px 26px; max-width:440px; width:88%;
  max-height:80%; overflow-y:auto; box-shadow:0 18px 50px #00000055;
  position:relative; }
#card .x { position:absolute; top:8px; right:10px; border:none;
  background:none; color:var(--muted); font-size:20px; line-height:1;
  padding:6px; cursor:pointer; }
#card .x:hover { color:var(--text); }
#card .hz { font-size:46px; line-height:1.15; margin-bottom:2px; }
#card .basehz { font-size:26px; line-height:1.15; margin-bottom:2px; }
#card .py { font-size:17px; color:var(--c,#888); font-weight:600;
  margin-bottom:2px; }
#card .trad { color:var(--muted); font-size:13px; margin-bottom:8px; }
#card .nodef { color:var(--muted); font-size:13px; margin:8px 0; }
#card ul { margin:6px 0 10px 0; padding-left:20px; font-size:13.5px; }
#card li { margin:2px 0; }
#card .badges { display:flex; gap:6px; flex-wrap:wrap; margin:10px 0 4px 0; }
#card .badge { font-size:11px; font-weight:600; padding:3px 8px;
  border-radius:99px; background:var(--tile); color:var(--muted); }
#card .badge.lv { color:#fff; }
#card .btns { display:flex; gap:8px; margin-top:14px; }
#card button { border:1px solid var(--border); background:var(--tile);
  color:var(--text); font-size:12.5px; padding:6px 12px; border-radius:8px;
  cursor:pointer; }
#card button.st-deck { background:#3b82f6; border-color:transparent;
  color:#fff; }
#card button.st-known { background:transparent; border:1.5px solid #3b82f6;
  color:#3b82f6; }
#card .formsep { border:0; border-top:1px solid var(--border); margin:10px 0; }
"""

JS = r"""
var LEVEL_COLORS = %(colors)s;
var VER_LABELS = {"old":"HSK 2.0","new":"HSK 3.0 (2021)","newest":"HSK 3.0 (2025)"};

document.addEventListener('click', function(e){
  var head = e.target.closest('.panel-head');
  if (head) { togglePanel(head.parentNode); return; }
  var t = e.target.closest('.t[data-w]');
  if (t) { requestInfo(t.dataset.w); return; }
  if (e.target.id === 'ov') hideInfo();
});
document.addEventListener('contextmenu', function(e){
  var t = e.target.closest('.t[data-w]');
  if (!t) return;
  e.preventDefault();
  if (window.pycmd) pycmd('hskknown:' + t.dataset.w, applyPatch);
  else if (window.previewToggleKnown) previewToggleKnown(t);
});
document.addEventListener('keydown', function(e){
  if (e.key === 'Escape') hideInfo();
  if ((e.metaKey || e.ctrlKey) && window.pycmd){
    if (e.key === '=' || e.key === '+'){
      e.preventDefault(); pycmd('hskzoom:in');
    } else if (e.key === '-' || e.key === '_'){
      e.preventDefault(); pycmd('hskzoom:out');
    } else if (e.key === '0'){
      e.preventDefault(); pycmd('hskzoom:reset');
    }
  }
});

/* ---- collapsible panels ---- */
function togglePanel(p){
  // keep the clicked panel at the same viewport position through the
  // re-layout, so the view doesn't jump
  var before = p.getBoundingClientRect().top;
  p.classList.toggle('collapsed');
  if (window.pycmd) pycmd('hsktoggle:' + p.dataset.lvl);
  layoutBoard();
  window.scrollBy(0, p.getBoundingClientRect().top - before);
}

/* ---- justified layout ----
   Panels flow in strict level order. A row takes consecutive panels as
   long as giving each a width proportional to its content area keeps
   every width above MINW; the row's widths then fill the board exactly,
   so panels sharing a row come out roughly equal in height. Collapsed
   panels become full-width bars. */
var MINW = 380, GAP = 12;
var _panels = null;

function measurePanels(){
  var board = document.getElementById('board');
  _panels = Array.prototype.slice.call(board.querySelectorAll('.panel'));
  var meas = document.createElement('div');
  meas.style.cssText = 'position:absolute;left:-99999px;top:0;width:420px;';
  document.body.appendChild(meas);
  _panels.forEach(function(p){
    var was = p.classList.contains('collapsed');
    p.classList.remove('collapsed');
    p.style.width = '420px';
    meas.appendChild(p);
    var tiles = p.querySelector('.tiles');
    p._area = Math.max(1, tiles.offsetHeight) * 392;
    if (was) p.classList.add('collapsed');
  });
  document.body.removeChild(meas);
}

function layoutBoard(){
  var board = document.getElementById('board');
  if (!_panels) measurePanels();
  // emptying the board momentarily shrinks the page, which would clamp
  // the scroll position to the top — save it and restore afterwards
  var scrollY = window.scrollY;
  var W = board.clientWidth || document.body.clientWidth - 36;
  var rows = [], cur = [];
  function flush(){ if (cur.length){ rows.push(cur); cur = []; } }
  _panels.forEach(function(p){
    if (p.classList.contains('collapsed')){ flush(); rows.push([p]); return; }
    var test = cur.concat([p]);
    var sumA = 0;
    test.forEach(function(q){ sumA += q._area; });
    var avail = W - GAP * (test.length - 1);
    var minShare = Infinity;
    test.forEach(function(q){
      minShare = Math.min(minShare, avail * q._area / sumA);
    });
    if (cur.length && minShare < MINW) flush();
    cur.push(p);
  });
  flush();
  board.innerHTML = '';
  rows.forEach(function(r){
    var d = document.createElement('div');
    d.className = 'brow';
    var avail = W - GAP * (r.length - 1);
    var sumA = 0;
    r.forEach(function(q){ sumA += q._area; });
    r.forEach(function(q){
      q.style.height = '';
      q.style.width = (r.length === 1)
          ? '100%%'
          : Math.floor(avail * q._area / sumA) + 'px';
      d.appendChild(q);
    });
    board.appendChild(d);
    equalizeRow(r, avail);
  });
  window.scrollTo(0, scrollY);
}

/* nudge widths within a row until the panels' rendered heights match:
   from each panel's measured height, recover its true content area, then
   re-split the row width so header + area/width comes out equal */
function equalizeRow(r, avail){
  if (r.length < 2) return;
  for (var it = 0; it < 4; it++){
    var hs = [], heads = [], ws = [];
    r.forEach(function(p){
      hs.push(p.offsetHeight);
      heads.push(p.offsetHeight - p.querySelector('.tiles').offsetHeight);
      ws.push(parseFloat(p.style.width));
    });
    if (Math.max.apply(null, hs) - Math.min.apply(null, hs) < 6) break;
    var As = [], sumA = 0, headAvg = 0;
    r.forEach(function(p, i){
      As.push((hs[i] - heads[i]) * ws[i]);
      sumA += As[i];
      headAvg += heads[i] / r.length;
    });
    var H = headAvg + sumA / avail;
    var nw = [], sumW = 0;
    r.forEach(function(p, i){
      nw.push(Math.max(MINW, As[i] / Math.max(1, H - heads[i])));
      sumW += nw[i];
    });
    r.forEach(function(p, i){
      p.style.width = Math.floor(nw[i] * avail / sumW) + 'px';
    });
  }
  // whatever residual difference remains (tile rows are quantized),
  // stretch every panel to the row's tallest so bottoms always align
  var maxH = 0;
  r.forEach(function(p){ maxH = Math.max(maxH, p.offsetHeight); });
  r.forEach(function(p){ p.style.height = maxH + 'px'; });
}
var _lt = null;
window.addEventListener('resize', function(){
  clearTimeout(_lt); _lt = setTimeout(layoutBoard, 120);
});
window.addEventListener('DOMContentLoaded', layoutBoard);

/* ---- known-word patches: retint tiles and update headers in place,
   never re-rendering or re-flowing the board ---- */
function setTileStatus(word, status){
  var cls = status === 2 ? 'st-r' : (status === 1 ? 'st-d' : 'st-a');
  var tiles = document.querySelectorAll('.t[data-w]');
  for (var i = 0; i < tiles.length; i++){
    if (tiles[i].dataset.w === word)
      tiles[i].className = 't ' + cls;
  }
}
function updateHeaders(d){
  (d.panels || []).forEach(function(ps){
    var p = document.querySelector('.panel[data-lvl="' + ps.lvl + '"]');
    if (!p) return;
    p.querySelector('.pct').textContent = ps.pct;
    p.querySelector('.stat').textContent = ps.stat;
    p.querySelector('.bar .r').style.width = ps.rw;
    p.querySelector('.bar .d').style.width = ps.dw;
  });
  if (d.summary){
    document.getElementById('sum-pct').textContent = d.summary.pct;
    document.getElementById('sum-cov').textContent = d.summary.covered;
    document.getElementById('sum-rev').textContent = d.summary.reviewed;
  }
}
function applyPatch(raw){
  var d = (typeof raw === 'string') ? JSON.parse(raw) : raw;
  setTileStatus(d.word, d.status);
  updateHeaders(d);
}
function applyBulkPatch(raw){
  var d = (typeof raw === 'string') ? JSON.parse(raw) : raw;
  (d.words || []).forEach(function(w){ setTileStatus(w.w, w.status); });
  updateHeaders(d);
}

/* ---- info modal ---- */
function requestInfo(w){
  if (window.pycmd) pycmd('hskinfo:' + w, showInfo);
  else if (window.PREVIEW_INFO && PREVIEW_INFO[w]) showInfo(PREVIEW_INFO[w]);
}
function toggleKnownFromCard(w){
  if (window.pycmd)
    pycmd('hskknown:' + w, function(raw){
      applyPatch(raw);
      requestInfo(w);   // refresh the open card's button state
    });
  else if (window.previewToggleKnownWord)
    previewToggleKnownWord(w);
}
function esc(s){ var d=document.createElement('div'); d.textContent=s;
  return d.innerHTML; }
function hideInfo(){ document.getElementById('ov').classList.remove('show'); }
function showInfo(raw){
  var d = (typeof raw === 'string') ? JSON.parse(raw) : raw;
  var c = document.getElementById('card');
  c.style.setProperty('--c', d.color);
  function formsHtml(forms, word){
    var h = '';
    forms.forEach(function(f, i){
      if (i > 0) h += '<hr class="formsep">';
      h += '<div class="py">' + esc(f.p) + '</div>';
      if (f.t && f.t !== word)
        h += '<div class="trad">traditional: ' + esc(f.t) + '</div>';
      if (f.m.length){
        h += '<ul>';
        f.m.forEach(function(m){ h += '<li>' + esc(m) + '</li>'; });
        h += '</ul>';
      }
    });
    return h;
  }
  var h = '<button class="x" onclick="hideInfo()" title="close">×</button>';
  h += '<div class="hz">' + esc(d.word) + '</div>';
  if (!d.forms.length)
    h += '<div class="nodef">No dictionary entry available.</div>';
  h += formsHtml(d.forms, d.word);
  (d.bases || []).forEach(function(b){
    h += '<hr class="formsep">';
    h += '<div class="basehz">' + esc(b.word) + '</div>';
    h += formsHtml(b.forms, b.word);
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
  h += '<div class="btns">';
  if (d.state === 'deck'){
    h += '<button class="st-deck" title="open in Anki\'s browser" ' +
         'onclick="if(window.pycmd)pycmd(\'hskfind:' +
         esc(d.word) + '\')">In deck</button>';
  } else if (d.state === 'known'){
    h += '<button class="st-known" title="click to unmark" ' +
         'onclick="toggleKnownFromCard(\'' +
         esc(d.word) + '\')">Marked known</button>';
  } else {
    h += '<button title="click to mark as known" ' +
         'onclick="toggleKnownFromCard(\'' +
         esc(d.word) + '\')">Unknown</button>';
  }
  h += '</div>';
  c.innerHTML = h;
  document.getElementById('ov').classList.add('show');
}
"""


def counts(tiles, status):
    reviewed = sum(t["n"] for t in tiles if status.get(t["w"]) == 2)
    indeck = sum(t["n"] for t in tiles if status.get(t["w"]) == 1)
    total = sum(t["n"] for t in tiles)
    return reviewed, indeck, total


def panel_stats(lvl, tiles, status, cum_total):
    """Header numbers for one panel, as strings ready for HTML/JS patch."""
    reviewed, indeck, total = counts(tiles, status)
    covered = reviewed + indeck
    pct = 100.0 * covered / total if total else 0.0
    return {
        "lvl": lvl,
        "pct": "%.0f%%" % pct,
        "stat": "%d reviewed · %d unreviewed · %d new · %d total"
                % (reviewed, indeck, total, cum_total),
        "rw": "%.2f%%" % (100.0 * reviewed / total if total else 0),
        "dw": "%.2f%%" % (100.0 * indeck / total if total else 0),
    }


def _panel_html(lvl, tiles, status, cum_total, collapsed):
    ps = panel_stats(lvl, tiles, status, cum_total)
    out = []
    for t in tiles:
        st = status.get(t["w"], 0)
        cls = ("st-r", "st-d")[st == 1] if st else "st-a"
        we = html_mod.escape(t["w"], quote=True)
        out.append('<span class="t %s" data-w="%s">%s</span>'
                   % (cls, we, html_mod.escape(t["w"])))
    return """
<div class="panel%s" style="--c:%s" data-lvl="%d">
  <div class="panel-head" title="click to collapse/expand">
    <span class="lvl">%s</span>
    <span class="pct">%s</span>
    <span class="stat">%s</span>
    <span class="caret">▼</span>
  </div>
  <div class="bar">
    <div class="r" style="width:%s"></div>
    <div class="d" style="width:%s"></div>
  </div>
  <div class="tiles">%s</div>
</div>""" % (
        " collapsed" if collapsed else "", LEVEL_COLORS[lvl], lvl,
        level_label(lvl), ps["pct"], ps["stat"], ps["rw"], ps["dw"],
        "".join(out),
    )


def build_html(levels_tiles, status, version_label, deck_name, field_name,
               night=False, collapsed_levels=(), extra_js=""):
    panels = []
    reviewed = indeck = total = 0       # HSK 1-6 only, for the top summary
    cum = 0
    for lvl, tiles in sorted(levels_tiles.items()):
        r, d, n = counts(tiles, status)
        cum += n
        if lvl <= 6:
            reviewed += r
            indeck += d
            total += n
        panels.append(_panel_html(lvl, tiles, status, cum_total=cum,
                                  collapsed=lvl in collapsed_levels))
    panels = "".join(panels)
    covered = reviewed + indeck
    pct = 100.0 * covered / total if total else 0.0
    js = JS % {"colors": json.dumps(LEVEL_COLORS)}

    return """<!doctype html><html><head><meta charset="utf-8">
<style>%s</style></head>
<body class="%s">
  <div class="summary">
    <span class="big" id="sum-pct">%.1f%%</span>
    <span class="sub"><b id="sum-cov">%d</b> of <b>%d</b> HSK 1–6 words
      (%s) in <b>%s</b> (<span id="sum-rev">%d</span> reviewed or known)
      · matching field “%s”</span>
  </div>
  <div class="board" id="board">%s</div>
  <div class="legend">
    <span><span class="t st-r" style="background:#94a3b8;color:#fff">爱</span>
      reviewed, or marked known</span>
    <span><span class="t st-d" style="border-color:#94a3b8">爱</span>
      in deck, not yet reviewed</span>
    <span><span class="t st-a">爱</span> not in deck</span>
    <span>hover to zoom · click for details · right-click to mark a word
      you already know</span>
  </div>
  <div id="ov"><div id="card"></div></div>
  <script>%s%s</script>
</body></html>""" % (
        CSS, "night" if night else "",
        pct, covered, total,
        html_mod.escape(version_label), html_mod.escape(deck_name),
        reviewed, html_mod.escape(field_name),
        panels, js, extra_js,
    )
