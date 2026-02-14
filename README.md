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

Install dependencies:

```bash
pip install cfbd pandas
