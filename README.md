# FPL Geese vs BBBSAS — H2H League Tracker (2026/27)

A self-updating scoreboard for the eight-player head-to-head competition. One
link, opens on any phone, always current. No app, no logins for the players.

**Geese:** Max · Phil · Dorian · Torsten  
**BBBSAS:** Tommi · Pat · Frej · Tej

## How it works (the "set-and-forget" bit)

Three moving parts, all free, all on GitHub:

1. **`update_data.py`** fetches each manager's gameweek points from the official
   FPL API, works out the four H2H fixtures per gameweek, and writes `data.json`.
2. **A scheduled GitHub Action** (`.github/workflows/update.yml`) runs that
   script a few times a day and commits the fresh `data.json` back to the repo.
3. **`index.html`** is the dashboard, served free by **GitHub Pages**. It just
   reads `data.json` from the same site — so there's no FPL "CORS" problem that
   you'd hit if you tried to call the FPL API straight from a web page.

You set it up once. After that it updates itself every gameweek.

## One-time setup (about 10 minutes)

### 1. Add the eight Entry IDs
Open `update_data.py` and fill in the `ENTRY_IDS` block. To find someone's
Entry ID: open their FPL **Points** page while logged in — the number in the URL
`.../entry/<ID>/event/...` is it. (You can also read it off the Gameweek History
page.) Leave the schedule alone; it's already built for GW1–GW20.

### 2. Put it on GitHub
- Create a **new repository** (public is simplest and keeps it free), e.g.
  `fpl-geese-bbbsas`.
- Upload all four files, keeping the folder layout:
  ```
  index.html
  update_data.py
  data.json
  .github/workflows/update.yml
  ```

### 3. Turn on GitHub Pages
- Repo **Settings → Pages**.
- **Source:** "Deploy from a branch". **Branch:** `main`, folder `/ (root)`. Save.
- After a minute you'll get a URL like
  `https://<your-username>.github.io/fpl-geese-bbbsas/` — **that's the link you
  share with the group.**

### 4. Let the Action run
- Repo **Settings → Actions → General → Workflow permissions** →
  set to **"Read and write permissions"** and save. (This lets the job commit the
  updated `data.json`.)
- Go to the **Actions** tab, pick **"Update FPL H2H data"**, and click
  **"Run workflow"** once to prove it works. It'll fetch data and update the page.

That's it. From now on it refreshes on its own.

## Sharing it with the players
Send them the GitHub Pages link. It works on any phone browser, and they can
"Add to Home Screen" so it behaves like an app. Nothing to install.

## Changing things later
- **Fixture schedule** — edit `ROUND_ROBIN` / `LAST_GAMEWEEK` in `update_data.py`.
- **A player or ID changes** — edit the `GEESE` / `BBBSAS` / `ENTRY_IDS` blocks.
- **Raw points instead of net** — set `USE_NET_POINTS = False` (default counts
  points hits, matching FPL's own H2H scoring).

## The live gameweek panel
Under the main scoreboard there's a **Live** panel showing the current
gameweek's four matchups with provisional live scores (captain doubled, hits
deducted). It's clearly separated from the table: **live scores never count
towards the standings or the cumulative chart until the gameweek is finished.**
Before a gameweek kicks off it shows the four upcoming matchups instead.

Because the browser can't call the FPL API directly, "live" means *as fresh as
the last update run*. The schedule refreshes every ~15 minutes (see
`update.yml`), which is near-live for a casual league; you can make it more or
less frequent there.

## Good to know
- The **table and chart** only ever use **completed** gameweeks — a week counts
  once the PL marks it finished *and* all eight scores are in. Future weeks
  never affect the standings.
- Sample scores are in `data.json` now so you can see the design before the
  season starts. The first real run overwrites them.
- GitHub pauses scheduled Actions if a repo has had no commits for 60 days. The
  weekly data commits normally keep it awake; if the league goes quiet in the
  off-season, one manual "Run workflow" wakes it back up.
# fpl-geese-bbbsas
