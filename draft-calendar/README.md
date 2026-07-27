# Draft Calendar

Automatically publishes a subscribed `.ics` feed of every league's draft time from Yahoo Fantasy, so it stays current in your calendar without re-importing anything.

**Subscribe URL:** `https://elfbarenjoyer.github.io/dynastySNS/calendar/draft.ics`

- **Google Calendar**: Other calendars → **+** → "From URL" → paste the link
- **Apple Calendar**: File → New Calendar Subscription → paste the link
- **Outlook**: Add calendar → Subscribe from web → paste the link

## How it works

A GitHub Actions workflow runs hourly, checks Yahoo's API for each tracked league's draft time, regenerates the `.ics` feed if anything changed, and pushes it live. The script self-throttles: it only re-checks Yahoo every 24 hours for drafts far out (or not yet scheduled), every 6 hours inside the final week, and hourly on draft day itself — this keeps API usage minimal while catching same-day rescheduling.

## Leagues tracked

See `leagues.json`. Currently tracking six leagues:

| League | 2026 ID |
|---|---|
| SnSAllStars (DynastySnS) | `470.l.8226` |
| Legends Keeper League | `470.l.554803` |
| Suckem and Shedep | `470.l.8231` |
| Kibbles and Vicks | `470.l.8325` |
| TOP TIER | `470.l.226018` |
| Turn Down For Watt | `470.l.644501` |

A league only appears on the calendar once Yahoo has a scheduled `draft_time` for it (self-drafts and not-yet-scheduled live drafts are silently omitted until then).

## **Next year: Adding new leagues**

When 2027 rolls around and Yahoo issues new league IDs (the `470` prefix will change to `475` or whatever that season's code is):

1. Open `leagues.json`
2. For each league, get the new ID from its Yahoo URL: `football.fantasysports.yahoo.com/f1/<NEW_ID>` → write it as `"475.l.<NEW_ID>"`
3. The script will automatically re-pin itself every season using Yahoo's `renewed` field — no other changes needed
4. If you've joined a new league and want to track it: add a new entry to `leagues.json` with its `display_name` and current league ID, and the workflow will start tracking it on the next run

That's it — no code changes, no re-authentication, just update the league IDs in one JSON file.

## How the automation works (GitHub Actions)

The workflow in `.github/workflows/draft-calendar.yml`:
- Triggers hourly (`0 * * * *`) or manually via `workflow_dispatch` (Actions tab → Run workflow)
- Writes the `YAHOO_OAUTH_TOKEN` secret to a temp file (only lives during the run, never committed)
- Runs `export_draft_calendar.py`, which fetches draft times and updates `leagues.json`, `state.json`, and `calendar/draft.ics`
- Only commits/pushes if something actually changed

The workflow will auto-disable if the repo has zero commits for 60 days (GitHub's standard safety), but in practice this repo gets dashboard updates throughout the season, and this workflow itself commits whenever a league's draft time changes — so it stays enabled. If it ever silently disables anyway, just click "Enable workflow" on the Actions tab, or manually trigger a run via `workflow_dispatch`.

## Local reference (not used by the workflow)

The main fantasy football project has a `draft-calendar/` folder with the same scripts, just for reference. The live copy runs in this repo via GitHub Actions; the local copy is no longer used.
