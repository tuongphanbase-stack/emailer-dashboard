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
