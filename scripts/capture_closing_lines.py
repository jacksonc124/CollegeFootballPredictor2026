"""
Standalone entry point for the capture_closing_lines GitHub Action
(.github/workflows/capture_closing_lines.yml). Pulls the current pick log down from
Supabase, re-fetches current market lines for every pre-kickoff game in it, updates
closing_spread_home on each upcoming pick, and pushes the result back up — all without a
running Streamlit process, since this runs on its own schedule close to each slate's
kickoffs (see pick_log.capture_closing_lines's docstring for why the timing matters).

Requires BEARER_TOKEN (CFBD), SUPABASE_URL, and SUPABASE_KEY as environment variables —
GitHub Actions repo secrets, not Streamlit secrets (this never runs inside Streamlit).
"""

import os
import sys

# Python only adds this script's own directory (scripts/) to sys.path, not the repo root —
# so pick_log (which lives at the repo root) isn't importable without this, regardless of
# the invoking shell's current directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pick_log  # noqa: E402


def main() -> int:
    bearer_token = os.environ.get("BEARER_TOKEN")
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not bearer_token:
        print("BEARER_TOKEN not set — nothing to do.")
        return 1
    if not (supabase_url and supabase_key):
        print("SUPABASE_URL/SUPABASE_KEY not set — this job only makes sense with Supabase "
              "sync configured (there'd be no log to update otherwise).")
        return 1

    pick_log.sync_from_supabase(supabase_url, supabase_key)
    updated = pick_log.capture_closing_lines(bearer_token)
    print(f"Updated closing_spread_home on {updated} row(s).")
    pick_log.sync_to_supabase(supabase_url, supabase_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
