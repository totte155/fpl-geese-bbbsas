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
from datetime import datetime, timedelta, timezone

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


# The Full Time write-up is held until this long after the gameweek's final
# match kicks off: 2 hours of football, then a 12-hour wait.
REPORT_HOLD_HOURS = 14


def settled(gw_row):
    """True once enough time has passed since the gameweek's last match.

    FPL's own verification is usually the slower gate, so this rarely bites —
    it's here so the report can never arrive while the week still feels live.
    """
    when = gw_row.get("last_kickoff")
    if not when:
        return True
    try:
        ko = datetime.fromisoformat(when.replace("Z", "+00:00"))
        if ko.tzinfo is None:
            ko = ko.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return True
    return datetime.now(timezone.utc) >= ko + timedelta(hours=REPORT_HOLD_HOURS)


def decide(d, sent):
    """Return (kind, gw) for the story that is due, or (None, None)."""
    gws = S.completed(d)
    if gws:
        latest = gws[-1]
        if latest["gw"] not in sent.get("report", []) and settled(latest):
            return "report", latest["gw"]

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


def mark(kind, gw):
    """Record that a story was delivered. Called only after a successful send."""
    sent = load_sent()
    lst = sent.setdefault(kind, [])
    if gw not in lst:
        lst.append(gw)
        save_sent(sent)
        print(f"Marked {kind} GW{gw} as sent.")
    else:
        print(f"{kind} GW{gw} was already marked.")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--mark":
        return mark(sys.argv[2], int(sys.argv[3]))

    # A cheap dry run: is a story due? Lets the workflow skip installing
    # Chromium on the ~95% of runs where nothing is happening.
    if len(sys.argv) > 1 and sys.argv[1] == "--due":
        kind, _ = decide(S.load(), load_sent())
        emit(due="true" if kind else "false")
        print(f"Due: {kind or 'nothing'}")
        return 0

    d = S.load()
    site = os.environ.get("SITE_URL", "")

    # The archive is rebuilt from data.json every run, not only when something
    # is emailed. That keeps it current as gameweeks finish, and means past
    # weeks appear on their own without any backfill step.
    with open("stories.html", "w", encoding="utf-8") as fh:
        fh.write(S.build_archive(d, site))
    print(f"Archive rebuilt: {len(S.completed(d))} gameweek(s).")

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
    text = S.to_text(built)

    # Written to fixed names so the workflow can attach them, and so the latest
    # of each kind is always available in the repo to copy into WhatsApp.
    for name in (f"{kind}", f"{kind}_gw{built['gw']}"):
        with open(os.path.join(S.OUT_DIR, name + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(S.OUT_DIR, f"{kind}.html"), "w", encoding="utf-8") as fh:
        fh.write(S.to_html(built, site))

    # The matchday / teamsheet graphic. Drawn here so it can be attached to the
    # email and committed alongside the text. Failing to draw it must never stop
    # the story going out, so this is best-effort.
    image = ""
    try:
        import graphic
        image = graphic.build(kind, built["gw"]) or ""
        if image:
            print(f"Graphic: {image}")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: graphic not drawn ({exc}).", file=sys.stderr)

    # NOT marked as sent here. The workflow calls `notify.py --mark <kind> <gw>`
    # only after the email has actually gone out, so a mail failure can never
    # silently tick a week off and skip it forever.
    print(text)
    emit(send="true", kind=kind, gw=str(built["gw"]),
         subject=built["subject"], body_file=f"{S.OUT_DIR}/{kind}.html",
         image=image)
    return 0


if __name__ == "__main__":
    sys.exit(main())
