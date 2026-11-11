"""The panel's look (docs/v2/panel.md, owner 11-04): three levels, home (every task) → a task → a cycle, drawn from the model
bitt.panel.data reads. Layout, lines, shape and colour carry the meaning; words only confirm. Pure: model dict in, HTML string out;
links through `Links`, so the live server (`bitt serve`) and a static snapshot (scripts/viz_evals.py) draw the same pages."""
import html
from pathlib import Path

e = html.escape

CSS = """<style>
:root{--paper:#faf9f6;--ink:#1d2127;--quiet:#8b929c;--rule:#e3e1db;--tile:#f0eee8;--work:#0f8a96;--wait:#d98a00;--person:#c2255c;--ok:#2b8a3e;--bad:#d9302c;--vio:#6741d9}
@media (prefers-color-scheme:dark){:root{--paper:#14161a;--ink:#e8e6e1;--quiet:#7d8590;--rule:#2a2e35;--tile:#1e2228;--work:#3bc0cc;--wait:#f0a928;--person:#f06595;--ok:#51cf66;--bad:#ff6b6b;--vio:#9775fa}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:14px 16px 60px}a{color:inherit;text-decoration:none}
.crumb{display:flex;gap:8px;font-size:13px;color:var(--quiet);margin-bottom:10px}.crumb a:hover{color:var(--ink)}
h1{margin:0;font-size:24px;letter-spacing:-.01em}h2{margin:30px 0 10px;font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--quiet)}
.q{font-size:20px;margin:6px 0 2px;max-width:40ch}.mute{color:var(--quiet)}.num{font-variant-numeric:tabular-nums}
/* tiles: one square per cycle; fill and edge say the state */
.tile{position:relative;display:inline-grid;place-items:center;width:30px;height:30px;border-radius:7px;font-size:12px;font-weight:600;border:2px solid var(--quiet);color:var(--quiet);background:transparent;flex:none}
.tile.EXPLORE{border:2px dashed var(--work);color:var(--work)}.tile.FRAME,.tile.WORK{background:var(--work);border-color:var(--work);color:var(--paper)}
.tile.JUDGE,.tile.ACT{background:var(--wait);border-color:var(--wait);color:var(--paper)}.tile.CLOSED{border-color:var(--ok);color:var(--ok)}
.tile.CLOSED::before{content:"";position:absolute;inset:auto 3px 3px auto;width:6px;height:3px;border-left:2px solid var(--ok);border-bottom:2px solid var(--ok);transform:rotate(-45deg) translate(-1px,-1px)}
.tile.PARKED{border-color:var(--rule);color:var(--rule)}
.tile.person{box-shadow:0 0 0 3px var(--paper),0 0 0 5px var(--person)}
.tile.fail::after{content:"";position:absolute;top:-6px;right:-6px;border:7px solid transparent;border-bottom-color:var(--bad);border-right-color:var(--bad);border-radius:2px}
.tile.train{background-image:repeating-linear-gradient(135deg,transparent 0 5px,rgba(255,255,255,.35) 5px 10px);background-size:28px 28px;animation:slide 1.6s linear infinite}
@keyframes slide{to{background-position:28px 0}}
.tile.lg{width:44px;height:44px;border-radius:10px;font-size:16px}
/* the live pulse: what just changed flashes a ring that hugs its own edge and spreads a fixed 6px (never scaled: a wide row grows
   as little as a tile), three times; a cycle waiting on you (.nag) keeps breathing */
.pulse{animation:halo 1.4s ease-out 3}.nag{animation:halo 2.4s ease-out infinite}
@keyframes halo{0%{outline:2px solid var(--vio);outline-offset:0}100%{outline:2px solid transparent;outline-offset:6px}}
@keyframes ring{0%{opacity:.9;transform:scale(.9)}100%{opacity:0;transform:scale(1.35)}}
/* the last check: a dot that blinks on each check, red when the store did not answer */
.chk{position:fixed;right:12px;bottom:10px;display:flex;gap:6px;align-items:center;font-size:12px;color:var(--quiet);background:var(--paper);padding:3px 9px;border:1px solid var(--rule);border-radius:11px;font-variant-numeric:tabular-nums}
.chk i{width:7px;height:7px;border-radius:50%;background:var(--ok)}.chk.bad i{background:var(--bad)}.chk.bad{color:var(--bad)}.chk.tick i{animation:blink .7s ease-out}
@keyframes blink{0%{transform:scale(1.8)}100%{transform:scale(1)}}
.blip{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--vio);position:relative}.blip::after{content:"";position:absolute;inset:-4px;border-radius:50%;border:2px solid var(--vio);animation:ring 2.4s ease-out infinite}
@media (prefers-reduced-motion:reduce){.pulse,.nag,.blip::after,.tile.train,.chk i{animation:none}}
/* home: one lane per task */
.lane{display:grid;grid-template-columns:170px 1fr 130px;gap:14px;align-items:center;padding:14px 12px 14px 16px;border-bottom:1px solid var(--rule);position:relative}
.lane::before{content:"";position:absolute;left:0;top:10px;bottom:10px;width:4px;border-radius:2px;background:var(--rule)}
.lane.you::before{background:var(--person)}.lane.busy::before{background:var(--work)}
.lane:hover{background:var(--tile)}.lane .nm{font-weight:650;font-size:17px;display:flex;gap:8px;align-items:center}
.lane .tiles{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.badge{display:inline-grid;place-items:center;min-width:22px;height:22px;border-radius:11px;padding:0 6px;font-size:12px;font-weight:700;color:var(--paper)}
.badge.you{background:var(--person)}.badge.wait{background:var(--wait)}.okmark{color:var(--ok);font-weight:700}
.lane .last{grid-column:2 / 4;font-size:12.5px;color:var(--quiet);margin-top:-6px}
.spark{display:block}.spark rect{fill:var(--quiet);opacity:.55}.spark rect.hot{fill:var(--work);opacity:1}
@media (max-width:640px){.lane{grid-template-columns:1fr auto}.lane .tiles{grid-column:1 / 3;order:3}.lane .last{grid-column:1 / 3}}
/* task: attention stack + rail */
.att{display:grid;gap:8px}.att a{display:block;padding:10px 14px;border-radius:8px;background:var(--tile);border-left:5px solid var(--quiet)}
.att .you{border-color:var(--person)}.att .problem{border-color:var(--bad)}.att .waiting{border-color:var(--wait)}
.att code{display:block;font-size:12px;color:var(--quiet);margin-top:2px;overflow-wrap:anywhere}.att .k{display:flex;gap:10px;align-items:baseline}
.att .who{display:inline-block;width:11px;height:11px;border-radius:50%;background:var(--person);flex:none;transform:translateY(1px)}
.att .problem .who{border-radius:0;background:var(--bad);clip-path:polygon(50% 0,100% 100%,0 100%)}.att .waiting .who{background:none;border:3px solid var(--wait);border-top-color:transparent;animation:spin 1.6s linear infinite}
@keyframes spin{to{transform:rotate(1turn)}}
.cols{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:28px}@media (max-width:820px){.cols{grid-template-columns:minmax(0,1fr)}}
.strip{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap}.strip a{display:grid;gap:6px;justify-items:center;width:150px;padding:10px 8px;border-radius:10px;background:var(--tile)}
.strip .qq{font-size:12.5px;text-align:center;line-height:1.25}.strip .v{font-size:11px;color:var(--ok)}
/* track: four stations, a marker where the cycle is */
.track{display:flex;align-items:center;gap:0;margin:14px 0 4px;max-width:420px}.track i{width:18px;height:18px;border-radius:50%;border:2px solid var(--quiet);flex:none;background:var(--paper)}
.track b{height:3px;flex:1;background:var(--rule)}.track .on{background:var(--work);border-color:var(--work)}.track .here{box-shadow:0 0 0 4px var(--paper),0 0 0 6px currentColor}
.track.s-JUDGE .on,.track.s-ACT .on{background:var(--wait);border-color:var(--wait)}.track.s-CLOSED i{background:var(--ok);border-color:var(--ok)}.track.s-CLOSED b{background:var(--ok)}
.track.s-EXPLORE i{border-style:dashed;border-color:var(--work)}.track.s-EXPLORE b{background:repeating-linear-gradient(90deg,var(--work) 0 5px,transparent 5px 10px);height:2px}
.track .bl{background:var(--work)}.track.s-JUDGE .bl,.track.s-ACT .bl{background:var(--wait)}
.ladders{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:18px 16px}
.stk{position:relative;padding:0 calc(var(--l) * 5px) calc(var(--l) * 5px) 0}.stk .ly{position:absolute;inset:0;border:1.5px solid var(--rule);border-radius:10px;background:var(--tile)}
.stk .ly:nth-child(1){transform:translate(calc(var(--l) * 5px),calc(var(--l) * 5px));inset:0 calc(var(--l) * 5px) calc(var(--l) * 5px) 0}
.stk .ly:nth-child(2){transform:translate(calc((var(--l) - 1) * 5px),calc((var(--l) - 1) * 5px));inset:0 calc(var(--l) * 5px) calc(var(--l) * 5px) 0}
.stk .ly:nth-child(3){transform:translate(calc((var(--l) - 2) * 5px),calc((var(--l) - 2) * 5px));inset:0 calc(var(--l) * 5px) calc(var(--l) * 5px) 0}
.stk .ly:nth-child(4){transform:translate(calc((var(--l) - 3) * 5px),calc((var(--l) - 3) * 5px));inset:0 calc(var(--l) * 5px) calc(var(--l) * 5px) 0}
.stk .ly.ghost{background:none;border:1.5px dashed var(--bad)}
.cd{position:relative;background:var(--tile);border:1.5px solid var(--rule);border-radius:10px;padding:9px 12px 12px;overflow:hidden;font-size:12px}
.cd .hd{display:flex;justify-content:space-between;gap:8px;font-size:13.5px}.cd .hd b{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cd .mute{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.cd .ft{position:absolute;left:0;right:0;bottom:0;height:4px;display:flex;background:var(--rule)}
.cd .ft .m{background:var(--ok)}.cd .ft .f{background:var(--bad)}.cd.bad{border-color:var(--bad)}
.cd.running .ft{background-image:repeating-linear-gradient(45deg,transparent 0 5px,color-mix(in srgb,var(--work) 45%,transparent) 5px 10px)}
.pan{position:relative;border:1px solid var(--rule);border-radius:10px;background:var(--paper)}.pan .vp{overflow:auto;max-height:72vh;cursor:grab;touch-action:none}.pan .vp.drag{cursor:grabbing;user-select:none}
.zm{position:absolute;right:8px;top:8px;display:flex;gap:4px;z-index:1}.zm button{font:inherit;font-size:12px;min-width:28px;height:24px;border:1px solid var(--rule);border-radius:6px;background:var(--tile);color:var(--ink);cursor:pointer}
.pan svg{display:block}.pan text{font:12px system-ui,sans-serif;fill:var(--ink)}.pan text.l1{font-weight:600}.pan text.l3{fill:var(--quiet)}.pan text.inv{fill:var(--paper)}
.pan .el{fill:var(--quiet);font-size:11px}.pan .ed{fill:none;stroke:var(--quiet);stroke-width:1.5}.pan .tip{fill:var(--quiet)}
.pan .n{fill:var(--tile);stroke:var(--ink);stroke-width:2}.pan .n.step{stroke:var(--work)}.pan .n.decision{stroke:var(--vio)}.pan .n.model{fill:var(--vio);stroke:var(--vio)}
.pan .n.raw{stroke-width:4}.pan .n.ext{fill:none;stroke:var(--quiet);stroke-dasharray:5 4}.pan a.ext:hover .n{stroke:var(--ink)}.pan .nt{fill:var(--wait)}.pan .cb{fill:var(--ink)}.pan text.cbt{fill:var(--paper);font-size:11px;font-weight:700}.pan .n.deck{opacity:.55}.pan .dm{fill:var(--vio)}
.par{display:grid;gap:8px}.par a{display:grid;grid-template-columns:auto minmax(0,1fr) 220px;gap:14px;align-items:center;padding:10px 12px;border-radius:10px;background:var(--tile);color:inherit;text-decoration:none}
.par .qq{font-size:13.5px;line-height:1.3}.par .track{margin:0;max-width:none}.par .track i{width:13px;height:13px}
.par .prog{grid-column:2/4}.done{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;align-items:center}.done a{opacity:.75}.done a:hover{opacity:1}
@media(max-width:640px){.par a{grid-template-columns:auto minmax(0,1fr)}.par .track{grid-column:1/3}}
details.fold>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:10px;margin:30px 0 10px}details.fold>summary::-webkit-details-marker{display:none}
details.fold>summary h2{margin:0}details.fold>summary .chev{width:8px;height:8px;border-right:2px solid var(--quiet);border-bottom:2px solid var(--quiet);transform:rotate(-45deg);transition:transform .15s}
details.fold[open]>summary .chev{transform:rotate(45deg)}.mini{display:flex;gap:3px;align-items:center}.mini i{width:10px;height:10px;border:2px solid var(--ink);border-radius:2px;background:var(--tile)}
.mini i.step{border-color:var(--work);border-radius:4px}.mini i.decision{border-color:var(--vio);transform:rotate(45deg) scale(.8)}.mini i.model{background:var(--vio);border-color:var(--vio)}.mini i.raw{border-width:3px}.mini i.ext{border:2px dashed var(--quiet);border-radius:4px}
.stations{display:flex;max-width:420px;justify-content:space-between;font-size:11px;color:var(--quiet)}
/* shelf */
.shelf{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}.item{padding:12px;border-radius:10px;background:var(--tile)}
.shape{display:inline-block;width:26px;height:26px;border:2.5px solid var(--ink);vertical-align:middle;margin-right:8px;position:relative}
.shape.dataset{border-radius:3px}.shape.evalset{border-radius:3px}.shape.evalset::after{content:"";position:absolute;left:2px;right:2px;top:50%;border-top:2.5px dashed var(--ink)}
.shape.model{border:0;background:var(--vio);clip-path:polygon(25% 5%,75% 5%,100% 50%,75% 95%,25% 95%,0 50%)}
.shape.raw{border-radius:3px;border-style:double;border-width:5px}
.vers{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;align-items:center}.pill{font-size:12px;padding:1px 9px;border-radius:10px;border:1.5px solid var(--ink);font-variant-numeric:tabular-nums}
.pill.alias{border-style:dashed;border-color:var(--vio);color:var(--vio)}.pill+.pill:before{content:none}.appr{width:16px;height:16px;border-radius:50%;background:var(--ok);display:inline-grid;place-items:center;float:right}
.appr::after{content:"";width:6px;height:3px;border-left:2px solid var(--paper);border-bottom:2px solid var(--paper);transform:rotate(-45deg) translate(1px,-1px)}
.rows{font-size:12px;color:var(--quiet);margin-left:34px}
/* ladder: rung length is the size of the run */
.ladder{display:grid;gap:7px;max-width:520px}.rung{display:grid;grid-template-columns:52px 1fr 70px;gap:10px;align-items:center;font-size:12px;color:var(--quiet)}
.bar{height:14px;border-radius:4px;display:flex;overflow:hidden;background:transparent}.bar .m{background:var(--ok);opacity:.85}.bar .f{background:var(--bad)}
.bar.running .m{background:repeating-linear-gradient(135deg,var(--work) 0 6px,color-mix(in srgb,var(--work) 55%,transparent) 6px 12px);background-size:34px 34px;animation:slide 1.6s linear infinite}
.bar .rest{flex:1;border:1.5px dashed var(--rule);border-left:0;border-radius:0 4px 4px 0}
/* arms: rows are arms, columns the data; each cell an interval on a 0-1 line */
.tbl{overflow-x:auto}table.arms{border-collapse:collapse}table.arms th{font-weight:500;font-size:12px;color:var(--quiet);text-align:left;padding:4px 14px 8px 10px}
table.arms td{padding:8px 14px 8px 10px;border-top:1px solid var(--rule);vertical-align:middle}table.arms td.arm{font-weight:600;min-width:150px}
tr.split td.arm{box-shadow:inset 4px 0 0 var(--bad)}.cell{display:flex;align-items:center;gap:8px;font-size:12px}.cell svg{overflow:visible}.cell .won{color:var(--ok)}.cell .lost{color:var(--bad)}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:7px;border:2px solid var(--quiet)}.dot.filled{border-color:var(--work)}.dot.measured{background:var(--ok);border-color:var(--ok)}
.dot.running{border:2px solid var(--work);border-top-color:transparent;animation:spin 1.6s linear infinite}
.judge{font-size:12px;color:var(--quiet);margin:0 0 6px}
.banner{display:flex;gap:10px;align-items:center;padding:10px 14px;border-radius:8px;border:2px solid var(--person);margin:14px 0;max-width:560px}.banner .who{width:12px;height:12px;border-radius:50%;background:var(--person);flex:none}
.banner code{font-size:12px;color:var(--quiet)}
/* train */
.prog{height:10px;border-radius:5px;background:var(--rule);overflow:hidden;max-width:360px}.prog i{display:block;height:100%;background:var(--work)}
/* flow: left to right, columns are steps in time */
.flow{overflow-x:auto}.flow text{font:12px system-ui,sans-serif;fill:var(--ink)}.flow .sub{fill:var(--quiet);font-size:11px}.flow path{fill:none;stroke:var(--quiet);stroke-width:1.6}
.flow .n{fill:var(--tile);stroke:var(--ink);stroke-width:2}.flow .n.step{stroke:var(--work)}.flow .n.decision{stroke:var(--vio)}.flow .n.model{fill:var(--vio);stroke:var(--vio)}.flow .n.raw{stroke-width:4}
/* timeline rail */
.rail{position:relative;margin:0;padding:0 0 0 22px;list-style:none}.rail::before{content:"";position:absolute;left:6px;top:4px;bottom:4px;width:2px;background:var(--rule)}
.rail li{position:relative;padding:3px 0 3px 8px;font-size:13.5px}.rail li.day{font-size:11px;letter-spacing:.06em;color:var(--quiet);padding-top:12px}
.rail .mk{position:absolute;left:-21px;top:9px;width:11px;height:11px;background:var(--quiet);border-radius:50%}
.rail .run .mk{background:var(--work)}.rail .decision .mk{background:var(--vio);border-radius:2px;transform:rotate(45deg)}.rail .tag .mk{background:var(--ok);border-radius:2px}
.rail .plan .mk{background:var(--paper);border:2.5px solid var(--person)}.rail .cycle .mk{width:13px;height:13px;left:-22px;border-radius:3px;background:var(--ink)}
.rail .validation .mk,.rail .outcome .mk{background:var(--ok)}.rail .refusal .mk{background:var(--bad);border-radius:0;clip-path:polygon(50% 0,100% 100%,0 100%)}
.rail .refusal{color:var(--bad)}.rail .usr{font-weight:550}.rail .t{color:var(--quiet);font-variant-numeric:tabular-nums;margin-right:6px;font-size:12px}
.rail .cy{display:inline-grid;place-items:center;min-width:18px;height:18px;border-radius:5px;border:1.5px solid var(--quiet);font-size:10.5px;color:var(--quiet);margin-right:6px}
.rail .changed .mk{box-shadow:0 0 0 3px var(--paper),0 0 0 5px var(--vio)}
.rail .stacked .mk{z-index:0}.rail .stacked .mk::after{content:"";position:absolute;inset:0;border-radius:inherit;background:inherit;opacity:.45;transform:translate(3px,-3px);z-index:-1}
/* the inspector: a rail line, a graph box, a run card or a shelf item opens its node in a drawer on the right (served pages only) */
[data-n]{cursor:pointer}.rail li[data-n]:hover,.item[data-n]:hover{background:var(--tile)}.pan .bx[data-n]:hover .n{stroke-width:3}
.sel{outline:2px solid var(--vio);outline-offset:2px;border-radius:6px}.pan .bx.sel .n{stroke:var(--vio);stroke-width:3}
.ins{position:fixed;top:0;right:0;bottom:0;width:min(540px,100vw);background:var(--paper);border-left:1px solid var(--rule);box-shadow:-10px 0 28px rgba(0,0,0,.14);overflow:auto;padding:12px 16px 48px;z-index:5;font-size:13px}
.ins[hidden]{display:none}.ins .ih{display:flex;gap:8px;align-items:center;font-size:16px}.ins .ih b{flex:1;overflow-wrap:anywhere}
.ins button{font:inherit;font-size:12px;min-width:26px;height:24px;border:1px solid var(--rule);border-radius:6px;background:var(--tile);color:var(--ink);cursor:pointer}
.ins .id{display:block;font-size:11.5px;color:var(--quiet);overflow-wrap:anywhere;margin:4px 0}.ins h2{margin:18px 0 6px}
.ins .ln{display:grid;grid-template-columns:70px minmax(0,1fr) auto;gap:8px;padding:3px 6px;border-radius:5px}.ins .ln:hover{background:var(--tile)}
.ins .ln .r{color:var(--quiet);overflow:hidden;text-overflow:ellipsis}.ins .ln .t{color:var(--quiet);font-size:11.5px;font-variant-numeric:tabular-nums}
.ins pre{margin:0;padding:8px 10px;background:var(--tile);border-radius:6px;font-size:11.5px;overflow:auto;max-height:340px;white-space:pre-wrap;overflow-wrap:anywhere}
.ins .qh{display:flex;justify-content:space-between;align-items:center;margin:10px 0 3px;color:var(--quiet)}.ins .err{color:var(--bad)}
</style>"""

STATIONS = ["FRAME", "WORK", "JUDGE", "ACT"]


class Links:
    """Where a page lives. Static files by default (one folder per store); the server passes its own."""

    def __init__(self, home="index.html", task="task_{t}.html", cycle="cycle_{t}_{n}.html", seq=None, node=None):
        self._h, self._t, self._c, self.seq, self.node = home, task, cycle, seq, node    # node: the inspector's URL (__N__ = the id)

    def home(self):
        return self._h

    def task(self, t):
        return self._t.format(t=t)

    def cycle(self, t, n):
        return self._c.format(t=t, n=n)


L = Links()


def dn(nid):
    """The attribute that opens a node in the inspector (served pages only: a snapshot has no server to ask)."""
    return f" data-n='{e(nid)}'" if L.node and nid else ""


def page(title, purpose, crumbs, body, seq=None):
    """A whole page; with a seq URL (live), the page asks it every few seconds and redraws in place when the store changed."""
    nav = "".join(f"<a href='{h}'>{e(t)}</a><span>/</span>" for h, t in crumbs)
    live = live_js(L.seq, seq) if L.seq else ""
    live += f"<aside class='ins' id='ins' hidden data-url='{e(L.node)}'></aside>{INS_JS}" if L.node else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="report:purpose" content="{e(purpose)}"><title>{e(title)}</title>{CSS}</head>'
            f"<body><main>{('<div class=crumb>' + nav + '</div>') if crumbs else ''}{body}</main>{AGO_JS}{live}</body></html>\n")


def ago(last):
    """A live age (the page's clock ticks it), or the sample's words."""
    return f"<span data-at='{last['at']}'></span>" if last.get("at") else e(last.get("ago", ""))


def yous(t):
    return sum(1 for n in t["needs"] if n["kind"] in ("you", "problem"))


def tile(t, c, big=False, link=True, pulse=False):
    cls = ["tile", c["state"]]
    cls += ["person"] if c.get("planWaiting") else []
    cls += ["fail"] if c.get("failed") else []
    cls += ["train"] if c.get("train") else []
    cls += ["lg"] if big else []
    cls += ["nag"] if pulse else []
    sq = f" data-seq='{c['seq']}'" if c.get("seq") else ""
    inner = f"<span class='{' '.join(cls)}'{sq}>{c['n']}</span>"
    return f"<a href='{L.cycle(t['name'], c['n'])}'>{inner}</a>" if link else inner


def spark(vals):
    mx = max(max(vals), 1)
    bars = "".join(f"<rect class='{'hot' if i >= len(vals) - 2 and v else ''}' x='{i * 9}' y='{24 - 24 * v / mx:.1f}' width='6' height='{max(24 * v / mx, 1.5):.1f}' rx='1'/>"
                   for i, v in enumerate(vals))
    return f"<svg class='spark' width='126' height='26' viewBox='0 0 126 26'>{bars}</svg>"


# ---------------------------------------------------------------- level 1
def home(S):
    lanes = []
    for t in sorted(S["tasks"], key=lambda t: (-yous(t), t["name"])):
        you = yous(t)
        wait = sum(1 for n in t["needs"] if n["kind"] == "waiting")
        open_ = [c for c in t["cycles"] if c["state"] != "CLOSED"]
        cls = "you" if you else "busy" if open_ else ""
        tiles = "".join(tile(t, c, pulse=t["changed"] and c["planWaiting"] if c.get("planWaiting") else False) for c in t["cycles"])
        badges = (f"<span class='badge you'>{you}</span>" if you else "") + (f"<span class='badge wait'>{wait}</span>" if wait else "") \
            + ("" if you or wait or open_ else "<span class='okmark'>✓</span>")
        blip = "<span class='blip' title='changed'></span>" if t["changed"] else ""
        last = t["last"]
        lanes.append(f"<div class='lane {cls}'{(chr(32) + 'data-seq=' + chr(39) + str(t['seq']) + chr(39)) if t.get('seq') else ''}><div class='nm'><a href='{L.task(t['name'])}'>{e(t['name'])}</a>{blip}{badges}</div>"
                     f"<div class='tiles'>{tiles}</div>{spark(t['activity'])}"
                     f"<div class='last'>{ago(last)} · {e(last['actor'])} · {e(last['text'])}</div></div>")
    lanes = lanes or ["<div class='lane'><div class='nm mute'>no task yet</div></div>"]   # an empty store still draws its home
    return page("bitt", "The panel's home: every task as a lane of cycle tiles, those that need a person on top.",
                [], f"<h1>bitt</h1><div style='margin-top:12px'>{''.join(lanes)}</div>", S.get("seq"))


# ---------------------------------------------------------------- level 2
def ladder_html(lad):
    """One card per step; every earlier run of it (the smoke run, each rung) is a layer stacked behind; the card's foot is the latest
    run: made green, failed red, running striped."""
    if not lad:
        return ""
    if "rungs" not in lad[0]:                                      # the hand sample: one step's rungs
        lad = [{"label": "clean", "kind": "derive", "on": "", "of": None, "rungs": lad}]
    out = []
    for st in lad:
        last = st["rungs"][-1]
        m, f = 100 * last["made"] / last["n"], 100 * last["failed"] / last["n"]
        cls = " bad" if last["status"] == "failed" else " running" if last["status"] == "running" else ""
        layers = min(len(st["rungs"]) - 1, 4)
        ghost = any(r.get("skipped_smoke") for r in st["rungs"])     # the smoke run that never ran: a dashed layer behind
        layers_html = "<i class=ly></i>" * layers + ("<i class='ly ghost' title='no smoke run'></i>" if ghost else "")
        layers += 1 if ghost else 0
        out.append(f"<div class='stk' style='--l:{layers}'{dn(st.get('nid'))}>{layers_html}<div class='cd{cls}'>"
                   f"<div class='hd'><b>{e(st['label'])}</b><span class='num'>{last['made']}<span class='mute'>/{last['n']}</span></span></div>"
                   f"<div class='mute'>{e(st['kind'])}{(' · ' + e(st['on'])) if st.get('on') else ''}</div>"
                   f"<div class='ft'><i class='m' style='width:{m:.1f}%'></i><i class='f' style='width:{f:.1f}%'></i></div></div></div>")
    return f"<div class='ladders'>{''.join(out)}</div>"


def rail(acts, with_cycle=True):
    out, day = [], None
    for a in acts:
        if a["day"] != day:
            day = a["day"]
            out.append(f"<li class='day'>{day}</li>")
        who = "usr" if a["actor"].startswith("usr") else ""
        stk = f" stacked' title='{e(a['after'])}" if a.get("after") else ""   # a smoke run folded in: a layer behind the dot
        out.append(f"<li class='{a['kind']} {who} {'changed' if a.get('changed') else ''}{stk}'{(chr(32) + 'data-seq=' + chr(39) + str(a['seq']) + chr(39)) if a.get('seq') else ''}{dn(a.get('nid'))}><span class='mk'></span>"
                   f"{('<span class=cy>' + str(a['cycle']) + '</span>') if with_cycle and a.get('cycle') else ''}<span class='t'>{a['t']}</span>{e(a['text'])}</li>")
    return f"<ul class='rail'>{''.join(out)}</ul>"


def shelf_html(items):
    out = []
    for it in items:
        vers = "".join(f"<span class='pill'>{v['v']}</span>" + (f"<span class='pill alias'>@{v['alias']}</span>" if v.get("alias") else "") for v in it["versions"])
        rows = f"<span class='rows num'>{it['rows']}</span>" if it["rows"] else ""
        out.append(f"<div class='item'{dn(it.get('nid'))}>{'<span class=appr></span>' if it['approved'] else ''}<span class='shape {it['kind']}'></span>"
                   f"<b>{e(it['name'])}</b>{rows}<div class='vers'>{vers}</div></div>")
    return f"<div class='shelf'>{''.join(out)}</div>"


def task_page(t):
    needs = "".join(f"<a class='{n['kind']}' href='{L.cycle(t["name"], n["cycle"])}'><div class='k'><span class='who'></span><span>{e(n['text'])}</span></div>"
                    f"<code>{e(n['cmd'])}</code></a>" for n in t["needs"])
    def lane(c):
        prog = f"<div class='prog'><i style='width:{c['train']['p'] * 100:.0f}%'></i></div>" if c.get("train") else ""
        return (f"<a href='{L.cycle(t['name'], c['n'])}'>{tile(t, c, link=False, pulse=bool(c.get('planWaiting')) and t['changed'])}"
                f"<span class='qq'>{e(c['question'])}</span>{track(c, names=False)}{prog}</a>")
    open_ = [c for c in t["cycles"] if c["state"] != "CLOSED"]
    closed = [c for c in t["cycles"] if c["state"] == "CLOSED"]
    strip = (f"<div class='par'>{''.join(lane(c) for c in open_)}</div>"
             + (f"<div class='done'>{''.join(tile(t, c) for c in closed)}</div>" if closed else ""))
    body = (f"<h1>{e(t['name'])}</h1><div class='mute'>{e(t['problem'])}</div>"
            f"<h2>Needs you</h2>" + (f"<div class='att'>{needs}</div>" if needs else "<span class='okmark'>✓</span>")
            + f"<h2>Cycles</h2>{strip}"
            + fold("Map", t.get("whole"), "map")
            + (f"<div class='cols'><div><h2>Made here</h2>{shelf_html(t['shelf'])}</div><div><h2>Happened</h2>{rail(t['acts'])}</div></div>"
               if t["shelf"] else f"<h2>Happened</h2>{rail(t['acts'])}"))
    return page(f"bitt: {t['name']}",
                f"The task {t['name']}: what waits on a person, its cycles, its whole map, what exists with versions, what happened.",
                [(L.home(), "bitt")], body + PAN_JS, t.get("seq"))


# ---------------------------------------------------------------- level 3
def interval(c):
    x = lambda v: 4 + 88 * v  # noqa: E731
    col = "var(--ok)" if c["won"] else "var(--bad)"
    return (f"<div class='cell'><svg width='96' height='18' viewBox='0 0 96 18'><line x1='4' y1='9' x2='92' y2='9' stroke='var(--rule)' stroke-width='2'/>"
            f"<line x1='{x(c['lo']):.1f}' y1='9' x2='{x(c['hi']):.1f}' y2='9' stroke='{col}' stroke-width='5' stroke-linecap='round' opacity='.45'/>"
            f"<circle cx='{x(c['rate']):.1f}' cy='9' r='5' fill='{col}'/></svg><span class='{'won' if c['won'] else 'lost'} num'>{c['rate']:.2f}</span>"
            f"<span class='mute num'>{c['n']}</span></div>")


def arms_html(plan):
    cols = plan["cols"]
    head = "".join(f"<th>{e(c)}</th>" for c in cols)
    rows = []
    for a in plan["arms"]:
        won = {a["cells"][c]["won"] for c in cols if c in a["cells"]}
        tds = "".join(f"<td>{interval(a['cells'][c]) if c in a['cells'] else ''}</td>" for c in cols)
        rows.append(f"<tr class='{'split' if len(won) > 1 else ''}'><td class='arm'><span class='dot {a['state']}'></span>{e(a['label'])}</td>{tds}</tr>")
    return (f"<div class='judge'>⚖ {e(plan['judge'])}</div><div class='tbl'><table class='arms'><tr><th></th>{head}</tr>{''.join(rows)}</table></div>")


def flow_html(f, fid="flow"):
    """Left to right: a node's column = its longest way from a source; each column ordered by where its sources sit. A box grows to its
    text (wrapped, never cut); a ladder of runs is one box with a deck behind; an arrow names the columns it fed."""
    import textwrap
    nodes = f["nodes"]
    if not nodes:
        return ""
    LH, PX, CH, GX, GY = 16, 12, 6.6, 96, 22
    text, wid, hgt = {}, {}, {}
    for n in nodes:
        ls = n.get("lines") or [n["label"], n.get("sub", "")]
        out = []
        for i, line in enumerate(x for x in ls if x):
            out += [("l1" if i == 0 else "l3" if i == 2 else "", w) for w in textwrap.wrap(line, 34 if i == 0 else 40)]
        text[n["id"]] = out
        wid[n["id"]] = max(110, 2 * PX + CH * max(len(t) for _, t in out))
        hgt[n["id"]] = max(46, 14 + LH * len(out))
    ups = {}
    for ed in f["edges"]:
        ups.setdefault(ed[1], []).append(ed[0])
    cols = {}
    for n in nodes:
        cols.setdefault(n["col"], []).append(n["id"])
    order = {}
    for c in sorted(cols):
        cols[c].sort(key=lambda x: (sum(order.get(u, 0) for u in ups.get(x, [])) / max(1, len(ups.get(x, []))), x))
        for i, x in enumerate(cols[c]):
            order[x] = i
    colw = {c: max(wid[x] for x in xs) for c, xs in cols.items()}
    colh = {c: sum(hgt[x] for x in xs) + GY * (len(xs) - 1) for c, xs in cols.items()}
    H = max(colh.values()) + 40
    xs_, x = {}, 20
    for c in sorted(cols):
        xs_[c] = x
        x += colw[c] + GX
    W = x - GX + 30
    pos = {}
    for c, ids in cols.items():
        y = 20 + (H - 40 - colh[c]) / 2
        for i in ids:
            pos[i] = (xs_[c] + (colw[c] - wid[i]) / 2, y)
            y += hgt[i] + GY
    shape = {n["id"]: n["shape"] for n in nodes}
    deck = {n["id"]: n.get("rungs", 0) for n in nodes}
    svg = [f"<defs><marker id='ar-{fid}' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto'>"
           "<path d='M0,0 L10,5 L0,10 Z' class='tip'/></marker></defs>"]
    for ed in f["edges"]:
        a_, b_ = ed[0], ed[1]
        (x1, y1), (x2, y2) = pos[a_], pos[b_]
        x1, y1, x2, y2 = x1 + wid[a_] + (8 if deck[a_] > 1 else 0), y1 + hgt[a_] / 2, x2 - 2, y2 + hgt[b_] / 2
        dx = max(30, (x2 - x1) / 2)
        svg.append(f"<path class='ed' d='M{x1:.0f},{y1:.0f} C{x1 + dx:.0f},{y1:.0f} {x2 - dx:.0f},{y2:.0f} {x2:.0f},{y2:.0f}' marker-end='url(#ar-{fid})'/>")
        if len(ed) > 2 and ed[2]:
            svg.append(f"<text class='el' x='{x2 - 8:.0f}' y='{y2 - 7:.0f}' text-anchor='end'>{e(ed[2])}</text>")
    for n in nodes:
        i = n["id"]
        x, y = pos[i]
        r = 14 if n["shape"] == "step" else 3
        back = "".join(f"<rect class='n deck {n['shape']}' x='{x + 4 * d:.0f}' y='{y + 4 * d:.0f}' width='{wid[i]:.0f}' height='{hgt[i]:.0f}' rx='{r}'/>"
                       for d in (2, 1)) if deck[i] > 1 else ""
        mark = (f"<path class='dm' d='M{x},{y + 10} L{x + 10},{y} L{x + 20},{y + 10} L{x + 10},{y + 20} Z' transform='translate(-10,-10)'/>"
                if n["shape"] == "decision" else "")
        tc = " inv" if n["shape"] == "model" else ""
        if n.get("cyc"):                                            # the whole map: which cycle made it, as its tile
            mark += (f"<rect class='cb' x='{x - 9:.0f}' y='{y - 9:.0f}' width='18' height='18' rx='4'/>"
                     f"<text class='cbt' x='{x:.0f}' y='{y + 4:.0f}' text-anchor='middle'>{n['cyc']}</text>")
        if n.get("cited"):                                          # a note cites it: a folded corner
            mark += f"<path class='nt' d='M{x + wid[i] - 14:.0f},{y:.0f} L{x + wid[i]:.0f},{y:.0f} L{x + wid[i]:.0f},{y + 14:.0f} Z'/>"
        if n["shape"] == "ext":
            to = n["to"]
            href = L.cycle(to[0], to[1]) if to[1] else L.task(to[0])
            svg.append(f"<a href='{e(href)}' class='bx ext'><rect class='n ext' x='{x:.0f}' y='{y:.0f}' width='{wid[i]:.0f}' height='{hgt[i]:.0f}' rx='10'/>"
                       + "".join(f"<text class='{c}' x='{x + PX:.0f}' y='{y + 19 + LH * k_:.0f}'>{e(t)}</text>" for k_, (c, t) in enumerate(text[i])) + "</a>")
            continue
        svg.append(f"<g class='bx'{dn(n.get('nid'))}>{back}<rect class='n {n['shape']}' x='{x:.0f}' y='{y:.0f}' width='{wid[i]:.0f}' height='{hgt[i]:.0f}' rx='{r}'/>{mark}"
                   + "".join(f"<text class='{c}{tc}' x='{x + PX:.0f}' y='{y + 19 + LH * k_:.0f}'>{e(t)}</text>" for k_, (c, t) in enumerate(text[i]))
                   + "</g>")
    return (f"<div class='pan' id='{fid}'><div class='zm'><button data-z='-1'>−</button><button data-z='0'>fit</button><button data-z='1'>+</button></div>"
            f"<div class='vp'><svg width='{W:.0f}' height='{H:.0f}' viewBox='0 0 {W:.0f} {H:.0f}' data-w='{W:.0f}' data-h='{H:.0f}'>{''.join(svg)}</svg></div></div>")


def fold(title, f, fid):
    """A graph folded under its title; the fold line is a miniature of its boxes."""
    if not f or not f["nodes"]:
        return ""
    mini = "".join(f"<i class='{n['shape']}'></i>" for n in f["nodes"][:40])
    return (f"<details class='fold'><summary><span class='chev'></span><h2>{e(title)}</h2><span class='mini'>{mini}</span></summary>"
            f"{flow_html(f, fid)}</details>")


PAN_JS = """<script data-re>
document.querySelectorAll('.pan').forEach(p => {
  const vp = p.querySelector('.vp'), svg = vp.querySelector('svg'), W = +svg.dataset.w, H = +svg.dataset.h;
  let z = 1;
  const set = v => { z = Math.min(3, Math.max(.2, v)); svg.setAttribute('width', W * z); svg.setAttribute('height', H * z); };
  p.querySelectorAll('.zm button').forEach(b => b.onclick = () => set(+b.dataset.z ? z * (+b.dataset.z > 0 ? 1.25 : .8) : Math.min(1, vp.clientWidth / W)));
  vp.addEventListener('wheel', ev => { if (!ev.ctrlKey && !ev.metaKey) return; ev.preventDefault(); set(z * (ev.deltaY < 0 ? 1.1 : .9)); }, {passive: false});
  let d = null;
  vp.addEventListener('pointerdown', ev => { d = [ev.clientX, ev.clientY, vp.scrollLeft, vp.scrollTop]; vp.setPointerCapture(ev.pointerId); vp.classList.add('drag'); });
  vp.addEventListener('pointermove', ev => { if (!d) return; vp.scrollLeft = d[2] - (ev.clientX - d[0]); vp.scrollTop = d[3] - (ev.clientY - d[1]); });
  const up = () => { d = null; vp.classList.remove('drag'); };
  vp.addEventListener('pointerup', up); vp.addEventListener('pointercancel', up);
});
</script>"""


def track(c, names=True):
    st = c["state"]
    at = STATIONS.index(st) if st in STATIONS else (3 if st == "CLOSED" else -1)
    parts = []
    for i, s in enumerate(STATIONS):
        cls = "on" if i <= at else ""
        cls += " here" if i == at and st != "CLOSED" else ""
        parts.append(f"<i class='{cls}' style='color:inherit'></i>")
        if i < 3:
            parts.append(f"<b class='{'bl' if i < at else ''}'></b>")
    labels = "".join(f"<span>{x.lower()}</span>" for x in STATIONS)
    return f"<div class='track s-{st}'>{''.join(parts)}</div>" + (f"<div class='stations'>{labels}</div>" if names else "")


def cycle_page(t, c):
    acts = [a for a in t["acts"] if a["cycle"] == c["n"]]
    pulse = ""
    body = [f"<div style='display:flex;gap:14px;align-items:center'>{tile(t, c, big=True, link=False)}<h1>{e(t['name'])}#{c['n']}</h1></div>",
            f"<div class='q'>{e(c['question'])}</div>", track(c)]
    if c.get("verdict"):
        body.append(f"<div class='okmark' style='margin-top:6px'>{e(c['verdict'])}</div>")
    if c.get("planWaiting"):
        pw = c["planWaiting"] if isinstance(c["planWaiting"], dict) else {"actor": "agent:haiku", "cmd": "bitt validate 3fa9c1e0 approve"}
        body.append(f"<div class='banner'><span class='who'></span><div>{e(pw['actor'])} proposed this plan<br><code>{e(pw['cmd'])}</code></div></div>")
    if c.get("train"):
        body.append(f"<h2>Training</h2><div class='prog'><i style='width:{c['train']['p'] * 100:.0f}%'></i></div><div class='mute num'>{e(c['train']['label'])}</div>")
    if c.get("plan"):
        body.append(f"<h2>Arms</h2>{arms_html(c['plan'])}")
    if c.get("ladder"):
        body.append(f"<h2>Runs</h2>{ladder_html(c['ladder'])}")
    if c["flow"]["nodes"]:
        mini = "".join(f"<i class='{n['shape']}'></i>" for n in c["flow"]["nodes"][:24])
        body.append(f"<details class='fold'><summary><span class='chev'></span><h2>Made</h2><span class='mini'>{mini}</span></summary>{flow_html(c['flow'])}</details>")
    body.append(f"<h2>Happened</h2>{rail(acts, with_cycle=False)}" if acts else "")
    return page(f"bitt: {t['name']}#{c['n']}",
                f"The cycle {t['name']}#{c['n']}: its question and where it is, the arms side by side, runs, how it was made, what happened.",
                [(L.home(), "bitt"), (L.task(t["name"]), t["name"])], "".join(body) + pulse + PAN_JS, t.get("seq"))


def write_static(S, out):
    """Every page of a model as files in one folder (static links), for a store nobody serves."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / L.home()).write_text(home(S))
    for t in S["tasks"]:
        (out / L.task(t["name"])).write_text(task_page(t))
        for c in t["cycles"]:
            (out / L.cycle(t["name"], c["n"])).write_text(cycle_page(t, c))
    return out / L.home()


AGO_JS = """<script>
(function tick() { const n = Date.now() / 1000; document.querySelectorAll('[data-at]').forEach(x => { const s = n - x.dataset.at;
  x.textContent = s < 60 ? Math.round(s) + ' s' : s < 3600 ? Math.round(s / 60) + ' min' : s < 86400 ? Math.round(s / 3600) + ' h' : Math.round(s / 86400) + ' d'; });
  setTimeout(tick, 5000); })();
</script>"""

def live_js(seq_url, seq):
    """The live bits of a served page: the last-check badge, and the poll that redraws <main> when the seq moves."""
    return CHK + LIVE_JS.replace("__SEQ__", seq_url).replace("__AT__", str(seq or 0))


CHK = "<div class='chk' id='chk'><i></i><span>checking</span></div>"

LIVE_JS = """<script>
(() => {
  let at = __AT__, ok = 0, bad = false;
  const chk = document.getElementById('chk');
  const show = () => { if (!chk) return; const s = Math.round((Date.now() - ok) / 1000);
    chk.classList.toggle('bad', bad);
    chk.lastChild.textContent = !ok ? (bad ? 'store not answering' : 'checking') : (bad ? 'store not answering · last ok ' : 'checked ') + s + ' s ago'; };
  setInterval(show, 1000);
  const keep = () => ({ y: scrollY, open: [...document.querySelectorAll('details')].map(d => d.open),
    pan: [...document.querySelectorAll('.pan .vp')].map(v => [v.scrollLeft, v.scrollTop, v.querySelector('svg').getAttribute('width')]) });
  const put = s => { document.querySelectorAll('details').forEach((d, i) => { if (i < s.open.length) d.open = s.open[i]; });
    document.querySelectorAll('.pan .vp').forEach((v, i) => { const p = s.pan[i]; if (!p) return; const g = v.querySelector('svg');
      const z = p[2] / g.dataset.w; g.setAttribute('width', p[2]); g.setAttribute('height', g.dataset.h * z); v.scrollLeft = p[0]; v.scrollTop = p[1]; });
    scrollTo(0, s.y); };
  async function poll() {
    try {
      const r = await fetch('__SEQ__', { cache: 'no-store' });
      if (!r.ok) throw new Error(r.status);
      const now = +(await r.text());
      ok = Date.now(); bad = false;
      if (chk) { chk.classList.remove('tick'); void chk.offsetWidth; chk.classList.add('tick'); }
      if (now && now !== at) {
        const doc = new DOMParser().parseFromString(await (await fetch(location.href, { cache: 'no-store' })).text(), 'text/html');
        const s = keep();
        document.querySelector('main').replaceWith(doc.querySelector('main'));
        document.querySelectorAll('[data-seq]').forEach(x => { if (+x.dataset.seq > at) x.classList.add('pulse'); });
        put(s);
        if (window.insRedraw) insRedraw();
        document.querySelectorAll('script[data-re]').forEach(x => (0, eval)(x.textContent));
        at = now;
      }
    } catch (e) { bad = true; }
    show();
    setTimeout(poll, 3000);
  }
  setTimeout(poll, 3000);
})();
</script>"""


def inspector(d):
    """One node in the drawer (bitt.panel.data.inspect): what it is, the run's counts, what it links and what links it (each opens in
    turn), its payload, and the SQL that reads the same (copy, paste into DBeaver)."""
    def ln(x):
        return (f"<a class='ln'{dn(x['id'])}><span class='r'>{e(x['role'])}</span><span>{e(x['kind'])} · {e(x['label'])}</span>"
                f"<span class='t'>{e(x['t'])}</span></a>")
    out = [f"<div class='ih'><button data-back>‹</button><b>{e(d['label'])}</b><button data-x>×</button></div>",
           f"<div class='mute'>{' · '.join(e(str(v)) for v in (d['kind'], d['task'], d['state'], d['actor'], d['card'], d['t'], 'seq ' + str(d['seq'])) if v)}</div>",
           f"<code class='id'>{e(d['id'])}</code>"]
    if d["run"]:
        r = d["run"]
        out.append(f"<div class='{'err' if r['status'] == 'failed' else ''}'>{e(r['status'])} · {e(r['result'])}</div>")
        out += [f"<pre class='err'>{e(x)}</pre>" for x in r["errors"]]
        if r["n_errors"] > len(r["errors"]):
            out.append(f"<div class='mute'>+{r['n_errors'] - len(r['errors'])}</div>")
    if d["links"] or d["values"]:
        out.append(f"<h2>links</h2>{''.join(ln(x) for x in d['links'])}")
        out += [f"<div class='ln'><span class='r'>{e(k)}</span><span>{e(str(v))}</span></div>" for k, v in d["values"].items()]
    if d["history"]:
        more = f" (first {len(d['history'])})" if d["n_history"] > len(d["history"]) else ""
        out.append(f"<h2>linked by · {d['n_history']}{more}</h2>{''.join(ln(x) for x in d['history'])}")
    out.append(f"<h2>payload</h2><pre>{e(d['payload'])}</pre><h2>sql</h2>")
    out += [f"<div class='qh'><span>{e(t)}</span><button data-copy>copy</button></div><pre>{e(q)}</pre>" for t, q in d["sql"]]
    return "".join(out)


INS_JS = """<script>
(() => {
  const box = document.getElementById('ins'), url = box.dataset.url, back = [];
  let cur = null, down = null;
  const mark = () => document.querySelectorAll('[data-n]').forEach(x => x.classList.toggle('sel', !box.hidden && x.dataset.n === cur && !box.contains(x)));
  async function open(id, push) {
    try {
      const r = await fetch(url.replace('__N__', encodeURIComponent(id)), { cache: 'no-store' });
      box.innerHTML = r.ok ? await r.text() : '<p class=err>' + r.status + '</p>';
    } catch (err) { box.innerHTML = '<p class=err>store not answering</p>'; }
    if (push && cur && cur !== id) back.push(cur);
    cur = id; box.hidden = false; history.replaceState(null, '', '#n=' + id); mark();
  }
  const close = () => { box.hidden = true; cur = null; back.length = 0; history.replaceState(null, '', location.pathname + location.search); mark(); };
  window.insRedraw = () => { if (cur) open(cur, false); else mark(); };
  async function copy(s, b) {
    try { await navigator.clipboard.writeText(s); }
    catch (err) { const a = document.createElement('textarea'); a.value = s; document.body.append(a); a.select(); document.execCommand('copy'); a.remove(); }
    b.textContent = 'copied'; setTimeout(() => { b.textContent = 'copy'; }, 1200);
  }
  document.addEventListener('pointerdown', ev => { down = [ev.clientX, ev.clientY]; });
  document.addEventListener('click', ev => {
    const t = ev.target;
    if (down && Math.hypot(ev.clientX - down[0], ev.clientY - down[1]) > 5) return;      // a drag of the graph, not a pick
    if (t.closest('[data-x]')) return close();
    if (t.closest('[data-back]')) { if (back.length) open(back.pop(), false); return; }
    const cp = t.closest('[data-copy]');
    if (cp) return copy(cp.parentElement.nextElementSibling.textContent, cp);
    const n = t.closest('[data-n]');
    if (n) { ev.preventDefault(); if (!box.contains(n)) back.length = 0; open(n.dataset.n, box.contains(n)); }
  });
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !box.hidden) close(); });
  const m = location.hash.match(/^#n=([0-9a-f]+)/);
  if (m) open(m[1], false);
})();
</script>"""
