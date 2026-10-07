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
   https://tuongphanbase-stack.github.io/emailer-dashboard/
3. Optional: paste a GitHub token into the **TOKEN** box on the page. It's
   needed for the "run now" button and for higher API rate limits. The token
   is saved only in your own browser.

The "last email" line reads a `latest.json` file from each bot's repo; bots
that don't write one show "no latest.json yet".

## Markets charts and the morning summary email

The **Daily Summary** workflow (`.github/workflows/daily-summary.yml`) runs
`daily_summary.py`:

- **Every 3 hours** it collects the latest data from the emailer repos (gold,
  exchange rates, VN stocks, interest rates, RAM/SSD/laptop prices) into
  `data/summary.json`. The **Markets** section of the dashboard draws its
  charts from that file (7D / 30D / 90D range buttons above the charts).
- **Every morning at 7:45 (Vietnam time)** it also sends one summary email
  with all of the above.

Secrets (Settings -> Secrets and variables -> Actions):

- `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `SUMMARY_RECIPIENT`: for the email
- `GH_READ_TOKEN`: only needed once the emailer repos are **private**. Create
  a fine-grained token (GitHub Settings -> Developer settings -> Personal
  access tokens) with **Contents: Read-only** on those repos.

This repo itself must stay **public** for GitHub Pages to work on a free
account. `data/summary.json` only contains public market prices.

Sections with no data yet (for example gold, until gold-price-emailer has run
successfully) show "no data yet" in both the email and the charts. Charts fill
in as history builds up.

To preview the email locally without sending it:
`python daily_summary.py collect && python daily_summary.py preview`
(writes `email_preview.html`).
