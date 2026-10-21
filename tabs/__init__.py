"""Per-tab Streamlit rendering modules. Each exposes render(ctx), where ctx is the
types.SimpleNamespace app.py builds after fetching/filtering the slate — see app.py for
exactly what it carries (df, logos, rankings, the cached fetch wrappers tabs need, etc.)."""
