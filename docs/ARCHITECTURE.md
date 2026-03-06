# Architecture

This site uses a strict three-layer model:

1. `texhtml-engine` stays standalone and generates complete HTML artifacts.
2. `tools/import_engine_article.py` adapts engine output into Hugo page bundles.
3. Hugo (`content/`, `layouts/`, `static/`) renders site navigation, taxonomy, search, and page chrome.

## Contract

Each imported article is a leaf bundle at `content/math/<slug>/`:

- `index.md`: metadata and taxonomy.
- `body.html`: sanitized body fragment from engine `index.html`.
- `head-manifest.json`: styles/scripts required by that article.
- `search.txt`: plain-text extraction for future search pipeline upgrades.

Static assets are synced to `static/math-assets/<slug>/` without touching engine internals.