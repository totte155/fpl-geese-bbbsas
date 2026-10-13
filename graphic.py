#!/usr/bin/env python3
"""
Builds the weekly matchday graphic — a portrait card sized for WhatsApp,
rendered to PNG by headless Chromium.

    python graphic.py report          # latest completed gameweek
    python graphic.py report --gw 3

Writes stories/graphic_gw<N>.png (and the HTML it was rendered from).
"""

import argparse
import json
import os
import subprocess
import sys

import story as S

W, H, SCALE = 1080, 1350, 2
GEESE = "#1f8ef1"
SAUCE = "#d97706"          # amber: 30 ΔE from the blue even for protan/deutan
INK = "#0b1220"
PANEL = "#141f36"
LINE = "#26324c"
TEXT = "#eef2fb"
MUTED = "#93a0b8"


def fixture_rows(d, gw):
    """Each fixture as opposing bars, scaled against the highest score."""
    g_name, b_name = S.team_names(d)
    top = max(max(f["geese_score"], f["bbbsas_score"]) for f in gw["fixtures"]) or 1
    rows = []
    for f in gw["fixtures"]:
        gs, bs = f["geese_score"], f["bbbsas_score"]
        g_win = f["winner"] == g_name
        b_win = f["winner"] == b_name
        rows.append(f"""
      <div class="fx">
        <div class="side l {'win' if g_win else 'lose'}">
          <span class="nm">{f['geese_player']}</span>
          <span class="pt">{gs}</span>
        </div>
        <div class="bars">
          <div class="half l"><i style="width:{gs / top * 100:.1f}%"></i></div>
          <div class="half r"><i style="width:{bs / top * 100:.1f}%"></i></div>
        </div>
        <div class="side r {'win' if b_win else 'lose'}">
          <span class="pt">{bs}</span>
          <span class="nm">{f['bbbsas_player']}</span>
        </div>
      </div>""")
    return "".join(rows)


def awards_of(d, gw):
    """The three lines worth putting on a graphic, pulled from the full story."""
    scores = []
    for f in gw["fixtures"]:
        scores.append((f["geese_player"], f["geese_score"]))
        scores.append((f["bbbsas_player"], f["bbbsas_score"]))
    scores.sort(key=lambda s: -s[1])

    caps = []
    for f in gw["fixtures"]:
        det = f.get("detail") or {}
        for side, who in (("geese", f["geese_player"]), ("bbbsas", f["bbbsas_player"])):
            c = (det.get(side) or {}).get("captain")
            if c:
                caps.append((who, c["name"], c.get("haul", 0)))
    caps.sort(key=lambda c: -c[2])

    out = [("Player of the week", f"{scores[0][0]} {scores[0][1]}"),
           ("Flop of the week", f"{scores[-1][0]} {scores[-1][1]}")]
    if caps:
        out.append(("Captain of the week", f"{caps[0][1]} {caps[0][2]}"))
    return out


def records_strip(d, gw):
    """Both teams' tables as they stood after this gameweek."""
    rec = S.records(d, upto=gw["gw"])
    cols = []
    for side, name, col in (("geese", "FPL Geese", GEESE),
                            ("bbbsas", "Big Brexit Sauce", SAUCE)):
        rows = S.ranked(d, rec, side)
        tot = (f"{sum(r['w'] for r in rows)}-{sum(r['d'] for r in rows)}"
               f"-{sum(r['l'] for r in rows)}")
        body = "".join(
            f'<div class="rr"><span class="rn">{r["name"]}</span>'
            f'<span class="rw">{r["w"]}-{r["d"]}-{r["l"]}</span></div>'
            for r in rows)
        cols.append(f'<div class="rcol" style="border-top:3px solid {col}">'
                    f'<div class="rhead"><span style="color:{col}">{name}</span>'
                    f'<span style="color:{col}">{tot}</span></div>{body}</div>')
    return "".join(cols)


def build_html(d, gw):
    g_name, b_name = S.team_names(d)
    won = gw["winner"]
    colour = GEESE if won == g_name else SAUCE if won == b_name else MUTED
    label = ("FPL Geese win the week" if won == g_name
             else "Big Brexit Sauce win the week" if won == b_name else "Honours even")

    awards = "".join(
        f'<div class="aw"><span class="k">{k}</span><span class="v">{v}</span></div>'
        for k, v in awards_of(d, gw))

    g_tot, b_tot = gw["cum_geese"], gw["cum_bbbsas"]
    lead = ("Level" if g_tot == b_tot else
            f"FPL Geese lead by {g_tot - b_tot}" if g_tot > b_tot
            else f"Big Brexit Sauce lead by {b_tot - g_tot}")

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0}}
  body{{width:{W}px;height:{H}px;background:
      radial-gradient(900px 420px at 50% -8%,#1b2a49 0%,transparent 62%),{INK};
    font-family:Inter,'Helvetica Neue',Arial,sans-serif;color:{TEXT};padding:54px 56px;display:flex;
    flex-direction:column;-webkit-font-smoothing:antialiased}}
  .eyebrow{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:600;letter-spacing:.3em;
    text-transform:uppercase;font-size:22px;color:{MUTED}}}
  .gw{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:800;font-size:92px;line-height:.95;
    margin-top:6px;letter-spacing:.01em}}
  .verdict{{font-size:25px;font-weight:600;color:{colour};margin-top:4px}}

  .scoreline{{display:flex;align-items:center;justify-content:center;gap:34px;
    margin:34px 0 10px;padding:26px 0;border-top:1px solid {LINE};border-bottom:1px solid {LINE}}}
  .team{{display:flex;flex-direction:column;align-items:center;gap:8px;width:300px}}
  .team .badge{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:700;font-size:26px;
    letter-spacing:.1em;text-transform:uppercase}}
  .team .big{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:800;font-size:132px;line-height:.85;
    font-variant-numeric:tabular-nums}}
  .vs{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-size:34px;color:{MUTED};font-weight:600}}

  .fxs{{margin-top:26px;display:flex;flex-direction:column;gap:17px}}
  .fx{{display:grid;grid-template-columns:300px 1fr 300px;align-items:center;gap:20px}}
  .side{{display:flex;align-items:baseline;gap:12px;font-size:28px}}
  .side.l{{justify-content:flex-end}}
  .side .nm{{font-weight:600}}
  .side .pt{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:800;font-size:38px;
    font-variant-numeric:tabular-nums;min-width:62px;text-align:center}}
  .side.l .pt{{color:{GEESE}}} .side.r .pt{{color:{SAUCE}}}
  .side.lose{{opacity:.42}}
  /* Mirrored from the centre: each bar grows outward, so the longer bar always
     belongs to the higher score. A 2px gap keeps the two fills separate. */
  .bars{{display:flex;align-items:center;height:22px}}
  .half{{flex:1;display:flex;height:16px}}
  .half.l{{justify-content:flex-end;padding-right:2px}}
  .half.r{{justify-content:flex-start;padding-left:2px}}
  .half i{{display:block;height:100%}}
  .half.l i{{background:{GEESE};border-radius:4px 0 0 4px}}
  .half.r i{{background:{SAUCE};border-radius:0 4px 4px 0}}

  .recs{{margin-top:34px;display:flex;gap:16px}}
  .rcol{{flex:1;background:{PANEL};border:1px solid {LINE};border-radius:16px;
    padding:16px 20px 10px}}
  .rhead{{display:flex;justify-content:space-between;align-items:baseline;
    font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:700;
    font-size:23px;letter-spacing:.07em;text-transform:uppercase;
    padding-bottom:10px;border-bottom:1px solid {LINE};font-variant-numeric:tabular-nums}}
  .rr{{display:flex;justify-content:space-between;align-items:center;padding:9px 0;
    border-bottom:1px solid rgba(38,50,76,.55);font-size:25px}}
  .rr:last-child{{border-bottom:none}}
  .rn{{font-weight:600}}
  .rw{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:800;
    font-size:28px;font-variant-numeric:tabular-nums;color:{MUTED}}}

  .awards{{margin-top:auto;display:flex;gap:14px}}
  .aw{{flex:1;background:{PANEL};border:1px solid {LINE};border-radius:16px;
    padding:18px 20px;display:flex;flex-direction:column;gap:7px}}
  .aw .k{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:600;letter-spacing:.14em;
    text-transform:uppercase;font-size:17px;color:{MUTED}}}
  .aw .v{{font-size:27px;font-weight:700}}

  .foot{{margin-top:22px;padding-top:20px;border-top:1px solid {LINE};
    display:flex;align-items:center;justify-content:space-between}}
  .foot .season{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:800;font-size:40px;
    font-variant-numeric:tabular-nums}}
  .foot .lead{{font-size:23px;color:{MUTED};font-weight:500}}
  .sw{{display:inline-block;width:16px;height:16px;border-radius:5px;margin-right:9px;
    vertical-align:-1px}}
</style></head>
<body>
  <div class="eyebrow">FPL Geese vs Big Brexit Sauce · 2026/27</div>
  <div class="gw">GAMEWEEK {gw['gw']}</div>
  <div class="verdict">{label}</div>

  <div class="scoreline">
    <div class="team">
      <span class="badge" style="color:{GEESE}"><span class="sw" style="background:{GEESE}"></span>FPL Geese</span>
      <span class="big" style="color:{GEESE}">{gw['geese_points']}</span>
    </div>
    <span class="vs">—</span>
    <div class="team">
      <span class="badge" style="color:{SAUCE}"><span class="sw" style="background:{SAUCE}"></span>Big Brexit Sauce</span>
      <span class="big" style="color:{SAUCE}">{gw['bbbsas_points']}</span>
    </div>
  </div>

  <div class="fxs">{fixture_rows(d, gw)}</div>

  <div class="recs">{records_strip(d, gw)}</div>

  <div class="awards">{awards}</div>

  <div class="foot">
    <div class="season">
      <span style="color:{GEESE}">{g_tot}</span>
      <span style="color:{MUTED}">–</span>
      <span style="color:{SAUCE}">{b_tot}</span>
    </div>
    <div class="lead">{lead} · after {gw['gw']} of {d['last_gameweek']}</div>
  </div>
</body></html>"""


def preview_cards(d, live):
    """One card per matchup: head-to-head, form, captains, differentials."""
    rec = S.records(d)
    cards = []
    for f in live["fixtures"]:
        gp, bp = f["geese_player"], f["bbbsas_player"]

        aw, dr, bw = S.head_to_head(d, gp, bp)
        if not (aw or dr or bw):
            h2h = "First meeting"
        elif aw > bw:
            h2h = f"{gp} leads {aw}-{bw}"
        elif bw > aw:
            h2h = f"{bp} leads {bw}-{aw}"
        else:
            h2h = f"Level {aw}-{bw}"

        gform = "".join(rec[gp]["results"][-3:]) or "–"
        bform = "".join(rec[bp]["results"][-3:]) or "–"

        det = f.get("detail") or {}
        gc = (det.get("geese") or {}).get("captain")
        bc = (det.get("bbbsas") or {}).get("captain")
        if det.get("same_captain") and gc:
            cap = (f'<div class="cap same">Both captain {gc["name"]} '
                   f'<span class="capnote">— cancels out</span></div>')
        elif gc and bc:
            cap = (f'<div class="cap"><span style="color:{GEESE}">{gc["name"]}</span>'
                   f'<span class="capv">C vs C</span>'
                   f'<span style="color:{SAUCE}">{bc["name"]}</span></div>')
        else:
            cap = '<div class="cap"><span class="capnote">Captains not public yet</span></div>'

        def diffs(side):
            blk = det.get(side) or {}
            names = [p["name"] for p in blk.get("differentials", [])[:3]]
            chip = blk.get("chip")
            tag = (f'<span class="chip">{S.chip_label(chip)}</span>' if chip else "")
            return ("<span class='dn'>" + ", ".join(names) + "</span>" if names
                    else "<span class='dn muted'>—</span>") + tag

        cards.append(f"""
      <div class="mu">
        <div class="mu-top">
          <span class="who" style="color:{GEESE}">{gp}</span>
          <span class="h2h">{h2h}</span>
          <span class="who r" style="color:{SAUCE}">{bp}</span>
        </div>
        <div class="form">
          <span>{gform}</span><span class="formlbl">last 3</span><span>{bform}</span>
        </div>
        {cap}
        <div class="diffs">
          <div class="dcol">{diffs("geese")}</div>
          <div class="dcol r">{diffs("bbbsas")}</div>
        </div>
      </div>""")
    return "".join(cards)


def build_preview_html(d, live):
    g_tot, b_tot = d["totals"]["geese"], d["totals"]["bbbsas"]
    lead = ("All square" if g_tot == b_tot else
            f"FPL Geese lead by {g_tot - b_tot}" if g_tot > b_tot
            else f"Big Brexit Sauce lead by {b_tot - g_tot}")

    rec = S.records(d)
    watch = []
    for r in rec.values():
        w, l = S.winning_streak(r["results"]), S.losing_streak(r["results"])
        if w >= 3:
            watch.append(f'<span class="wi">{r["name"]} <b>{w} wins</b> in a row</span>')
        elif l >= 3:
            watch.append(f'<span class="wi">{r["name"]} <b>{l} losses</b> in a row</span>')
    watch_row = (f'<div class="watch"><span class="wlbl">Form watch</span>'
                 f'{"".join(watch)}</div>' if watch else "")

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0}}
  body{{width:{W}px;background:
      radial-gradient(900px 420px at 50% -8%,#1b2a49 0%,transparent 62%),{INK};
    font-family:Inter,'Helvetica Neue',Arial,sans-serif;color:{TEXT};padding:54px 56px 48px;
    -webkit-font-smoothing:antialiased}}
  .eyebrow{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:600;
    letter-spacing:.3em;text-transform:uppercase;font-size:22px;color:{MUTED}}}
  .gw{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:800;
    font-size:92px;line-height:.95;margin-top:6px}}
  .sub{{font-size:25px;font-weight:600;color:{MUTED};margin-top:4px}}

  .tally{{display:flex;align-items:center;gap:18px;
    margin:30px 0 8px;padding:22px 0;border-top:1px solid {LINE};border-bottom:1px solid {LINE}}}
  .tcol{{display:flex;flex-direction:column;gap:2px}}
  .tcol.r{{align-items:flex-end}}
  .tname{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:700;
    font-size:20px;letter-spacing:.12em;text-transform:uppercase}}
  .nums{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:800;
    font-size:64px;line-height:.95;font-variant-numeric:tabular-nums}}
  .tdash{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-size:44px;
    color:{MUTED};align-self:flex-end;padding-bottom:4px}}
  .tally .lead{{margin-left:auto;font-size:26px;color:{MUTED};font-weight:600}}

  .mu{{background:{PANEL};border:1px solid {LINE};border-radius:18px;
    padding:22px 26px 20px;margin-top:18px}}
  .mu-top{{display:flex;align-items:baseline;justify-content:space-between;gap:16px}}
  .who{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:800;
    font-size:40px;letter-spacing:.02em}}
  .who.r{{text-align:right}}
  .h2h{{font-size:20px;color:{MUTED};font-weight:500;white-space:nowrap}}
  .form{{display:flex;align-items:center;justify-content:space-between;margin-top:6px;
    font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-size:24px;
    letter-spacing:.18em;color:{MUTED}}}
  .formlbl{{font-family:Inter,sans-serif;font-size:15px;letter-spacing:.1em;
    text-transform:uppercase;opacity:.65}}
  .cap{{display:flex;align-items:center;justify-content:space-between;gap:14px;
    margin-top:14px;padding:11px 16px;background:{INK};border:1px solid {LINE};
    border-radius:12px;font-size:25px;font-weight:700}}
  .cap.same{{justify-content:center;color:#f0b429;border-color:rgba(240,180,41,.35);
    background:rgba(240,180,41,.07)}}
  .capv{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-size:19px;
    letter-spacing:.14em;color:{MUTED};font-weight:600}}
  .capnote{{font-size:20px;font-weight:500;color:{MUTED}}}
  .cap.same .capnote{{color:#f0b429;opacity:.8}}
  .diffs{{display:flex;justify-content:space-between;gap:20px;margin-top:13px}}
  .dcol{{flex:1;font-size:20px;color:{TEXT};opacity:.85}}
  .dcol.r{{text-align:right}}
  .dn.muted{{color:{MUTED}}}
  .chip{{display:inline-block;margin-left:9px;font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;
    font-size:16px;letter-spacing:.1em;text-transform:uppercase;color:#f0b429;
    border:1px solid rgba(240,180,41,.4);border-radius:6px;padding:1px 7px}}

  .watch{{margin-top:22px;display:flex;flex-wrap:wrap;align-items:center;gap:10px 22px;
    padding-top:20px;border-top:1px solid {LINE};font-size:21px;color:{MUTED}}}
  .wlbl{{font-family:'Barlow Condensed','Arial Narrow',Arial,sans-serif;font-weight:700;
    letter-spacing:.16em;text-transform:uppercase;font-size:18px}}
  .wi b{{color:{TEXT}}}
  .foot{{margin-top:22px;font-size:21px;color:{MUTED}}}
</style></head>
<body>
  <div class="eyebrow">FPL Geese vs Big Brexit Sauce · 2026/27</div>
  <div class="gw">GW {live['gw']} TEAMSHEET</div>
  <div class="sub">Captains are locked</div>

  <div class="tally">
    <div class="tcol">
      <span class="tname" style="color:{GEESE}">FPL Geese</span>
      <span class="nums" style="color:{GEESE}">{g_tot}</span>
    </div>
    <span class="tdash">–</span>
    <div class="tcol r">
      <span class="tname" style="color:{SAUCE}">Big Brexit Sauce</span>
      <span class="nums" style="color:{SAUCE}">{b_tot}</span>
    </div>
    <div class="lead">{lead}</div>
  </div>

  {preview_cards(d, live)}
  {watch_row}
  <div class="foot">Good luck.</div>
</body></html>"""


def render(html, png_path, full_page):
    """HTML -> PNG via headless Chromium."""
    from playwright.sync_api import sync_playwright
    html_path = png_path.replace(".png", ".html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H},
                        device_scale_factor=SCALE)
        pg.goto("file://" + os.path.abspath(html_path))
        pg.wait_for_timeout(900)          # let the webfonts land
        pg.screenshot(path=png_path, full_page=full_page)
        b.close()
    return png_path


def build(kind, gw_no=None, data="data.json"):
    """Draw one graphic. Returns its path, or None if there's nothing to draw."""
    d = S.load(data)
    os.makedirs(S.OUT_DIR, exist_ok=True)

    if kind == "preview":
        live = d.get("live")
        if not live or not any(f.get("detail") for f in live.get("fixtures", [])):
            return None               # picks aren't public yet
        png = os.path.join(S.OUT_DIR, f"teamsheet_gw{live['gw']}.png")
        # Preview height varies with the four cards, so size to content.
        return render(build_preview_html(d, live), png, full_page=True)

    gws = S.completed(d)
    gw = (next((g for g in gws if g["gw"] == gw_no), None) if gw_no
          else (gws[-1] if gws else None))
    if not gw:
        return None
    png = os.path.join(S.OUT_DIR, f"matchday_gw{gw['gw']}.png")
    return render(build_html(d, gw), png, full_page=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["report", "preview"])
    ap.add_argument("--gw", type=int, default=None)
    ap.add_argument("--data", default="data.json")
    args = ap.parse_args()

    path = build(args.kind, args.gw, args.data)
    if not path:
        print(f"Nothing to draw for {args.kind}.", file=sys.stderr)
        return 1
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
