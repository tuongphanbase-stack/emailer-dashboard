# Emailer Dashboard

One page to watch all the emailer bots: each one's latest GitHub Actions run,
its status, the last email it sent, and a button to run it now.

## Setup

1. The list of bots is in `config.json`. Add, remove or rename bots there;
   `index.html` never needs editing. Each entry has:
   - `name`: the repo name
   - `category`: `price`, `finance` or `social`
   - `workflow`: the workflow file name in that repo's `.github/workflows/`
2. Publish with GitHub Pages: Settings -> Pages -> Source: `main` branch,
   `/` root. The page will be at
   https://tuongphanbase.github.io/emailer-dashboard/
3. Optional: paste a GitHub token into the **TOKEN** box on the page. It's
   needed for the "run now" button and for higher API rate limits. The token
   is saved only in your own browser.

The "last email" line reads a `latest.json` file from each bot's repo; bots
that don't write one show "no latest.json yet".

## Pages

- `index.html` — the bot dashboard, with the **Thị trường** (markets) charts below it
- `prices.html` — **Giá hôm nay**: today's prices on one page, made for phones
- `projects.html` — every website and bot, from `config.json` → `projects`

Every chart and table has a **CSV** button (download the data) and a **⤢**
button (a large view; long tables show all rows there).

## Markets charts and the morning summary email

The **Daily Summary** workflow (`.github/workflows/daily-summary.yml`) runs
`daily_summary.py`:

- **Every 3 hours** it collects the latest data from the emailer repos (gold,
  exchange rates, VN stocks, interest rates, RAM/SSD/laptop prices, phone
  prices) into `data/summary.json`. The dashboard pages draw it.
- **Every morning at 7:45 (Vietnam time)** it also sends one summary email
  with all of the above.

Secrets (Settings -> Secrets and variables -> Actions):

- `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `SUMMARY_RECIPIENT`: for the email
- `GH_READ_TOKEN`: only needed once the emailer repos are **private**. Create
  a fine-grained token (GitHub Settings -> Developer settings -> Personal
  access tokens) with **Contents: Read-only** on those repos.

This repo itself must stay **public** for GitHub Pages to work on a free
account. `data/summary.json` only contains public market prices.

Sections with no data yet show "chưa có dữ liệu" in both the email and the
charts. Charts fill in as history builds up.

## Adding a data source

Sources are listed in `config.json` → `summary_sources` and run in parallel.
Each one returns generic **blocks** — `chart`, `tiles` or `table` — and the
email (`daily_summary.py`) and the pages (`markets.js`) draw any block, so a
new source needs no change to either.

- **A CSV history needs no code.** If an emailer saves rows of
  `time,key,value`, add an entry like this:

  ```json
  {"source": "csv_history", "id": "oil", "title": "Giá xăng", "icon": "⛽",
   "repo": "fuel-price-emailer", "path": "history.csv",
   "key_col": "product", "value_col": "price", "limit": 6, "unit": "VND"}
  ```

- **Anything else:** add a function to `summary_sources.py`:

  ```python
  @source("weather", "Thời tiết", icon="⛅")
  def weather(opt):
      data = json.loads(fetch_file("weather-emailer", "latest.json") or "null")
      if not data:
          return empty("chưa có dữ liệu thời tiết")
      return {"ok": True, "blocks": [table([col("Thành phố"), col("°C", "num")], data["rows"])],
              "text": ["..."]}
  ```

  then add `"weather"` to `summary_sources`. Blocks are described at the top
  of `summary_core.py`.

`python daily_summary.py sources` lists the available sources;
`python -m unittest discover tests` runs the tests.

To preview the email locally without sending it:
`python daily_summary.py collect && python daily_summary.py preview`
(writes `email_preview.html`).
