# CFB SP+ vs Market Spread Model

This script builds weekly college football against-the-spread (ATS) picks by comparing SP+ ratings to market point spreads from the CollegeFootballData (CFBD) API. It:

- Downloads and caches SP+ team ratings.
- Downloads and caches weekly betting lines.
- Computes a model spread (SP+ + home-field).
- Computes the edge vs. the market and implied cover probabilities.
- Prints ranked picks and saves them to CSV.

---

## Requirements

- Python 3.10+ (for type hints like `list[str]` and `int | None`)
- CFBD Python client
- pandas
- streamlit (for the `app.py` dashboard)

Install dependencies (in a virtual environment — see note below):

```bash
python -m venv .venv
.venv\Scripts\activate   # or: source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
```

> **Use a virtual environment.** The `cfbd` package requires `pydantic<2`, which will
> conflict with (and silently downgrade) a global environment that has `pydantic>=2`
> installed for other tools — breaking them. A project-local `.venv` keeps `cfbd`'s
> pydantic 1.x install isolated from everything else on your machine.

You'll also need a CFBD API bearer token (get one at [collegefootballdata.com](https://collegefootballdata.com/key)):

- For `cfbpredict.py`, set the `BEARER_TOKEN` environment variable.
- For `app.py` (Streamlit), either set `BEARER_TOKEN` as an environment variable, or add it to `.streamlit/secrets.toml`:

```toml
BEARER_TOKEN = "your-token-here"
```

### Optional: persistent pick log (Supabase)

The pick log (`pick_log.py`) normally lives only on local disk, which a Streamlit Cloud
redeploy wipes. To make it survive redeploys, create a free project at
[supabase.com](https://supabase.com), run `supabase/schema.sql` once in that project's SQL
Editor, then add these secrets:

```toml
SUPABASE_URL = "https://your-project-ref.supabase.co"
SUPABASE_KEY = "your-service-role-key"   # Settings -> API -> service_role key
```

Absent entirely, the app works exactly as before (local-disk-only). See pick_log.py's
`sync_from_supabase`/`sync_to_supabase` for how this is used.

Run the dashboard with:

```bash
streamlit run app.py
```

## Project layout

- `model.py` — shared fetchers (SP+ ratings, betting lines, team logos), math helpers, and pick-building logic used by both entry points below.
- `app.py` — Streamlit dashboard (Pick'em top 12, parlays, championship favorites).
- `cfbpredict.py` — CLI script that prints picks and saves them to CSV.
- `backtest.py` — grades a past week's picks against actual final scores and reports accuracy/calibration by tier. Run with `python backtest.py <year> <week> [season_type]`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```
