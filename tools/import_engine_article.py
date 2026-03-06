#!/usr/bin/env python3
"""Import standalone texhtml-engine output into Hugo math page bundles."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import stat
import time
from pathlib import Path

HEAD_RE = re.compile(r"(?is)<head[^>]*>(.*?)</head>")
BODY_RE = re.compile(r"(?is)<body[^>]*>(.*?)</body>")
TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
ARTICLE_RE = re.compile(r"(?is)<article\b[^>]*class=[\"'][^\"']*\bltx_document\b[^\"']*[\"'][^>]*>.*?</article>")
DOC_TITLE_RE = re.compile(r"(?is)<h1\b[^>]*class=[\"'][^\"']*\bltx_title_document\b[^\"']*[\"'][^>]*>.*?</h1>")
AUTHORS_RE = re.compile(r"(?is)<div\b[^>]*class=[\"'][^\"']*\bltx_authors\b[^\"']*[\"'][^>]*>.*?</div>")
DATES_RE = re.compile(r"(?is)<div\b[^>]*class=[\"'][^\"']*\bltx_dates\b[^\"']*[\"'][^>]*>.*?</div>")
TOC_RE = re.compile(r"(?is)<nav\b[^>]*class=[\"'][^\"']*\bltx_TOC\b[^\"']*[\"'][^>]*>.*?</nav>")
PAGE_FOOTER_RE = re.compile(r"(?is)<footer\b[^>]*class=[\"'][^\"']*\bltx_page_footer\b[^\"']*[\"'][^>]*>.*?</footer>")
PARAGRAPH_RE = re.compile(r"(?is)<p\b[^>]*class=[\"'][^\"']*\bltx_p\b[^\"']*[\"'][^>]*>(.*?)</p>")
LINK_RE = re.compile(r"(?is)<link\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>")
SCRIPT_RE = re.compile(r"(?is)<script\s+[^>]*src=[\"']([^\"']+)[\"'][^>]*>\s*</script>")
ATTR_RE = re.compile(r"(?i)(src|href)=(['\"])([^'\"]+)\2")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="Output slug in content/math/<slug>")
    parser.add_argument("--engine-dir", required=True, help="Directory containing engine index.html and assets")
    parser.add_argument("--site-root", default=".", help="Hugo site root")
    parser.add_argument("--title", default="", help="Override page title")
    parser.add_argument("--date", default="", help="Override page date in YYYY-MM-DD format")
    parser.add_argument("--summary", default="", help="Page summary")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--categories", default="", help="Comma-separated categories")
    return parser.parse_args()


def normalize_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_html(index_html: str) -> tuple[str, str, str]:
    head_match = HEAD_RE.search(index_html)
    body_match = BODY_RE.search(index_html)
    title_match = TITLE_RE.search(index_html)
    if not body_match:
        raise ValueError("Could not locate <body> in engine output")
    head = head_match.group(1) if head_match else ""
    body = body_match.group(1)
    title = html.unescape(TAG_RE.sub("", title_match.group(1)).strip()) if title_match else ""
    return head, body, title


def to_blog_body(body: str) -> str:
    # Prefer the semantic LaTeXML article block and discard page shell wrappers.
    m = ARTICLE_RE.search(body)
    out = m.group(0) if m else body
    # Avoid duplicate title; Hugo renders the page title in the post header.
    out = DOC_TITLE_RE.sub("", out)
    # Hugo already renders author/date metadata; remove LaTeXML's maketitle shell.
    out = AUTHORS_RE.sub("", out)
    out = DATES_RE.sub("", out)
    # The site renders its own navigation TOC for math pages.
    out = TOC_RE.sub("", out)
    # Drop generated LaTeXML footer/logo noise if present.
    out = PAGE_FOOTER_RE.sub("", out)
    return out.strip()


def to_public_asset(slug: str, path_value: str) -> str:
    if not path_value or path_value.startswith(("http://", "https://", "data:", "#", "mailto:")):
        return path_value
    cleaned = path_value.lstrip("./")
    return f"/math-assets/{slug}/{cleaned}"


def rewrite_body_assets(slug: str, body: str) -> str:
    def repl(match: re.Match[str]) -> str:
        attr, quote, value = match.groups()
        return f"{attr}={quote}{to_public_asset(slug, value)}{quote}"

    return ATTR_RE.sub(repl, body)


def build_manifest(slug: str, head: str) -> dict[str, list[str]]:
    styles = [to_public_asset(slug, href) for href in LINK_RE.findall(head)]
    scripts = [to_public_asset(slug, src) for src in SCRIPT_RE.findall(head)]
    return {"styles": styles, "scripts": scripts}


def extract_text(body: str) -> str:
    text = TAG_RE.sub(" ", body)
    text = html.unescape(text)
    return SPACE_RE.sub(" ", text).strip()


def summarize_text(text: str, max_chars: int = 240) -> str:
    cleaned = SPACE_RE.sub(" ", text).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars]
    last_space = cut.rfind(" ")
    if last_space > 80:
        cut = cut[:last_space]
    return cut.rstrip(" ,;:") + "..."


def derive_summary(body: str, max_chars: int = 240) -> str:
    for paragraph_html in PARAGRAPH_RE.findall(body):
        candidate = extract_text(paragraph_html)
        if len(candidate) < 40:
            continue
        lowered = candidate.lower()
        if lowered.startswith(("contents", "keywords", "msc", "mathematics subject classification")):
            continue
        return summarize_text(candidate, max_chars=max_chars)
    return summarize_text(extract_text(body), max_chars=max_chars)


def write_front_matter(
    target: Path,
    title: str,
    date_value: str,
    summary: str,
    tags: list[str],
    categories: list[str],
) -> None:
    if not date_value:
        date_value = dt.date.today().isoformat()

    lines = [
        "---",
        f'title: "{title.replace("\"", "\\\"")}"',
        f"date: {date_value}",
        'type: "math"',
        f'summary: "{summary.replace("\"", "\\\"")}"' if summary else "",
        "useEngineStyles: false",
        "showMathToc: true",
    ]

    if tags:
        lines.append("tags: [" + ", ".join(f'"{t}"' for t in tags) + "]")
    if categories:
        lines.append("categories: [" + ", ".join(f'"{c}"' for c in categories) + "]")

    lines.extend(["---", ""])
    target.write_text("\n".join(line for line in lines if line != "") + "\n", encoding="utf-8")


def sync_assets(engine_dir: Path, asset_dir: Path) -> None:
    def handle_remove_readonly(func, path, exc_info):
        # Windows can copy files with read-only bit; make writable and retry.
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    def remove_path(path: Path) -> None:
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path, onerror=handle_remove_readonly)
        else:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()

    if asset_dir.exists():
        last_err: Exception | None = None
        for _ in range(5):
            try:
                shutil.rmtree(asset_dir, onerror=handle_remove_readonly)
                last_err = None
                break
            except PermissionError as exc:
                # File can be temporarily locked (e.g. by hugo server or AV scanner).
                last_err = exc
                time.sleep(0.25)
        if last_err is not None:
            raise RuntimeError(
                f"Could not replace asset directory '{asset_dir}'. "
                "Close processes that may lock files (e.g. hugo server) and retry."
            ) from last_err
    asset_dir.mkdir(parents=True, exist_ok=True)

    for child in engine_dir.iterdir():
        if child.name.lower() == "index.html":
            continue
        destination = asset_dir / child.name
        remove_path(destination)
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def sync_global_fonts(engine_dir: Path, site_root: Path) -> None:
    engine_fonts = engine_dir / "fonts"
    if not engine_fonts.exists() or not engine_fonts.is_dir():
        return

    site_fonts = site_root / "static" / "fonts"
    site_fonts.mkdir(parents=True, exist_ok=True)
    for font_file in engine_fonts.glob("*.otf"):
        shutil.copy2(font_file, site_fonts / font_file.name)


def main() -> None:
    args = parse_args()

    slug = args.slug.strip()
    if not slug:
        raise ValueError("slug must be non-empty")

    engine_dir = Path(args.engine_dir).resolve()
    site_root = Path(args.site_root).resolve()
    index_file = engine_dir / "index.html"

    if not index_file.exists():
        raise FileNotFoundError(f"Missing engine output: {index_file}")

    raw_html = index_file.read_text(encoding="utf-8", errors="ignore")
    head, body, extracted_title = parse_html(raw_html)

    final_title = args.title.strip() or extracted_title or slug.replace("-", " ").title()
    final_summary = args.summary.strip()

    body_rewritten = rewrite_body_assets(slug, to_blog_body(body))
    manifest = build_manifest(slug, head)
    search_text = extract_text(body_rewritten)
    if not final_summary:
        final_summary = derive_summary(body_rewritten)

    bundle_dir = site_root / "content" / "math" / slug
    static_assets_dir = site_root / "static" / "math-assets" / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)

    write_front_matter(
        target=bundle_dir / "index.md",
        title=final_title,
        date_value=args.date.strip(),
        summary=final_summary,
        tags=normalize_list(args.tags),
        categories=normalize_list(args.categories),
    )
    (bundle_dir / "body.html").write_text(body_rewritten + "\n", encoding="utf-8")
    (bundle_dir / "head-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (bundle_dir / "search.txt").write_text(search_text + "\n", encoding="utf-8")

    sync_assets(engine_dir, static_assets_dir)
    sync_global_fonts(engine_dir, site_root)
    print(f"Imported '{slug}' into {bundle_dir}")


if __name__ == "__main__":
    main()
