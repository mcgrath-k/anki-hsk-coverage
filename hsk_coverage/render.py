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

try:
    from .plan import W_FREQ, W_COMP, W_UNLOCK, W_LEVEL
except ImportError:          # browser-preview scripts import render flat
    from plan import W_FREQ, W_COMP, W_UNLOCK, W_LEVEL

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
.legend .hint { text-decoration:underline dotted; cursor:help; }

/* study-plan side pane */
.planbtn { border:1px solid var(--border); background:var(--panel);
  color:var(--text); font-size:12px; padding:5px 12px; border-radius:8px;
  cursor:pointer; margin-left:auto; }
.planbtn:hover { border-color:#3b82f6; color:#3b82f6; }
body.planopen { padding-right:calc(var(--planw,332px) + 20px); }
#plan { position:fixed; top:0; right:calc(-1 * var(--planw,332px) - 13px);
  width:var(--planw,332px); height:100%;
  background:var(--panel); border-left:1px solid var(--border);
  z-index:40; display:flex; flex-direction:column;
  transition:right .2s ease; }
body.planopen #plan { right:0; }
#pgrip { position:absolute; left:0; top:0; width:6px; height:100%;
  cursor:col-resize; }
#pgrip:hover { background:var(--border); }
#plan .phead { display:flex; align-items:baseline; gap:8px;
  padding:14px 16px 10px 16px; border-bottom:1px solid var(--border); }
#plan .phead b { font-size:14px; }
#plan .pmethod { display:flex; gap:5px; flex-wrap:wrap; align-items:center;
  padding:8px 16px; font-size:10.5px; color:var(--muted);
  border-bottom:1px solid var(--border); }
.mchip { background:var(--tile); border-radius:99px; padding:2px 8px;
  font-weight:600; cursor:pointer; }
.mchip.sel { background:#3b82f6; color:#fff; }
.mchip.ihelp { margin-left:auto; background:transparent;
  border:1px solid var(--border); color:var(--muted); font-weight:700;
  font-size:10.5px; line-height:1; padding:3px 8px; align-self:center; }
.mchip.ihelp:hover { border-color:#3b82f6; color:#3b82f6; }
.mgrp { display:flex; gap:5px; align-items:center; flex-wrap:wrap; }
#plan-help { display:none; padding:8px 16px 10px 16px; font-size:11px;
  line-height:1.45; color:var(--muted);
  border-bottom:1px solid var(--border); }
#plan-help .phrow { margin-bottom:6px; }
#plan-help b { color:var(--text); }
#plan-list { overflow-y:auto; flex:1; padding:8px 10px; }
.prow { display:flex; gap:10px; align-items:flex-start;
  padding:7px 6px; border-radius:8px; max-height:70px; overflow:hidden;
  transition:opacity .5s ease, max-height .35s ease .45s,
             padding .35s ease .45s; }
.prow:hover { background:var(--tile); }
.prow.fadeout { opacity:0; max-height:0; padding-top:0; padding-bottom:0; }
.prow .t { flex:0 0 auto; font-size:14px; padding:6px 7px; margin-top:1px; }
.prow .t:hover { transform:scale(1.15); }
.prow .pmeta { min-width:0; }
.prow .ppy { font-size:12.5px; }
.prow .pdef { color:var(--muted); font-size:12px; }
.prow .pline { overflow:hidden; text-overflow:ellipsis;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.prow .preason { color:var(--muted); font-size:10.5px; margin-top:2px;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

/* info & options modals (shared card styling).
   Toggled with opacity/visibility on a promoted layer, NOT display: a
   display toggle of a full-viewport translucent overlay forces a repaint
   of the entire board underneath, which can wedge QtWebEngine's
   in-process compositor for seconds (the "click the x and Anki halts"
   freeze). Opacity on its own layer never touches the board's pixels. */
#ov, #oov, #iov { position:fixed; inset:0; background:var(--overlay);
  display:flex; align-items:center; justify-content:center; gap:4px;
  z-index:50; opacity:0; visibility:hidden; will-change:opacity;
  transition:opacity .12s ease, visibility 0s linear .12s; }
#ov.show, #oov.show, #iov.show { opacity:1; visibility:visible;
  transition:opacity .12s ease; }
.ibody { font-size:13.5px; line-height:1.55; margin-top:8px; }
.ibody .t { cursor:default; flex:0 0 auto; }
.ibody .t:hover { transform:none; }
.idots { display:flex; gap:6px; justify-content:center;
  margin:16px 0 4px 0; }
.idots i { width:7px; height:7px; border-radius:99px;
  background:var(--tile); }
.idots i.on { background:#3b82f6; }
.card { background:var(--panel); border:1px solid var(--border);
  border-radius:14px; padding:22px 26px; max-width:440px; width:88%;
  max-height:80%; overflow-y:auto; box-shadow:0 18px 50px #00000055;
  position:relative; }
.nav { border:none; background:none; color:#fff; font-size:36px;
  line-height:1; padding:10px 12px; cursor:pointer; opacity:0.55;
  user-select:none; flex:0 0 auto; }
.nav:hover { opacity:1; }
.card .x { position:absolute; top:8px; right:10px; border:none;
  background:none; color:var(--muted); font-size:20px; line-height:1;
  padding:6px; cursor:pointer; }
.card .x:hover { color:var(--text); }
.card .hz { font-size:46px; line-height:1.15; margin-bottom:2px; }
.card .basehz { font-size:26px; line-height:1.15; margin-bottom:2px; }
.card .py { font-size:17px; color:var(--c,#888); font-weight:600;
  margin-bottom:2px; }
.card .trad { color:var(--muted); font-size:13px; margin-bottom:8px; }
.card .nodef { color:var(--muted); font-size:13px; margin:8px 0; }
.card ul { margin:6px 0 10px 0; padding-left:20px; font-size:13.5px; }
.card li { margin:2px 0; }
.card .badges { display:flex; gap:6px; flex-wrap:wrap; margin:10px 0 4px 0; }
.card .badge { font-size:11px; font-weight:600; padding:3px 8px;
  border-radius:99px; background:var(--tile); color:var(--muted); }
.card .badge.lv { color:#fff; }
.card .btns { display:flex; gap:8px; margin-top:14px; flex-wrap:wrap; }
.card button { border:1px solid var(--border); background:var(--tile);
  color:var(--text); font-size:12.5px; padding:6px 12px; border-radius:8px;
  cursor:pointer; }
.card button.st-deck { background:#3b82f6; border-color:transparent;
  color:#fff; }
.card button.st-known { background:transparent; border:1.5px solid #3b82f6;
  color:#3b82f6; }
.card .formsep { border:0; border-top:1px solid var(--border); margin:10px 0; }
.card .ttl { font-size:18px; font-weight:700; }
.card .sec { font-size:11px; font-weight:700; letter-spacing:0.06em;
  text-transform:uppercase; color:var(--muted); margin:16px 0 6px 0; }
.card .path { font-family:ui-monospace,Menlo,Consolas,monospace;
  font-size:11px; color:var(--muted); word-break:break-all;
  margin-bottom:8px; }
"""

JS = r"""
var LEVEL_COLORS = %(colors)s;
var VER_LABELS = {"old":"HSK 2.0","new":"HSK 3.0 (2021)","newest":"HSK 3.0 (2025)"};
var NAV_MODE = %(nav_mode)s;      // 'all' | 'unknown' | 'covered'
var KNOWN_PATH = %(known_path)s;  // shown in the options popup
var INITIAL_PLAN = %(plan)s;      // study-plan items rendered on load
var PLAN_MODE = %(plan_mode)s;    // 'smart' | 'board'
var PLAN_LEVELS = %(plan_levels)s;// 'blend' | 'level'
var PLAN_TIPS = %(plan_tips)s;    // hover explanations for the chips
var SHOW_INTRO = %(show_intro)s;  // first ever start: show the tour

// any uncaught JS error lands in user_files/debug.log with its location,
// so page-side failures are never silent
window.onerror = function(msg, src, line, col){
  if (window.pycmd)
    pycmd('hsklog:js-error ' + msg + ' @' + line + ':' + col);
};

document.addEventListener('click', function(e){
  var head = e.target.closest('.panel-head');
  if (head) { togglePanel(head.parentNode); return; }
  var t = e.target.closest('.t[data-w]');
  if (t) { requestInfo(t.dataset.w); return; }
  if (e.target.id === 'ov') hideInfo();
  if (e.target.id === 'oov') hideOptions();
  if (e.target.id === 'iov') hideIntro();
});
document.addEventListener('contextmenu', function(e){
  var t = e.target.closest('.t[data-w]');
  if (!t) return;
  e.preventDefault();
  if (window.pycmd) pycmd('hskknown:' + t.dataset.w, applyPatch);
  else if (window.previewToggleKnown) previewToggleKnown(t);
});
document.addEventListener('keydown', function(e){
  if (e.key === 'Escape'){ hideInfo(); hideOptions(); hideIntro(); }
  if (document.getElementById('iov').classList.contains('show')){
    if (e.key === 'ArrowRight'){ e.preventDefault(); introGo(1); }
    else if (e.key === 'ArrowLeft'){ e.preventDefault(); introGo(-1); }
  } else if (document.getElementById('ov').classList.contains('show')){
    if (e.key === 'ArrowRight'){ e.preventDefault(); navInfo(1); }
    else if (e.key === 'ArrowLeft'){ e.preventDefault(); navInfo(-1); }
  }
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
var _lastW = 0;

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
  _lastW = W;
  if (window.pycmd)
    pycmd('hsklog:layout W=' + W + ' doc=' +
          document.documentElement.scrollWidth + 'x' +
          document.documentElement.scrollHeight);
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
/* ---- study-plan side pane ---- */
var _planTimer = null;

function planRow(it){
  var h = '<div class="prow" data-w="' + esc(it.w) + '">';
  h += '<span class="t st-a" data-w="' + esc(it.w) + '" style="--c:' +
       it.color + '">' + esc(it.w) + '</span>';
  h += '<div class="pmeta"><div class="pline"><b class="ppy" style="color:' +
       it.color + '">' + esc(it.py || '') + '</b>';
  if (it.def) h += ' <span class="pdef">— ' + esc(it.def) + '</span>';
  h += '</div>';
  if (it.reason)
    h += '<div class="preason">' + esc(it.reason) + '</div>';
  h += '</div></div>';
  return h;
}
/* plan-selector chips: pick which ordering to follow; hover a chip to
   see how that ordering is built */
function renderPlanCtl(){
  // each label + its chips is one flex group, so a wrap moves the whole
  // group to the next line with no stray leading gap
  function grp(label, kind, cur, opts){
    var h = '<span class="mgrp">' + label + ' ';
    opts.forEach(function(p){
      h += '<span class="mchip' + (cur === p[0] ? ' sel' : '') +
           '" title="' + esc(PLAN_TIPS[p[0]]) +
           '" onclick="setPlanOpt(\'' + kind + '\',\'' + p[0] + '\')">' +
           p[1] + '</span>';
    });
    return h + '</span>';
  }
  var h = grp('Word Order:', 'mode', PLAN_MODE,
              [['board', 'Board order'], ['smart', 'Smart order'],
               ['freq', 'Frequency']]);
  if (PLAN_MODE !== 'board')
    h += grp('HSK Order:', 'levels', PLAN_LEVELS,
             [['level', 'In order'], ['blend', 'Mixed']]);
  document.getElementById('plan-ctl').innerHTML = h;
}
/* the same explanations as the chips' hover tips, spelled out in an
   expandable block — hover-only help is easy to never discover */
function togglePlanHelp(){
  var el = document.getElementById('plan-help');
  if (el.style.display === 'block'){ el.style.display = 'none'; return; }
  var h = '';
  [['Board order', 'board'], ['Smart order', 'smart'],
   ['Frequency', 'freq'],
   ['HSK Order: In order', 'level'],
   ['HSK Order: Mixed', 'blend']]
  .forEach(function(p){
    h += '<div class="phrow"><b>' + p[0] + '</b> — ' +
         esc(PLAN_TIPS[p[1]]) + '</div>';
  });
  el.innerHTML = h;
  el.style.display = 'block';
}
function setPlanOpt(kind, val){
  if (kind === 'mode') PLAN_MODE = val;
  else PLAN_LEVELS = val;
  renderPlanCtl();
  if (window.pycmd)
    pycmd('hskplan:' + kind + ':' + val, function(raw){
      setPlan(typeof raw === 'string' ? JSON.parse(raw) : raw);
    });
}
function setPlan(d){
  if (!d) return;
  var h = '';
  d.items.forEach(function(it){ h += planRow(it); });
  document.getElementById('plan-list').innerHTML = h;
}
function togglePlan(){
  var open = document.body.classList.toggle('planopen');
  if (window.pycmd) pycmd('hskpane:' + (open ? '1' : '0'));
  setTimeout(layoutBoard, 230);   // after the slide-in settles
}
/* drag the pane's left edge to resize it; the board re-lays-out once on
   release, not on every mousemove */
var _dragPW = false;
document.addEventListener('mousedown', function(e){
  if (e.target.id !== 'pgrip') return;
  e.preventDefault();
  _dragPW = true;
  document.body.style.userSelect = 'none';
});
document.addEventListener('mousemove', function(e){
  if (!_dragPW) return;
  var w = Math.max(240, Math.min(640, window.innerWidth - e.clientX));
  document.body.style.setProperty('--planw', w + 'px');
});
document.addEventListener('mouseup', function(){
  if (!_dragPW) return;
  _dragPW = false;
  document.body.style.userSelect = '';
  var w = Math.round(parseFloat(
      getComputedStyle(document.getElementById('plan')).width));
  if (window.pycmd) pycmd('hskpanew:' + w);
  layoutBoard();
});
/* words that just became covered fade out of the list (scrolled into
   view first, so mass card-adding is hands-free), then the whole list
   re-ranks once things settle */
function planPatch(changed, plan){
  var list = document.getElementById('plan-list');
  var faded = false;
  var gone = {};
  (changed || []).forEach(function(c){
    if (c.status > 0) gone[c.w] = true;
  });
  var rows = list.querySelectorAll('.prow:not(.fadeout)');
  for (var i = 0; i < rows.length; i++){
    if (gone[rows[i].dataset.w]){
      if (!faded)
        rows[i].scrollIntoView({block:'center', behavior:'smooth'});
      rows[i].classList.add('fadeout');
      faded = true;
    }
  }
  clearTimeout(_planTimer);
  _planTimer = setTimeout(function(){ setPlan(plan); }, faded ? 1100 : 0);
}

var _lt = null;
window.addEventListener('resize', function(){
  clearTimeout(_lt);
  _lt = setTimeout(function(){
    // only a changed *width* needs a re-layout; height-only resize
    // events (scrollbar flicker, 1px window creep) must not trigger a
    // full board rebuild or they can cascade into a relayout storm
    var board = document.getElementById('board');
    var W = board.clientWidth || document.body.clientWidth - 36;
    if (window.pycmd)
      pycmd('hsklog:js-resize ' + window.innerWidth + 'x' +
            window.innerHeight + ' boardW=' + W);
    if (W !== _lastW) layoutBoard();
  }, 120);
});
window.addEventListener('DOMContentLoaded', function(){
  layoutBoard();
  renderPlanCtl();
  setPlan(INITIAL_PLAN);
  if (SHOW_INTRO) showIntro(0);
});

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
    document.getElementById('sum-rev').textContent = d.summary.reviewed;
    document.getElementById('sum-cov').textContent = d.summary.covered;
    document.getElementById('sum-covpct').textContent = d.summary.covpct;
  }
}
function applyPatch(raw){
  var d = (typeof raw === 'string') ? JSON.parse(raw) : raw;
  setTileStatus(d.word, d.status);
  updateHeaders(d);
  if (d.plan) planPatch([{w: d.word, status: d.status}], d.plan);
}
function applyBulkPatch(raw){
  var d = (typeof raw === 'string') ? JSON.parse(raw) : raw;
  (d.words || []).forEach(function(w){ setTileStatus(w.w, w.status); });
  updateHeaders(d);
  if (d.plan) planPatch(d.words || [], d.plan);
}

/* ---- info modal ---- */
var _curWord = null;

function requestInfo(w){
  if (window.pycmd) pycmd('hskinfo:' + w, showInfo);
  else if (window.PREVIEW_INFO && PREVIEW_INFO[w]) showInfo(PREVIEW_INFO[w]);
}

/* step to the previous/next word (arrow keys or the on-screen ‹ ›),
   walking the tiles in board order, filtered by NAV_MODE; the word the
   card currently shows is always part of the cycle so navigation works
   from any starting point */
function navMatch(t){
  if (NAV_MODE === 'unknown') return t.classList.contains('st-a');
  if (NAV_MODE === 'covered')
    return t.classList.contains('st-r') || t.classList.contains('st-d');
  return true;
}
function navInfo(dir){
  if (!_curWord) return;
  var tiles = document.querySelectorAll('.t[data-w]');
  var words = [];
  for (var i = 0; i < tiles.length; i++){
    if (tiles[i].dataset.w === _curWord || navMatch(tiles[i]))
      words.push(tiles[i].dataset.w);
  }
  var at = words.indexOf(_curWord);
  if (at < 0 || words.length < 2) return;
  requestInfo(words[(at + dir + words.length) %% words.length]);
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
function hideInfo(){
  _curWord = null;
  var ov = document.getElementById('ov');
  if (ov.classList.contains('show') && window.pycmd)
    pycmd('hsklog:card-close');
  ov.classList.remove('show');
}
function showInfo(raw){
  var d = (typeof raw === 'string') ? JSON.parse(raw) : raw;
  _curWord = d.word;
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

/* ---- options popup (same card styling as the info modal) ---- */
function hideOptions(){
  document.getElementById('oov').classList.remove('show');
}
function showOptions(){
  var o = document.getElementById('opts');
  var h = '<button class="x" onclick="hideOptions()" title="close">×</button>';
  h += '<div class="ttl">Options</div>';
  h += '<div class="sec">Arrow keys cycle through</div>';
  // plain buttons, not a <select>: QtWebEngine's native select popup
  // misrenders on macOS (blank list, runaway window growth)
  h += '<div class="btns">';
  [['all', 'All words'],
   ['unknown', 'Unknown words only'],
   ['covered', 'Reviewed &amp; in-deck words']].forEach(function(p){
    h += '<button class="' + (NAV_MODE === p[0] ? 'st-deck' : '') + '" ' +
         'onclick="setNavMode(\'' + p[0] + '\')">' + p[1] + '</button>';
  });
  h += '</div>';
  h += '<div class="sec">Known-words database</div>';
  h += '<div class="path">' + esc(KNOWN_PATH) + '</div>';
  h += '<div class="btns">' +
       '<button onclick="opt(\'reveal\')">Show in folder</button>' +
       '<button onclick="opt(\'pick\')">Use existing file…</button>' +
       '<button onclick="opt(\'move\')">Move to new file…</button></div>';
  h += '<div class="sec">Debugging</div>';
  h += '<div class="btns"><button onclick="opt(\'debug\')">' +
       'Show debug log in folder</button></div>';
  h += '<div class="sec">Help</div>';
  h += '<div class="btns"><button onclick="hideOptions();showIntro(0)">' +
       'Show the intro tour</button></div>';
  o.innerHTML = h;
  document.getElementById('oov').classList.add('show');
}
function setNavMode(v){
  NAV_MODE = v;
  if (window.pycmd) pycmd('hsknav:' + v);
  showOptions();   // re-render so the selected button highlights
}
function opt(action){
  if (window.pycmd) pycmd('hskopt:' + action);
}

/* ---- intro tour (shown once on first start; reopen from Options) ---- */
var INTRO = [
  {t: 'Welcome to the HSK Coverage Map',
   b: 'Every official HSK word is a tile, so you can see your whole ' +
      'deck\'s coverage at a glance:<br><br>' +
      '<span class="t st-r" style="background:#94a3b8;color:#fff">爱</span> ' +
      'reviewed, or marked known<br>' +
      '<span class="t st-d" style="border-color:#94a3b8">爱</span> ' +
      'in your deck, not yet reviewed<br>' +
      '<span class="t st-a">爱</span> not in your deck'},
  {t: 'Point it at your deck',
   b: 'At the top, pick your <b>deck</b>, the <b>field</b> that holds ' +
      'the Chinese word, and which HSK <b>word list</b> to measure ' +
      'against. Matching is forgiving: a field like 爱 (ài) still ' +
      'counts as 爱, and traditional characters match too. Use ' +
      '<b>Rescan deck</b> after editing notes outside the map.'},
  {t: 'Explore the words',
   b: 'Click any tile for pinyin, meanings and the traditional form, ' +
      'then walk the board with the <b>← / →</b> keys. ' +
      '<b>Right-click</b> a tile to mark a word you already know — it ' +
      'fills in and counts, no Anki card needed.'},
  {t: 'Follow a study plan',
   b: 'The <b>Study plan</b> button lists every word you don\'t know ' +
      'yet, in a suggested order: the board order, or a smart ranking ' +
      'that blends word frequency, characters you already know, and ' +
      'what each word unlocks. Add cards in Anki with the map open and ' +
      'rows tick themselves off the list.'},
  {t: 'Offline, and yours',
   b: 'After a one-time dictionary download everything works offline. ' +
      'The <b>Options</b> button sets what the arrow keys cycle ' +
      'through and where your known-words list is stored, and can ' +
      'reopen this tour any time. Zoom with Cmd/Ctrl + and −. 加油!'},
];
var _introAt = 0;
function showIntro(i){
  _introAt = Math.max(0, Math.min(INTRO.length - 1, i));
  var p = INTRO[_introAt];
  var h = '<button class="x" onclick="hideIntro()" title="close">×</button>';
  h += '<div class="ttl">' + p.t + '</div>';
  h += '<div class="ibody">' + p.b + '</div>';
  h += '<div class="idots">';
  for (var k = 0; k < INTRO.length; k++)
    h += '<i class="' + (k === _introAt ? 'on' : '') + '"></i>';
  h += '</div>';
  h += '<div class="btns" style="justify-content:center">';
  if (_introAt > 0) h += '<button onclick="introGo(-1)">Back</button>';
  h += (_introAt < INTRO.length - 1)
      ? '<button class="st-deck" onclick="introGo(1)">Next</button>'
      : '<button class="st-deck" onclick="hideIntro()">Get started</button>';
  h += '</div>';
  document.getElementById('intro').innerHTML = h;
  document.getElementById('iov').classList.add('show');
}
function introGo(d){ showIntro(_introAt + d); }
function hideIntro(){
  var el = document.getElementById('iov');
  if (!el.classList.contains('show')) return;
  el.classList.remove('show');
  if (window.pycmd) pycmd('hskintro:done');
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
               night=False, collapsed_levels=(), extra_js="",
               nav_mode="all", known_file="", plan=None, plan_open=False,
               plan_mode="smart", plan_levels="blend", show_intro=False,
               plan_width=332):
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
    # the headline percentage is words actually reviewed (or marked
    # known); the matched count alongside includes unreviewed cards
    pct = 100.0 * reviewed / total if total else 0.0
    covpct = 100.0 * covered / total if total else 0.0
    plan_width = max(240, min(640, int(plan_width or 332)))

    # hover explanations for the plan-selector chips (weights come from
    # plan.py so they never drift; keep the text free of double quotes —
    # it lands in a title attribute)
    plan_tips = {
        "board": "The same order as the gray tiles on the board: level by "
                 "level, single-character words first, then the official "
                 "HSK list order.",
        "smart": "Weighted blend of four signals: frequency %d%% (how "
                 "common the word is in everyday Chinese, from corpus "
                 "data), known parts %d%% (how many of its characters you "
                 "already know), unlocks %d%% (how many other unknown HSK "
                 "words share its characters), level %d%% (earlier levels "
                 "get a boost). Best score first; the gray note under "
                 "each word names the signals that apply."
                 % tuple(round(w * 100)
                         for w in (W_FREQ, W_COMP, W_UNLOCK, W_LEVEL)),
        "freq": "Purely by corpus frequency: the most common words in "
                "everyday Chinese first, regardless of HSK level.",
        "level": "Strictly increasing HSK level: all of one level before "
                 "any of the next, keeping the selected word order within "
                 "each level.",
        "blend": "All levels compete at once, ranked purely by the "
                 "selected word order. In Smart order a lower HSK level "
                 "still contributes %d%% of the score, nudging "
                 "early-level words ahead when words are otherwise equal."
                 % round(W_LEVEL * 100),
    }

    js = JS % {"colors": json.dumps(LEVEL_COLORS),
               "nav_mode": json.dumps(nav_mode),
               "known_path": json.dumps(known_file),
               "plan": json.dumps(plan),
               "plan_mode": json.dumps(plan_mode),
               "plan_levels": json.dumps(plan_levels),
               "plan_tips": json.dumps(plan_tips),
               "show_intro": json.dumps(bool(show_intro))}

    return """<!doctype html><html><head><meta charset="utf-8">
<style>%s</style></head>
<body class="%s" style="--planw:%dpx">
  <div class="summary">
    <span class="big" id="sum-pct">%.1f%%</span>
    <span class="sub"><b id="sum-rev">%d</b> of <b>%d</b> %s 1–6 words
      reviewed or marked known · <b id="sum-cov">%d</b>
      (<span id="sum-covpct">%.1f%%</span>) matched in deck</span>
    <button class="planbtn" onclick="togglePlan()">Study plan</button>
  </div>
  <div class="board" id="board">%s</div>
  <div id="plan">
    <div id="pgrip" title="drag to resize"></div>
    <div class="phead"><b>Study plan</b>
      <span class="mchip ihelp" onclick="togglePlanHelp()"
        title="what do these settings mean?">i</span></div>
    <div class="pmethod" id="plan-ctl"></div>
    <div id="plan-help"></div>
    <div id="plan-list"></div>
  </div>
  <div class="legend">
    <span><span class="t st-r" style="background:#94a3b8;color:#fff">爱</span>
      reviewed, or marked known</span>
    <span><span class="t st-d" style="border-color:#94a3b8">爱</span>
      in deck, not yet reviewed</span>
    <span><span class="t st-a">爱</span> not in deck</span>
    <span>hover to zoom · click for details (←/→ to browse) · right-click
      to mark a word you already know</span>
    <span class="hint" title="Within each panel: single-character words
      first, then multi-character words — each group in official HSK
      list order.">tile order</span>
  </div>
  <div id="ov">
    <button class="nav" onclick="navInfo(-1)" title="previous word">‹</button>
    <div id="card" class="card"></div>
    <button class="nav" onclick="navInfo(1)" title="next word">›</button>
  </div>
  <div id="oov"><div id="opts" class="card"></div></div>
  <div id="iov"><div id="intro" class="card"></div></div>
  <script>%s%s</script>
</body></html>""" % (
        CSS,
        " ".join(filter(None, ["night" if night else "",
                               "planopen" if plan_open else ""])),
        plan_width,
        pct, reviewed, total,
        html_mod.escape(version_label),
        covered, covpct,
        panels, js, extra_js,
    )
