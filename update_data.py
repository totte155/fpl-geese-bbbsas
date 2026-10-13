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
TEAM_BBBSAS_SHORT = "Big Brexit Sauce"

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
    "Phil": 3737996,
    "Dorian": 1684296,
    "Torsten": 4184094,
    "Tommi": 5204417,
    "Pat": 2816757,
    "Frej": 1004232,
    "Tej": 6871385,
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

# A full round-robin is four gameweeks: over any four weeks every Geese player
# faces every BBBSAS player exactly once. We cycle that block five times to
# fill GW1–GW20, so each of the 16 pairings recurs exactly five times.
#
# The rounds are ordered so that Round 4 — the requested finale — lands on
# GW20 (and also GW4, 8, 12, 16).
#
# Each tuple is (BBBSAS_player, GEESE_player).

ROUND_ROBIN = {
    1: [("Pat", "Max"),   ("Tommi", "Phil"), ("Frej", "Dorian"), ("Tej", "Torsten")],
    2: [("Frej", "Max"),  ("Tej", "Phil"),   ("Pat", "Dorian"),  ("Tommi", "Torsten")],
    3: [("Tej", "Max"),   ("Frej", "Phil"),  ("Tommi", "Dorian"), ("Pat", "Torsten")],
    4: [("Tommi", "Max"), ("Pat", "Phil"),   ("Tej", "Dorian"),  ("Frej", "Torsten")],
}

# Expand the four base rounds across all gameweeks up to LAST_GAMEWEEK.
# GAMEWEEK_OVERRIDES can replace the cycled fixtures for a specific gameweek if
# you ever need a one-off change. Tuples are (BBBSAS_player, GEESE_player).
GAMEWEEK_OVERRIDES = {}

FINAL_SCHEDULE_BY_NAME = {
    gw: GAMEWEEK_OVERRIDES.get(gw, ROUND_ROBIN[((gw - 1) % 4) + 1])
    for gw in range(1, LAST_GAMEWEEK + 1)
}

# ---------------------------------------------------------------------------
# 3. FPL API
# ---------------------------------------------------------------------------

API_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
API_HISTORY = "https://fantasy.premierleague.com/api/entry/{entry_id}/history/"
API_LIVE = "https://fantasy.premierleague.com/api/event/{gw}/live/"
API_PICKS = "https://fantasy.premierleague.com/api/entry/{entry_id}/event/{gw}/picks/"
API_FIXTURES = "https://fantasy.premierleague.com/api/fixtures/?event={gw}"
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


@lru_cache(maxsize=None)
def element_meta():
    """element_id -> {name, team, pos} for every Premier League player."""
    try:
        data = _get(API_BOOTSTRAP)
    except Exception:  # noqa: BLE001
        return {}
    teams = {t["id"]: t.get("short_name", "") for t in data.get("teams", [])}
    pos = {t["id"]: t.get("singular_name_short", "")
           for t in data.get("element_types", [])}
    out = {}
    for el in data.get("elements", []):
        out[el["id"]] = {
            "name": el.get("web_name", "?"),
            "team": teams.get(el.get("team"), ""),
            "pos": pos.get(el.get("element_type"), ""),
        }
    return out


def manager_squad(entry_id, gw):
    """Picks and active chip for a manager in a gameweek, or None.

    Picks only exist once the gameweek deadline has passed.
    """
    if not entry_id:
        return None
    try:
        data = _get(API_PICKS.format(entry_id=entry_id, gw=gw))
    except Exception:  # noqa: BLE001
        return None
    hist = data.get("entry_history", {}) or {}
    return {
        "picks": data.get("picks", []),
        "chip": data.get("active_chip"),
        # Used by the weekly story: points left unused on the bench, and the
        # cost of any extra transfers taken this gameweek.
        "bench_points": hist.get("points_on_bench", 0),
        "hit": hist.get("event_transfers_cost", 0),
    }


def _squad_view(squad_data, live_map, meta):
    """Turn raw picks into {element: info} plus the captain's details.

    A player counts as "playing" if their points count towards the manager's
    score this gameweek — i.e. they're in the starting XI, or the manager has
    played their Bench Boost (in which case all 15 count).
    """
    picks = (squad_data or {}).get("picks", [])
    chip = (squad_data or {}).get("chip")
    bench_boost = chip == "bboost"

    squad, captain = {}, None
    for p in picks:
        eid = p.get("element")
        info = meta.get(eid, {"name": f"#{eid}", "team": "", "pos": ""})
        mult = p.get("multiplier", 0)
        entry = {
            "id": eid,
            "name": info["name"],
            "team": info["team"],
            "pos": info["pos"],
            "points": live_map.get(eid, 0),
            "playing": mult > 0 or bench_boost,
            "multiplier": mult,
        }
        squad[eid] = entry
        if p.get("is_captain"):
            captain = dict(entry, haul=entry["points"] * max(mult, 1))
    return squad, captain, chip


def fixture_detail(geese_player, bbbsas_player, gw, live_map):
    """Captain picks and squad differentials for one H2H fixture."""
    meta = element_meta()
    if not meta:
        return None
    gp = manager_squad(ENTRY_IDS.get(geese_player, 0), gw)
    bp = manager_squad(ENTRY_IDS.get(bbbsas_player, 0), gw)
    if gp is None or bp is None:
        return None

    gsq, gcap, gchip = _squad_view(gp, live_map, meta)
    bsq, bcap, bchip = _squad_view(bp, live_map, meta)

    # Compare only players whose points actually count this gameweek. A bench
    # player is irrelevant to the H2H result unless Bench Boost is active, in
    # which case _squad_view has already marked them as playing.
    g_play = {e: p for e, p in gsq.items() if p["playing"]}
    b_play = {e: p for e, p in bsq.items() if p["playing"]}

    shared = set(g_play) & set(b_play)
    g_only = [g_play[e] for e in g_play if e not in b_play]
    b_only = [b_play[e] for e in b_play if e not in g_play]

    g_only.sort(key=lambda p: -p["points"])
    b_only.sort(key=lambda p: -p["points"])

    g_swing = sum(p["points"] * p["multiplier"] for p in g_only)
    b_swing = sum(p["points"] * p["multiplier"] for p in b_only)

    return {
        "shared_count": len(shared),
        "same_captain": bool(gcap and bcap and gcap["id"] == bcap["id"]),
        "geese": {"captain": gcap, "differentials": g_only,
                  "diff_points": g_swing, "chip": gchip,
                  "bench_points": gp.get("bench_points", 0), "hit": gp.get("hit", 0)},
        "bbbsas": {"captain": bcap, "differentials": b_only,
                   "diff_points": b_swing, "chip": bchip,
                   "bench_points": bp.get("bench_points", 0), "hit": bp.get("hit", 0)},
    }


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


# Approximate first-kickoff times, used ONLY if the fixtures API can't be
# reached. Premier League rounds to the end of November 2026 all fall on a
# Saturday, with no midweek round until 2 December. Exact kick-off times are
# confirmed by TV selection a few weeks ahead, so these are the earliest
# plausible slot rather than gospel — the API value always wins.
FIRST_KICKOFF_FALLBACK = {
    6:  "2026-10-10T11:30:00Z",
    7:  "2026-10-17T11:30:00Z",
    8:  "2026-10-24T11:30:00Z",
    9:  "2026-10-31T12:30:00Z",   # clocks go back 25 Oct, so UK time is UTC
    10: "2026-11-07T12:30:00Z",
    11: "2026-11-21T12:30:00Z",   # international break 9–17 Nov
    12: "2026-11-28T12:30:00Z",
}


@lru_cache(maxsize=None)
def first_kickoff(gw):
    """When the gameweek's earliest match kicks off, as an ISO-8601 UTC string.

    This is what the weekly Teamsheet is timed against. Read live from the
    fixtures API so it stays correct when matches are moved for television.
    """
    try:
        data = _get(API_FIXTURES.format(gw=gw))
        times = [f["kickoff_time"] for f in data if f.get("kickoff_time")]
        if times:
            return min(times)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: no fixture times for GW{gw} ({exc}); using fallback.",
              file=sys.stderr)
    return FIRST_KICKOFF_FALLBACK.get(gw)


@lru_cache(maxsize=None)
def last_kickoff(gw):
    """When the gameweek's final match kicks off, as an ISO-8601 UTC string.

    The Full Time write-up is held until well after this, so the report never
    lands while anyone still has players on the pitch.
    """
    try:
        data = _get(API_FIXTURES.format(gw=gw))
        times = [f["kickoff_time"] for f in data if f.get("kickoff_time")]
        if times:
            return max(times)
    except Exception:  # noqa: BLE001
        pass
    return None


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
            "detail": fixture_detail(geese_player, bbbsas_player, gw,
                                     live_map or live_points_map(gw)),
        })

    if status == "live" and not any_scores:
        status = "upcoming"  # GW is technically current but nothing scored yet

    return {
        "gw": gw,
        "status": status,  # 'live' or 'upcoming'
        "first_kickoff": first_kickoff(gw),
        "fixtures": fixtures,
        "provisional_geese": geese_pts,
        "provisional_bbbsas": bbbsas_pts,
        "provisional_score": f"{geese_pts}\u2013{bbbsas_pts}",
    }


def previous_detail_cache():
    """Detail already computed in a past run, so completed gameweeks aren't
    recalculated (and re-requested) every 15 minutes."""
    try:
        with open("data.json", encoding="utf-8") as fh:
            old = json.load(fh)
    except Exception:  # noqa: BLE001
        return {}
    cache = {}
    for gwrow in old.get("gameweeks", []):
        for fx in gwrow.get("fixtures", []):
            detail = fx.get("detail")
            if detail and _is_current_schema(detail):
                cache[(gwrow["gw"], fx["geese_player"], fx["bbbsas_player"])] = detail
    return cache


def _is_current_schema(detail):
    """Reject cached detail written by an older version of this script.

    Early versions listed bench players in the differentials and marked them
    with a "starting" flag. Those entries must be recomputed rather than
    reused, otherwise old gameweeks keep showing bench players forever.
    """
    for side in ("geese", "bbbsas"):
        block = detail.get(side) or {}
        if "chip" not in block or "bench_points" not in block:
            return False
        for player in block.get("differentials", []):
            if "playing" not in player:
                return False
    return True


# ---------------------------------------------------------------------------
# 4. H2H CALCULATIONS
# ---------------------------------------------------------------------------

def build():
    detail_cache = previous_detail_cache()
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
            key = (gw, geese_player, bbbsas_player)
            detail = detail_cache.get(key)
            if detail is None:
                detail = fixture_detail(geese_player, bbbsas_player, gw,
                                        live_points_map(gw))
            fixtures.append({
                "geese_player": geese_player,
                "geese_score": gs,
                "bbbsas_player": bbbsas_player,
                "bbbsas_score": bs,
                "winner": winner,
                "detail": detail,
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
            "last_kickoff": last_kickoff(gw),
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
        "entry_ids": {name: eid for name, eid in ENTRY_IDS.items() if eid},
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
