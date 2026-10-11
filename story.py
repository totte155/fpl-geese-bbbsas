#!/usr/bin/env python3
"""
Weekly story generator for the FPL Geese vs Big Brexit Sauce H2H league.

Produces two write-ups from data.json:

  preview  "The Teamsheet"  — sent once the gameweek deadline has passed, so
                              captains and differentials are visible.
  report   "Full Time"      — sent once a gameweek is finished and verified.

Each is written as plain text (ready to paste into WhatsApp) and as HTML
(for the email). Run:

    python story.py preview
    python story.py report
    python story.py report --gw 4        # re-generate an older week

Nothing here calls the FPL API — it reads data.json, which update_data.py
keeps current.
"""

import argparse
import json
import os
import re
import sys

DATA_FILE = "data.json"
EN = "–"          # en dash
OUT_DIR = "stories"    # generated text/HTML lands here


# ---------------------------------------------------------------------------
# Loading and shared helpers
# ---------------------------------------------------------------------------

def load(path=DATA_FILE):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def team_names(d):
    return d["teams"]["geese"]["name"], d["teams"]["bbbsas"]["name"]


def short(d, team_name):
    """Display name for a team."""
    g, b = team_names(d)
    if team_name == g:
        return "FPL Geese"
    if team_name == b:
        return d["teams"]["bbbsas"].get("short") or "Big Brexit Sauce"
    return team_name


def completed(d):
    return d.get("gameweeks", [])


def records(d, upto=None):
    """Per-player W-D-L and total points across completed gameweeks.

    `upto` caps it at a gameweek, so an archived write-up shows the table as it
    stood that week rather than as it stands today.
    """
    g_name, b_name = team_names(d)
    rec = {}
    for p in d["teams"]["geese"]["players"] + d["teams"]["bbbsas"]["players"]:
        rec[p] = {"name": p, "w": 0, "d": 0, "l": 0, "pts": 0, "results": []}
    for gw in completed(d):
        if upto is not None and gw["gw"] > upto:
            continue
        for f in gw["fixtures"]:
            g, b = rec.get(f["geese_player"]), rec.get(f["bbbsas_player"])
            if not g or not b:
                continue
            g["pts"] += f["geese_score"]
            b["pts"] += f["bbbsas_score"]
            if f["winner"] == g_name:
                g["w"] += 1; b["l"] += 1
                g["results"].append("W"); b["results"].append("L")
            elif f["winner"] == b_name:
                b["w"] += 1; g["l"] += 1
                b["results"].append("W"); g["results"].append("L")
            else:
                g["d"] += 1; b["d"] += 1
                g["results"].append("D"); b["results"].append("D")
    return rec


def ranked(d, rec, side):
    players = d["teams"][side]["players"]
    return sorted((rec[p] for p in players),
                  key=lambda r: (-r["w"], r["l"], -r["pts"]))


def wdl(r):
    return f"{r['w']}{EN}{r['d']}{EN}{r['l']}"


def head_to_head(d, a_geese, b_bbbsas, upto=None):
    """Lifetime record between two specific players. Returns (a_wins, draws, b_wins)."""
    g_name, b_name = team_names(d)
    aw = dr = bw = 0
    for gw in completed(d):
        if upto is not None and gw["gw"] >= upto:
            continue
        for f in gw["fixtures"]:
            if f["geese_player"] == a_geese and f["bbbsas_player"] == b_bbbsas:
                if f["winner"] == g_name: aw += 1
                elif f["winner"] == b_name: bw += 1
                else: dr += 1
    return aw, dr, bw


def losing_streak(results):
    """Length of the current run of losses (0 if the last result wasn't a loss)."""
    n = 0
    for r in reversed(results):
        if r == "L":
            n += 1
        else:
            break
    return n


def winning_streak(results):
    n = 0
    for r in reversed(results):
        if r == "W":
            n += 1
        else:
            break
    return n


def pint_ledger(d, upto=None):
    """Clean sweeps across the season. A 4-0 means the losing side owes a pint."""
    g_name, b_name = team_names(d)
    owed = {"FPL Geese": 0, "Big Brexit Sauce": 0}
    events = []
    n = len(d["teams"]["geese"]["players"])
    for gw in completed(d):
        if upto is not None and gw["gw"] > upto:
            continue
        if gw["geese_points"] == n and gw["bbbsas_points"] == 0:
            owed["Big Brexit Sauce"] += 1
            events.append((gw["gw"], "FPL Geese", "Big Brexit Sauce"))
        elif gw["bbbsas_points"] == n and gw["geese_points"] == 0:
            owed["FPL Geese"] += 1
            events.append((gw["gw"], "Big Brexit Sauce", "FPL Geese"))
    return owed, events


def chip_label(chip):
    return {"bboost": "Bench Boost", "3xc": "Triple Captain",
            "freehit": "Free Hit", "wildcard": "Wildcard",
            "manager": "Assistant Manager"}.get(chip, chip)


# ---------------------------------------------------------------------------
# The Teamsheet (start of week)
# ---------------------------------------------------------------------------

def build_preview(d):
    live = d.get("live")
    if not live:
        return None
    gw = live["gw"]
    rec = records(d)
    g_tot, b_tot = d["totals"]["geese"], d["totals"]["bbbsas"]

    L = []
    L.append(f"*GW{gw} TEAMSHEET*")
    L.append(f"FPL Geese {g_tot}{EN}{b_tot} Big Brexit Sauce")
    lead = d["leader"]
    if lead["team"] == "Level":
        L.append("All square. Everything to play for.")
    else:
        L.append(f"{short(d, lead['team'])} lead by {lead['margin']}.")
    L.append("")

    for f in live["fixtures"]:
        gp, bp = f["geese_player"], f["bbbsas_player"]
        L.append(f"*{gp} vs {bp}*")

        # Lifetime record between these two
        aw, dr, bw = head_to_head(d, gp, bp)
        if aw or dr or bw:
            if aw > bw:
                L.append(f"  H2H: {gp} leads {aw}{EN}{bw}" + (f" ({dr} drawn)" if dr else ""))
            elif bw > aw:
                L.append(f"  H2H: {bp} leads {bw}{EN}{aw}" + (f" ({dr} drawn)" if dr else ""))
            else:
                L.append(f"  H2H: level {aw}{EN}{bw}" + (f" ({dr} drawn)" if dr else ""))
        else:
            L.append("  H2H: first meeting")

        # Recent form
        gf = "".join(rec[gp]["results"][-3:]) or "-"
        bf = "".join(rec[bp]["results"][-3:]) or "-"
        L.append(f"  Form: {gp} {gf} / {bp} {bf}")

        det = f.get("detail")
        if det:
            gc = (det["geese"] or {}).get("captain")
            bc = (det["bbbsas"] or {}).get("captain")
            if det.get("same_captain") and gc:
                L.append(f"  C: both on {gc['name']} — cancels out")
            elif gc and bc:
                L.append(f"  C: {gc['name']} vs {bc['name']}")
            for side, who in (("geese", gp), ("bbbsas", bp)):
                blk = det.get(side) or {}
                diffs = blk.get("differentials", [])[:3]
                if diffs:
                    L.append(f"  {who} only: " + ", ".join(p["name"] for p in diffs))
                if blk.get("chip"):
                    L.append(f"  {who} plays {chip_label(blk['chip'])}!")
        else:
            L.append("  (picks not public yet)")
        L.append("")

    # Streak watch
    hot = [r for r in rec.values() if winning_streak(r["results"]) >= 3]
    cold = [r for r in rec.values() if losing_streak(r["results"]) >= 3]
    if hot or cold:
        L.append("*FORM WATCH*")
        for r in hot:
            L.append(f"  {r['name']} on a {winning_streak(r['results'])}-week winning run")
        for r in cold:
            L.append(f"  {r['name']} has lost {losing_streak(r['results'])} in a row")
        L.append("")

    owed, _ = pint_ledger(d)
    if owed["FPL Geese"] or owed["Big Brexit Sauce"]:
        L.append("*PINT DEBT*")
        for team, n in owed.items():
            if n:
                L.append(f"  {team} owe {n} round{'s' if n > 1 else ''}")
        L.append("")

    L.append("Good luck. Captains are locked.")
    return {"gw": gw, "kind": "preview",
            "subject": f"GW{gw} Teamsheet — FPL Geese vs Big Brexit Sauce",
            "lines": L}


# ---------------------------------------------------------------------------
# Full Time (end of week)
# ---------------------------------------------------------------------------

def build_report(d, gw_no=None):
    gws = completed(d)
    if not gws:
        return None
    gw = next((g for g in gws if g["gw"] == gw_no), None) if gw_no else gws[-1]
    if gw is None:
        return None

    g_name, b_name = team_names(d)
    rec = records(d, upto=gw["gw"])          # the table as it stood that week
    n_fix = len(gw["fixtures"])

    L = []
    L.append(f"*GW{gw['gw']} FULL TIME*")
    L.append(f"FPL Geese {gw['geese_points']}{EN}{gw['bbbsas_points']} Big Brexit Sauce"
             + ("" if gw["winner"] == "Draw" else f" — {short(d, gw['winner'])} win the week"))

    # Season state, and whether the lead changed hands this week
    prev = [g for g in gws if g["gw"] < gw["gw"]]
    before = (prev[-1]["cum_geese"], prev[-1]["cum_bbbsas"]) if prev else (0, 0)
    after = (gw["cum_geese"], gw["cum_bbbsas"])
    L.append(f"Season: FPL Geese {after[0]}{EN}{after[1]} Big Brexit Sauce")

    def leader(pair):
        if pair[0] > pair[1]: return "FPL Geese"
        if pair[1] > pair[0]: return "Big Brexit Sauce"
        return "Level"
    if leader(before) != leader(after):
        if leader(after) == "Level":
            L.append("The lead is gone — all square.")
        else:
            L.append(f"*{leader(after)} take the lead!*")
    L.append("")

    # Results
    L.append("*RESULTS*")
    for f in gw["fixtures"]:
        # Winner's name in bold — renders in WhatsApp and in the email alike.
        gp, bp = f["geese_player"], f["bbbsas_player"]
        if f["winner"] == g_name:
            gp = f"*{gp}*"
        elif f["winner"] == b_name:
            bp = f"*{bp}*"
        L.append(f"  {gp} {f['geese_score']}{EN}{f['bbbsas_score']} {bp}")
    L.append("")

    # ---- Weekly awards ----------------------------------------------------
    scores = []
    for f in gw["fixtures"]:
        scores.append((f["geese_player"], f["geese_score"], "geese", f))
        scores.append((f["bbbsas_player"], f["bbbsas_score"], "bbbsas", f))
    scores.sort(key=lambda s: -s[1])

    A = []
    top, low = scores[0], scores[-1]
    A.append(f"  Player of the week: {top[0]} ({top[1]})")
    A.append(f"  Flop of the week: {low[0]} ({low[1]})")

    # Captains
    caps = []
    for f in gw["fixtures"]:
        det = f.get("detail") or {}
        for side, who in (("geese", f["geese_player"]), ("bbbsas", f["bbbsas_player"])):
            c = (det.get(side) or {}).get("captain")
            if c:
                caps.append((who, c["name"], c.get("haul", 0)))
    if caps:
        caps.sort(key=lambda c: -c[2])
        A.append(f"  Captain of the week: {caps[0][1]} {caps[0][2]} ({caps[0][0]})")
        blanks = [c for c in caps if c[2] <= 4]
        for who, name, haul in blanks:
            A.append(f"  Captain blank: {who} got {haul} from {name}")

    # Luck
    margins = []
    for f in gw["fixtures"]:
        m = abs(f["geese_score"] - f["bbbsas_score"])
        if f["winner"] != "Draw":
            win = f["geese_player"] if f["winner"] == g_name else f["bbbsas_player"]
            lose = f["bbbsas_player"] if f["winner"] == g_name else f["geese_player"]
            lose_pts = f["bbbsas_score"] if f["winner"] == g_name else f["geese_score"]
            margins.append((m, win, lose, lose_pts))
    if margins:
        margins.sort(key=lambda x: x[0])
        if margins[0][0] <= 3:
            A.append(f"  Luckiest win: {margins[0][1]} by {margins[0][0]}")
        big = margins[-1]
        A.append(f"  Biggest win: {big[1]} by {big[0]}")
        unlucky = max(margins, key=lambda x: x[3])
        A.append(f"  Unluckiest loss: {unlucky[2]} scored {unlucky[3]} and still lost")

    # Bench waste and hits
    bench, hits = [], []
    for f in gw["fixtures"]:
        det = f.get("detail") or {}
        for side, who in (("geese", f["geese_player"]), ("bbbsas", f["bbbsas_player"])):
            blk = det.get(side) or {}
            if blk.get("bench_points"):
                bench.append((blk["bench_points"], who, blk.get("chip")))
            if blk.get("hit"):
                hits.append((blk["hit"], who))
    bench = [b for b in bench if b[2] != "bboost"]
    if bench:
        bench.sort(key=lambda b: -b[0])
        A.append(f"  Bench waste: {bench[0][1]} left {bench[0][0]} on the bench")
    for cost, who in hits:
        row = next((m for m in margins if m[2] == who), None)
        if row and row[0] < cost:
            A.append(f"  Hit that cost it: {who} took {EN}{cost} and lost by {row[0]}")

    # Chips played
    for f in gw["fixtures"]:
        det = f.get("detail") or {}
        for side, who in (("geese", f["geese_player"]), ("bbbsas", f["bbbsas_player"])):
            chip = (det.get(side) or {}).get("chip")
            if chip:
                A.append(f"  Chip: {who} played {chip_label(chip)}")

    if A:
        L.append("*AWARDS*")
        L += A
        L.append("")

    # Records
    L.append("*RECORDS*")
    for side, label in (("geese", "FPL Geese"), ("bbbsas", "Big Brexit Sauce")):
        rows = ranked(d, rec, side)
        tot = f"{sum(r['w'] for r in rows)}{EN}{sum(r['d'] for r in rows)}{EN}{sum(r['l'] for r in rows)}"
        L.append(f"  {label} ({tot})")
        for i, r in enumerate(rows, 1):
            L.append(f"    {i}. {r['name']} {wdl(r)}")
    L.append("")

    # Streaks — the three-in-a-row flag
    slides = [(r["name"], losing_streak(r["results"])) for r in rec.values()
              if losing_streak(r["results"]) >= 3]
    runs = [(r["name"], winning_streak(r["results"])) for r in rec.values()
            if winning_streak(r["results"]) >= 3]
    if slides or runs:
        L.append("*STREAKS*")
        for name, n in sorted(slides, key=lambda x: -x[1]):
            L.append(f"  {name} has lost {n} in a row")
        for name, n in sorted(runs, key=lambda x: -x[1]):
            L.append(f"  {name} has won {n} in a row")
        L.append("")

    # Clean sweep forfeit
    if gw["geese_points"] == n_fix and gw["bbbsas_points"] == 0:
        L.append(f"*CLEAN SWEEP — {n_fix}{EN}0 to FPL Geese.*")
        L.append("Big Brexit Sauce owe a pint each next week.")
        L.append("")
    elif gw["bbbsas_points"] == n_fix and gw["geese_points"] == 0:
        L.append(f"*CLEAN SWEEP — {n_fix}{EN}0 to Big Brexit Sauce.*")
        L.append("FPL Geese owe a pint each next week.")
        L.append("")

    owed, events = pint_ledger(d, upto=gw["gw"])
    if events:
        L.append("*PINT LEDGER*")
        for g_no, winner, loser in events:
            L.append(f"  GW{g_no}: {loser} owe {winner}")
        L.append("")

    # Title race
    remaining = d["last_gameweek"] - gw["gw"]
    gap = abs(after[0] - after[1])
    if remaining:
        L.append(f"{remaining} gameweek{'s' if remaining != 1 else ''} left, "
                 f"{n_fix * remaining} points still available. Gap: {gap}.")
        if gap > n_fix * remaining:
            L.append(f"*{leader(after)} have won it.*")
    else:
        L.append("That's the season.")
        if leader(after) != "Level":
            L.append(f"*{leader(after)} win the 2026/27 H2H league.*")

    return {"gw": gw["gw"], "kind": "report",
            "subject": f"GW{gw['gw']} Full Time — FPL Geese "
                       f"{gw['geese_points']}{EN}{gw['bbbsas_points']} Big Brexit Sauce",
            "lines": L}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def to_text(story):
    """Plain text, WhatsApp-friendly (*bold* markers are WhatsApp's own)."""
    return "\n".join(story["lines"]).rstrip() + "\n"


def lines_to_html(lines, skip_first=0):
    """Render story lines as HTML. Shared by the email and the archive page."""
    out = []
    for raw in lines[skip_first:]:
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if not line:
            out.append('<div style="height:10px"></div>')
            continue
        bold = (line.startswith("*") and line.endswith("*") and len(line) > 2
                and line.count("*") == 2)
        if bold:
            line = line[1:-1]
        line = (line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        if not bold:
            # Inline *emphasis*, e.g. the winning name on a results line.
            line = re.sub(r"\*(.+?)\*", r"<strong>\1</strong>", line)
        style = f"margin:0;padding:1px 0 1px {indent * 8}px;"
        if bold:
            style += ("font-weight:700;letter-spacing:.04em;text-transform:uppercase;"
                      "font-size:13px;color:#8593ad;padding-top:10px;")
        else:
            style += "font-size:15px;color:#e9eefb;"
        out.append(f'<p style="{style}">{line}</p>')
    return "".join(out)


def to_html(story, site_url=""):
    GEESE, SAUCE = "#1f8ef1", "#8b5cf6"
    body = lines_to_html(story["lines"])

    link = (f'<p style="margin:18px 0 0;font-size:13px">'
            f'<a href="{site_url}" style="color:{GEESE}">Open the live dashboard</a></p>'
            if site_url else "")

    return f"""<!DOCTYPE html>
<html><body style="margin:0;background:#0b1220;padding:20px;
  font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
  <div style="max-width:560px;margin:0 auto;background:#121c30;border:1px solid #22304c;
    border-radius:14px;padding:22px 24px">
    <p style="margin:0 0 4px;font-size:12px;letter-spacing:.18em;text-transform:uppercase;
      color:#8593ad">FPL <span style="color:{GEESE}">Geese</span> vs
      <span style="color:{SAUCE}">Big Brexit Sauce</span></p>
    {body}
    {link}
  </div>
</body></html>"""


def build_archive(d, site_url=""):
    """The season archive: every completed gameweek's write-up, newest first.

    Rebuilt from data.json each run, so past weeks appear automatically and
    each one shows the table as it stood at the time.
    """
    gws = list(reversed(completed(d)))
    g_tot, b_tot = d["totals"]["geese"], d["totals"]["bbbsas"]
    lead = d["leader"]
    if lead["team"] == "Level":
        verdict = "All square"
    else:
        verdict = f"{short(d, lead['team'])} lead by {lead['margin']}"

    cards = []
    for i, gw in enumerate(gws):
        story = build_report(d, gw["gw"])
        if not story:
            continue
        # The first two lines are the heading and scoreline, already in the
        # card header — don't repeat them in the body.
        body = lines_to_html(story["lines"], skip_first=2)
        won = gw["winner"]
        colour = ("var(--geese)" if won == team_names(d)[0]
                  else "var(--bbbsas)" if won == team_names(d)[1] else "var(--draw)")
        label = short(d, won) if won != "Draw" else "Draw"
        cards.append(f"""
      <details class="gwcard" {'open' if i == 0 else ''}>
        <summary style="border-left:3px solid {colour}">
          <span class="gwno">GW {gw['gw']}</span>
          <span class="gwscore" style="color:{colour}">
            {gw['geese_points']}{EN}{gw['bbbsas_points']}</span>
          <span class="gwwin" style="color:{colour}">{label}</span>
          <span class="chev">&rsaquo;</span>
        </summary>
        <div class="gwbody">{body}</div>
      </details>""")

    if not cards:
        cards = ['<div class="empty"><h3>No completed gameweeks yet</h3>'
                 '<p>Each week\'s write-up appears here once the gameweek is over.</p></div>']

    back = (f'<a class="back" href="{site_url}">&larr; Live dashboard</a>'
            if site_url else "")

    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#0b1220">
<title>Season Story — FPL Geese vs Big Brexit Sauce</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{{--ink:#0b1220;--panel:#121c30;--panel-2:#0f1728;--line:#22304c;
    --text:#e9eefb;--muted:#8593ad;--geese:#1f8ef1;--bbbsas:#8b5cf6;--draw:#64748b;
    --display:"Barlow Condensed",system-ui,sans-serif;--body:"Inter",system-ui,sans-serif;}}
  *{{box-sizing:border-box}} html,body{{margin:0}}
  body{{background:radial-gradient(1100px 520px at 50% -12%,#16223c 0%,transparent 60%),var(--ink);
    color:var(--text);font-family:var(--body);line-height:1.5;padding:0 16px 64px;
    -webkit-font-smoothing:antialiased}}
  .wrap{{max-width:720px;margin:0 auto}}
  header{{padding:26px 2px 8px}}
  .eyebrow{{font-family:var(--display);font-weight:600;letter-spacing:.22em;
    text-transform:uppercase;font-size:13px;color:var(--muted)}}
  .eyebrow b{{color:var(--text);font-weight:700}}
  h1{{font-family:var(--display);font-weight:800;font-size:38px;margin:6px 0 2px;
    letter-spacing:.01em}}
  .sub{{color:var(--muted);font-size:14px}}
  .back{{display:inline-block;margin-top:14px;font-size:13px;color:var(--geese);
    text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:5px 12px}}
  .back:hover{{border-color:var(--geese)}}
  .tally{{margin-top:18px;border:1px solid var(--line);border-radius:14px;
    background:linear-gradient(180deg,var(--panel),var(--panel-2));padding:16px 18px;
    display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}}
  .tally .score{{font-family:var(--display);font-weight:800;font-size:30px;
    font-variant-numeric:tabular-nums}}
  .tally .g{{color:var(--geese)}} .tally .b{{color:var(--bbbsas)}}
  .tally .verdict{{font-family:var(--display);font-weight:700;font-size:16px;
    letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}}
  .gwcard{{margin-top:12px;border:1px solid var(--line);border-radius:14px;
    background:var(--panel-2);overflow:hidden}}
  summary{{list-style:none;cursor:pointer;display:flex;align-items:center;gap:12px;
    padding:13px 16px;background:var(--panel)}}
  summary::-webkit-details-marker{{display:none}}
  summary:hover{{background:#16233a}}
  .gwno{{font-family:var(--display);font-weight:700;letter-spacing:.12em;
    text-transform:uppercase;font-size:13px;color:var(--muted);min-width:52px}}
  .gwscore{{font-family:var(--display);font-weight:800;font-size:22px;
    font-variant-numeric:tabular-nums;min-width:52px}}
  .gwwin{{font-size:13.5px;font-weight:600;flex:1}}
  .chev{{color:var(--muted);transition:transform .15s ease}}
  details[open] .chev{{transform:rotate(90deg)}}
  .gwbody{{padding:6px 18px 18px}}
  .empty{{margin-top:16px;border:1px dashed var(--line);border-radius:14px;
    background:var(--panel-2);padding:34px 24px;text-align:center;color:var(--muted)}}
  .empty h3{{font-family:var(--display);font-weight:700;color:var(--text);
    font-size:22px;margin:0 0 6px}}
  footer{{margin-top:32px;padding-top:16px;border-top:1px solid var(--line);
    font-size:12px;color:var(--muted)}}
  @media (max-width:430px){{
    h1{{font-size:30px}} .gwwin{{display:none}} .tally .score{{font-size:26px}}
  }}
</style>
</head>
<body><div class="wrap">
  <header>
    <div class="eyebrow"><b>FPL Geese</b> vs <b>Big Brexit Sauce</b> · 2026/27</div>
    <h1>Season Story</h1>
    <div class="sub">Every gameweek, written up once it's over.</div>
    {back}
  </header>

  <div class="tally">
    <div><span class="score g">{g_tot}</span>
      <span class="score" style="color:var(--muted)">{EN}</span>
      <span class="score b">{b_tot}</span></div>
    <div class="verdict">{verdict}</div>
  </div>

  {''.join(cards)}

  <footer>Written up automatically after each gameweek is final.</footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["preview", "report", "archive"])
    ap.add_argument("--gw", type=int, default=None)
    ap.add_argument("--data", default=DATA_FILE)
    ap.add_argument("--site", default=os.environ.get("SITE_URL", ""))
    args = ap.parse_args()

    d = load(args.data)

    if args.kind == "archive":
        html = build_archive(d, args.site)
        with open("stories.html", "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"Wrote stories.html ({len(completed(d))} gameweeks).")
        return 0

    story = build_preview(d) if args.kind == "preview" else build_report(d, args.gw)
    if not story:
        print(f"No {args.kind} available yet.", file=sys.stderr)
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    text = to_text(story)
    base = os.path.join(OUT_DIR, f"{args.kind}")
    with open(base + ".txt", "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(base + ".html", "w", encoding="utf-8") as fh:
        fh.write(to_html(story, args.site))
    with open(os.path.join(OUT_DIR, "subject.txt"), "w", encoding="utf-8") as fh:
        fh.write(story["subject"])
    with open(os.path.join(OUT_DIR, "gw.txt"), "w", encoding="utf-8") as fh:
        fh.write(str(story["gw"]))

    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
