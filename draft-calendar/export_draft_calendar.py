"""Regenerate the draft-times .ics feed from Yahoo.

Usage (GitHub Actions):
    python draft-calendar/export_draft_calendar.py

The workflow provides YAHOO_OAUTH_TOKEN (path to the oauth json).
The script regenerates draft-calendar/leagues.json, draft-calendar/state.json,
and ../calendar/draft.ics if anything changed; the workflow handles git operations.

Design notes:
  - Draft time comes from Yahoo's `league.settings()['draft_time']` (a UTC epoch),
    present once a live draft is scheduled and absent otherwise.
  - One shared OAuth token covers every league on this Yahoo account.
  - Each league is throttled (24h / 6h / 1h depending on how close its draft is)
    so a single hourly scheduled run doesn't hammer Yahoo's API.
  - The .ics is only rewritten when a league's draft_time actually changed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import yahoo_fantasy_api as yfa  # noqa: E402
from yahoo_oauth import OAuth2  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
LEAGUES_JSON = SCRIPT_DIR / "leagues.json"
STATE_JSON = SCRIPT_DIR / "state.json"
OAUTH_PATH = Path(os.getenv("YAHOO_OAUTH_TOKEN", str(SCRIPT_DIR / "yahoo_oauth.json")))
ICS_OUTPUT = ROOT / "calendar" / "draft.ics"

DRAFT_DURATION = timedelta(hours=3)
REMINDER_BEFORE = timedelta(minutes=60)

DAY = 24 * 3600


def main() -> None:
    leagues = _load_json(LEAGUES_JSON)
    state = _load_json(STATE_JSON)
    now = datetime.now(timezone.utc)

    oauth = _init_oauth(OAUTH_PATH)
    game = yfa.Game(oauth, "nfl")

    for key, league_cfg in leagues.items():
        entry = state.setdefault(key, {})
        if entry.get("done"):
            continue
        if not os.getenv("FORCE_CHECK") and not _is_due(entry, now):
            continue

        league_id = league_cfg["league_id"]
        league = game.to_league(league_id)
        settings = league.settings()

        draft_time = settings.get("draft_time")
        entry["draft_time"] = int(draft_time) if draft_time else None
        entry["last_checked_utc"] = now.isoformat()
        entry["done"] = settings.get("draft_status") == "postdraft"

        renewed = settings.get("renewed")
        if renewed:
            new_league_id = renewed.replace("_", ".l.", 1)
            if new_league_id != league_id:
                print(f"{key}: rolling league id {league_id} -> {new_league_id}")
                league_cfg["league_id"] = new_league_id

        print(
            f"{key}: draft_time={entry['draft_time']} "
            f"({_fmt(entry['draft_time'])}) done={entry['done']}"
        )

    _save_json(LEAGUES_JSON, leagues)
    _save_json(STATE_JSON, state)

    signature = {
        key: state[key].get("draft_time")
        for key in leagues
        if state.get(key, {}).get("draft_time")
    }
    if signature == state.get("_published_signature"):
        print("No draft-time changes since last publish; leaving draft.ics untouched.")
        return

    ics_text = _build_ics(leagues, state)
    ICS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ICS_OUTPUT.write_text(ics_text, encoding="utf-8", newline="\r\n")
    print(f"Wrote {ICS_OUTPUT}")

    state["_published_signature"] = signature
    _save_json(STATE_JSON, state)


def _is_due(entry: Dict[str, object], now: datetime) -> bool:
    last_checked = entry.get("last_checked_utc")
    if last_checked is None:
        return True
    elapsed = (now - datetime.fromisoformat(last_checked)).total_seconds()

    draft_time = entry.get("draft_time")
    if not draft_time:
        threshold = DAY
    else:
        days_out = (datetime.fromtimestamp(draft_time, tz=timezone.utc) - now).days
        if days_out <= 1:
            threshold = 0
        elif days_out <= 7:
            threshold = 6 * 3600
        else:
            threshold = DAY

    return elapsed >= threshold


def _build_ics(leagues: Dict[str, Dict[str, str]], state: Dict[str, Dict[str, object]]) -> str:
    now_stamp = _ics_dt(datetime.now(timezone.utc))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//fantasy-football//draft-calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Fantasy Draft Times",
    ]

    for key, league_cfg in sorted(leagues.items()):
        draft_time = state.get(key, {}).get("draft_time")
        if not draft_time:
            continue
        start = datetime.fromtimestamp(draft_time, tz=timezone.utc)
        end = start + DRAFT_DURATION
        season = league_cfg["league_id"].split(".", 1)[0]
        name = league_cfg["display_name"]

        lines += [
            "BEGIN:VEVENT",
            f"UID:{key}-draft-{season}@fantasy-football.local",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART:{_ics_dt(start)}",
            f"DTEND:{_ics_dt(end)}",
            *_fold(f"SUMMARY:{name} Fantasy Draft"),
            *_fold(f"DESCRIPTION:Yahoo Fantasy Football live draft for {name}."),
            "URL:https://football.fantasysports.yahoo.com",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "DESCRIPTION:Draft starting soon",
            f"TRIGGER:-PT{int(REMINDER_BEFORE.total_seconds() // 60)}M",
            "END:VALARM",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\n".join(lines) + "\n"


def _fold(line: str, limit: int = 75) -> list[str]:
    """RFC 5545 line folding: continuation lines start with a single space."""
    if len(line) <= limit:
        return [line]
    folded = [line[:limit]]
    rest = line[limit:]
    while rest:
        folded.append(" " + rest[: limit - 1])
        rest = rest[limit - 1 :]
    return folded


def _ics_dt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _fmt(epoch: Optional[int]) -> str:
    if not epoch:
        return "not scheduled"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _init_oauth(oauth_path: Path) -> OAuth2:
    if not oauth_path.exists():
        raise FileNotFoundError(f"Yahoo OAuth file not found: {oauth_path}")
    oauth = OAuth2(None, None, from_file=str(oauth_path))
    if not oauth.token_is_valid():
        oauth.refresh_access_token()
    return oauth


def _load_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: Dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
