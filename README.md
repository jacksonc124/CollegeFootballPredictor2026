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
