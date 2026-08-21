#!/usr/bin/env python3
"""
FPL H2H League Tracker — data builder (2026/27 season)

Fetches live Fantasy Premier League data, works out the head-to-head match
results between the two teams, and writes everything the dashboard needs into
data.json. Runs server-side (GitHub Actions), so there is no browser CORS
problem and no API key required.

Only ONE thing needs editing before the season: the ENTRY_IDS below.
"""

import json
import sys
from datetime import datetime, timezone
from functools import lru_cache

import requests

# ---------------------------------------------------------------------------
# 1. CONFIGURATION  —  this is the only section you should ever need to touch
# ---------------------------------------------------------------------------

TEAM_GEESE = "FPL Geese"
TEAM_BBBSAS = "Big Ben Brexit Sauce Appreciation Society"
TEAM_BBBSAS_SHORT = "BBBSAS"

# Team colours (kept in sync with the dashboard).
TEAM_COLOURS = {
    TEAM_GEESE: "#1f8ef1",
    TEAM_BBBSAS: "#8b5cf6",
}

# The eight players and which team they play for.
GEESE = ["Max", "Phil", "Dorian", "Torsten"]
BBBSAS = ["Tommi", "Pat", "Frej", "Tej"]

# >>> REPLACE THESE with the real 2026/27 FPL Entry IDs. <<<
# Find an Entry ID by opening a manager's FPL "Points" page — the number in the
# URL /entry/<ID>/event/... is their Entry ID. Leave as 0 to test the pipeline.
ENTRY_IDS = {
    "Max": 5167402,
    "Phil": 3737996,          # >>> still needed <<<
    "Dorian": 1684296,
    "Torsten": 4184094,
    "Tommi": 5204417,
    "Pat": 2816757,
    "Frej": 1004232,
    "Tej": 6871385,           # >>> still needed <<<
}

# The competition runs to this gameweek.
LAST_GAMEWEEK = 20

# Use net points (gameweek points minus any points hits from extra transfers),
# which is how FPL's own H2H mode scores. Set to False to use raw points.
USE_NET_POINTS = True

# ---------------------------------------------------------------------------
# 2. FIXTURE SCHEDULE
# ---------------------------------------------------------------------------
# A full round-robin is four gameweeks: over any four weeks every Geese player
# faces every BBBSAS player exactly once. We cycle that block five times to
# fill GW1–GW20, so each pairing recurs five times across the competition.
#
# Each tuple is (BBBSAS_player, GEESE_player).

ROUND_ROBIN = {
    1: [("Tommi", "Max"),  ("Pat", "Phil"),   ("Frej", "Dorian"),   ("Tej", "Torsten")],
    2: [("Pat", "Max"),    ("Frej", "Phil"),  ("Tej", "Dorian"),    ("Tommi", "Torsten")],
    3: [("Frej", "Max"),   ("Tej", "Phil"),   ("Tommi", "Dorian"),  ("Pat", "Torsten")],
    4: [("Tej", "Max"),    ("Tommi", "Phil"), ("Pat", "Dorian"),    ("Frej", "Torsten")],
}

# Expand the four base rounds across all gameweeks up to LAST_GAMEWEEK.
FINAL_SCHEDULE_BY_NAME = {
    gw: ROUND_ROBIN[((gw - 1) % 4) + 1] for gw in range(1, LAST_GAMEWEEK + 1)
}

# ---------------------------------------------------------------------------
# 3. FPL API
# ---------------------------------------------------------------------------

API_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
API_HISTORY = "https://fantasy.premierleague.com/api/entry/{entry_id}/history/"
API_LIVE = "https://fantasy.premierleague.com/api/event/{gw}/live/"
API_PICKS = "https://fantasy.premierleague.com/api/entry/{entry_id}/event/{gw}/picks/"
HEADERS = {"User-Agent": "fpl-h2h-tracker/1.0"}
TIMEOUT = 20


@lru_cache(maxsize=None)
def _get(url):
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def finished_gameweeks():
    """Gameweeks that have actually been played (never assume future GWs)."""
    try:
        data = _get(API_BOOTSTRAP)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: could not read bootstrap-static ({exc}).", file=sys.stderr)
        return set()
    done = set()
    for event in data.get("events", []):
        gw = event.get("id")
        if event.get("finished") and event.get("data_checked") and gw is not None:
            done.add(gw)
    return done


def player_points_by_gw(entry_id):
    """Map of gameweek -> net (or raw) points for one manager."""
    if not entry_id:
        return {}
    try:
        data = _get(API_HISTORY.format(entry_id=entry_id))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: no history for entry {entry_id} ({exc}).", file=sys.stderr)
        return {}
    out = {}
    for row in data.get("current", []):
        gw = row.get("event")
        pts = row.get("points", 0)
        if USE_NET_POINTS:
            pts -= row.get("event_transfers_cost", 0)
        if gw is not None:
            out[gw] = pts
    return out


def current_event():
    """The gameweek in progress, or the next one due. Returns (gw, status).

    status is 'live' if the current GW has started but isn't finished, or
    'upcoming' if the next GW hasn't kicked off. Returns (None, None) once the
    competition is over or the data can't be read.
    """
    try:
        data = _get(API_BOOTSTRAP)
    except Exception:  # noqa: BLE001
        return None, None
    events = data.get("events", [])
    for ev in events:  # a GW that has started but not finished
        if ev.get("is_current") and not ev.get("finished"):
            gw = ev.get("id")
            return (gw, "live") if gw and gw <= LAST_GAMEWEEK else (None, None)
    for ev in events:  # otherwise the next GW to come
        if ev.get("is_next"):
            gw = ev.get("id")
            return (gw, "upcoming") if gw and gw <= LAST_GAMEWEEK else (None, None)
    return None, None


@lru_cache(maxsize=None)
def live_points_map(gw):
    """element_id -> live total points for a gameweek (provisional while live)."""
    try:
        data = _get(API_LIVE.format(gw=gw))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: no live data for GW{gw} ({exc}).", file=sys.stderr)
        return {}
    out = {}
    for el in data.get("elements", []):
        stats = el.get("stats", {})
        out[el.get("id")] = stats.get("total_points", 0)
    return out


def manager_live_score(entry_id, gw, live_map):
    """Provisional live score for one manager: sum of on-field points
    (captain already doubled via multiplier), minus any transfer hit."""
    if not entry_id:
        return None
    try:
        data = _get(API_PICKS.format(entry_id=entry_id, gw=gw))
    except Exception:  # noqa: BLE001 — picks aren't available before the deadline
        return None
    total = 0
    for pick in data.get("picks", []):
        total += live_map.get(pick.get("element"), 0) * pick.get("multiplier", 0)
    if USE_NET_POINTS:
        total -= data.get("entry_history", {}).get("event_transfers_cost", 0)
    return total


def build_live_block():
    """The current-gameweek matchup with provisional live scores.

    This is displayed separately and NEVER counted towards the league totals
    until the gameweek is finished and flows through the normal calculation.
    """
    gw, status = current_event()
    if gw is None:
        return None

    pairings = FINAL_SCHEDULE_BY_NAME.get(gw)
    if not pairings:
        return None

    live_map = live_points_map(gw) if status == "live" else {}
    fixtures, geese_pts, bbbsas_pts, any_scores = [], 0, 0, False

    for bbbsas_player, geese_player in pairings:
        gs = manager_live_score(ENTRY_IDS.get(geese_player, 0), gw, live_map)
        bs = manager_live_score(ENTRY_IDS.get(bbbsas_player, 0), gw, live_map)
        if gs is None or bs is None or status != "live":
            gs, bs, leader = (gs or 0), (bs or 0), "—"
        else:
            any_scores = True
            leader = (TEAM_GEESE if gs > bs else
                      TEAM_BBBSAS if bs > gs else "Level")
            if gs > bs:
                geese_pts += 1
            elif bs > gs:
                bbbsas_pts += 1
        fixtures.append({
            "geese_player": geese_player, "geese_score": gs,
            "bbbsas_player": bbbsas_player, "bbbsas_score": bs, "leader": leader,
        })

    if status == "live" and not any_scores:
        status = "upcoming"  # GW is technically current but nothing scored yet

    return {
        "gw": gw,
        "status": status,  # 'live' or 'upcoming'
        "fixtures": fixtures,
        "provisional_geese": geese_pts,
        "provisional_bbbsas": bbbsas_pts,
        "provisional_score": f"{geese_pts}\u2013{bbbsas_pts}",
    }


# ---------------------------------------------------------------------------
# 4. H2H CALCULATIONS
# ---------------------------------------------------------------------------

def build():
    completed = finished_gameweeks()
    scores = {name: player_points_by_gw(ENTRY_IDS.get(name, 0)) for name in ENTRY_IDS}

    gameweeks = []
    cum_geese = cum_bbbsas = 0

    for gw in range(1, LAST_GAMEWEEK + 1):
        # A gameweek only counts once the PL marks it finished AND we have a
        # score for all eight managers — protects against partial data.
        pairings = FINAL_SCHEDULE_BY_NAME[gw]
        have_all = all(gw in scores.get(b, {}) and gw in scores.get(g, {})
                       for b, g in pairings)
        if gw not in completed or not have_all:
            continue

        fixtures = []
        geese_pts = bbbsas_pts = 0
        for bbbsas_player, geese_player in pairings:
            gs = scores[geese_player][gw]
            bs = scores[bbbsas_player][gw]
            if gs > bs:
                winner = TEAM_GEESE
                geese_pts += 1
            elif bs > gs:
                winner = TEAM_BBBSAS
                bbbsas_pts += 1
            else:
                winner = "Draw"
            fixtures.append({
                "geese_player": geese_player,
                "geese_score": gs,
                "bbbsas_player": bbbsas_player,
                "bbbsas_score": bs,
                "winner": winner,
            })

        if geese_pts > bbbsas_pts:
            gw_winner = TEAM_GEESE
        elif bbbsas_pts > geese_pts:
            gw_winner = TEAM_BBBSAS
        else:
            gw_winner = "Draw"

        cum_geese += geese_pts
        cum_bbbsas += bbbsas_pts

        gameweeks.append({
            "gw": gw,
            "geese_points": geese_pts,
            "bbbsas_points": bbbsas_pts,
            "score": f"{geese_pts}\u2013{bbbsas_pts}",  # en dash
            "winner": gw_winner,
            "cum_geese": cum_geese,
            "cum_bbbsas": cum_bbbsas,
            "fixtures": fixtures,
        })

    if cum_geese > cum_bbbsas:
        leader, margin = TEAM_GEESE, cum_geese - cum_bbbsas
    elif cum_bbbsas > cum_geese:
        leader, margin = TEAM_BBBSAS, cum_bbbsas - cum_geese
    else:
        leader, margin = "Level", 0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": {
            "geese": {"name": TEAM_GEESE, "colour": TEAM_COLOURS[TEAM_GEESE],
                      "players": GEESE},
            "bbbsas": {"name": TEAM_BBBSAS, "short": TEAM_BBBSAS_SHORT,
                       "colour": TEAM_COLOURS[TEAM_BBBSAS], "players": BBBSAS},
        },
        "last_gameweek": LAST_GAMEWEEK,
        "completed_count": len(gameweeks),
        "totals": {"geese": cum_geese, "bbbsas": cum_bbbsas},
        "leader": {"team": leader, "margin": margin},
        "gameweeks": gameweeks,
        "live": build_live_block(),
    }


def main():
    data = build()
    with open("data.json", "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"Wrote data.json — {data['completed_count']} completed gameweek(s), "
          f"Geese {data['totals']['geese']}–{data['totals']['bbbsas']} BBBSAS.")


if __name__ == "__main__":
    main()
