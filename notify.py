#!/usr/bin/env python3
"""
Decides whether a weekly story is due, writes it, and records that it was sent.

Run by the GitHub Action. It is deliberately idempotent: each gameweek gets at
most one Teamsheet and one Full Time, tracked in stories/sent.json. That means
the workflow can run as often as it likes — several times a day is fine — and
nothing is ever sent twice. It also means a missed or delayed run just sends
late rather than not at all, which matters because GitHub's scheduler is
best-effort.

Order of preference when both are due: the report goes first, because the
week that just finished is the bigger story.
"""

import json
import os
import sys
from datetime import datetime, timezone

import story as S

SENT_FILE = os.path.join(S.OUT_DIR, "sent.json")


def load_sent():
    try:
        with open(SENT_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 — first run, or file not created yet
        return {"preview": [], "report": []}


def save_sent(sent):
    os.makedirs(S.OUT_DIR, exist_ok=True)
    with open(SENT_FILE, "w", encoding="utf-8") as fh:
        json.dump(sent, fh, indent=2)


def picks_are_public(live):
    """Captains and differentials only exist once the deadline has passed."""
    return any(f.get("detail") for f in (live or {}).get("fixtures", []))


def kicked_off(live):
    """True once the gameweek's first match has started.

    The Teamsheet is timed to first kick-off rather than to the deadline: by
    then every squad is locked and public, and nobody is reading team news.
    first_kickoff comes from the fixtures API, so moved matches are handled.
    If the time is missing entirely, fall back to 'picks are public', which is
    about 90 minutes earlier — better early than never.
    """
    when = (live or {}).get("first_kickoff")
    if not when:
        return True
    try:
        ko = datetime.fromisoformat(when.replace("Z", "+00:00"))
        if ko.tzinfo is None:
            ko = ko.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001 — unparseable timestamp, don't block the send
        return True
    return datetime.now(timezone.utc) >= ko


def decide(d, sent):
    """Return (kind, gw) for the story that is due, or (None, None)."""
    gws = S.completed(d)
    if gws:
        latest = gws[-1]["gw"]
        if latest not in sent.get("report", []):
            return "report", latest

    live = d.get("live")
    if live and picks_are_public(live) and kicked_off(live):
        if live["gw"] not in sent.get("preview", []):
            return "preview", live["gw"]

    return None, None


def emit(**kw):
    """Hand values back to the workflow."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        for k, v in kw.items():
            print(f"{k}={v}")
        return
    with open(path, "a", encoding="utf-8") as fh:
        for k, v in kw.items():
            fh.write(f"{k}={v}\n")


def main():
    d = S.load()
    sent = load_sent()
    kind, gw = decide(d, sent)

    if not kind:
        print("Nothing due.")
        emit(send="false")
        return 0

    built = S.build_preview(d) if kind == "preview" else S.build_report(d, gw)
    if not built:
        print(f"{kind} for GW{gw} could not be built.", file=sys.stderr)
        emit(send="false")
        return 0

    os.makedirs(S.OUT_DIR, exist_ok=True)
    site = os.environ.get("SITE_URL", "")
    text = S.to_text(built)

    # Written to fixed names so the workflow can attach them, and so the latest
    # of each kind is always available in the repo to copy into WhatsApp.
    for name in (f"{kind}", f"{kind}_gw{built['gw']}"):
        with open(os.path.join(S.OUT_DIR, name + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(S.OUT_DIR, f"{kind}.html"), "w", encoding="utf-8") as fh:
        fh.write(S.to_html(built, site))

    sent.setdefault(kind, []).append(built["gw"])
    save_sent(sent)

    print(text)
    emit(send="true", kind=kind, gw=str(built["gw"]),
         subject=built["subject"], body_file=f"{S.OUT_DIR}/{kind}.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
