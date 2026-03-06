# Publishing Workflow

## One-time setup

- Keep `texhtml-engine` in a separate repository.
- Build engine output for each article into a local directory containing `index.html` and assets.

## Import an article

Example:

```bash
python tools/import_engine_article.py on-two-notions \
  --engine-dir C:/path/to/engine/output/on-two-notions \
  --title "On Two Notions of a Gerbe over a Stack" \
  --date 2026-03-02 \
  --tags gerbes,stacks,category-theory \
  --categories research-notes
```

## Build site

```bash
hugo --minify
```

## Development server

```bash
hugo server -D
```

## Migrate WordPress XML (fidelity-first)

```bash
python tools/import_wordpress_xml.py C:/path/to/wordpress-export.xml
```

This importer:

- Imports only published `post` and `page` entries.
- Preserves title, slug, date, categories, and tags.
- Writes date URLs as `/YYYY/MM/DD/slug/`.
- Keeps `<content:encoded>` HTML verbatim except image URL rewrites.
- Mirrors images to `static/wp-media/...` and rewrites links to local paths.
