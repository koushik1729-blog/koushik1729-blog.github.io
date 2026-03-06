#!/usr/bin/env python3
"""Fidelity-first WordPress XML importer for Hugo.

Rules implemented:
- Import only published posts and pages.
- Preserve title, slug, date, tags, and categories.
- Keep <content:encoded> HTML verbatim except image URL rewriting.
- Mirror images locally and rewrite to /wp-media/... paths.
- Emit date-based URLs: /YYYY/MM/DD/slug/
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

WP_NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "wp": "http://wordpress.org/export/1.2/",
}

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".tif", ".tiff", ".avif")
ATTR_URL_RE = re.compile(r"""(?i)(\b(?:src|href|data-src)\s*=\s*['"])([^'"]+)(['"])""")
SRCSET_RE = re.compile(r"""(?i)(\bsrcset\s*=\s*['"])([^'"]+)(['"])""")
LATEX_SHORTCODE_RE = re.compile(r"\$latex\s+(.+?)\$", re.DOTALL)
DISPLAY_PAR_RE = re.compile(r"(?s)<p>\s*\\\((.+?)\\\)\s*</p>")
MISMATCH_DISPLAY_RE = re.compile(r"\\\[([^<]*?)\\\)")
MISMATCH_INLINE_RE = re.compile(r"\\\(([^<]*?)\\\]")
MATH_SEGMENT_RE = re.compile(r"(\\\((.+?)\\\)|\\\[(.+?)\\\])", re.DOTALL)
UPLOAD_DATE_RE = re.compile(r"/(20\d{2})/(0[1-9]|1[0-2])/")
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml_file", help="WordPress export XML (WXR) file")
    parser.add_argument("--site-root", default=".", help="Hugo site root")
    parser.add_argument("--content-subdir", default="content/wp-import", help="Target content subdirectory")
    parser.add_argument("--media-subdir", default="wp-media", help="Media subdirectory name under static/")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report, without writing files")
    return parser.parse_args()


def safe_text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_date(raw: str) -> dt.datetime:
    raw = raw.strip()
    if not raw or raw == "0000-00-00 00:00:00":
        raise ValueError("missing date")
    return dt.datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")


def ensure_slug(raw_slug: str, fallback_title: str, post_id: str) -> str:
    slug = raw_slug.strip()
    if slug:
        return slug
    base = fallback_title.strip().lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    if not base:
        base = f"wp-{post_id or 'item'}"
    return base


def is_image_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.lower()
    return path.endswith(IMAGE_EXTENSIONS)


def normalize_image_url(raw_url: str, base_url: str) -> str:
    return urllib.parse.urljoin(base_url, raw_url)


def build_media_relpath(url: str, fallback_date: dt.datetime) -> Path:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path
    file_name = Path(path).name or "image"
    file_name = SAFE_NAME_RE.sub("-", file_name)
    if "." not in file_name:
        file_name += ".bin"

    match = UPLOAD_DATE_RE.search(path)
    if match:
        year, month = match.group(1), match.group(2)
    else:
        year, month = str(fallback_date.year), f"{fallback_date.month:02d}"

    unique_prefix = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return Path(year) / month / f"{unique_prefix}-{file_name}"


def download_binary(url: str, destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # nosec: B310
            data = resp.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False
    destination.write_bytes(data)
    return True


def rewrite_attr_urls(
    html_body: str,
    base_url: str,
    post_date: dt.datetime,
    media_root: Path,
    media_subdir_name: str,
    url_cache: dict[str, str],
    failures: list[str],
) -> str:
    def replace_single(url: str) -> str:
        normalized = normalize_image_url(url, base_url)
        if normalized in url_cache:
            return url_cache[normalized]
        if not is_image_url(normalized):
            return url

        rel_media = build_media_relpath(normalized, post_date)
        local_target = media_root / rel_media
        ok = download_binary(normalized, local_target)
        if not ok:
            failures.append(normalized)
            return url

        local_url = f"/{media_subdir_name}/{rel_media.as_posix()}"
        url_cache[normalized] = local_url
        return local_url

    def attr_repl(match: re.Match[str]) -> str:
        prefix, old_url, suffix = match.groups()
        return f"{prefix}{replace_single(old_url)}{suffix}"

    def srcset_repl(match: re.Match[str]) -> str:
        prefix, srcset_value, suffix = match.groups()
        items = [part.strip() for part in srcset_value.split(",") if part.strip()]
        rewritten: list[str] = []
        for item in items:
            parts = item.split()
            if not parts:
                continue
            old_url = parts[0]
            new_url = replace_single(old_url)
            tail = " ".join(parts[1:])
            rewritten.append((new_url + (" " + tail if tail else "")).strip())
        return f"{prefix}{', '.join(rewritten)}{suffix}"

    body = ATTR_URL_RE.sub(attr_repl, html_body)
    body = SRCSET_RE.sub(srcset_repl, body)
    return body


def rewrite_wp_latex_shortcodes(body_html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        return r"\(" + expr + r"\)"

    out = LATEX_SHORTCODE_RE.sub(repl, body_html)
    out = DISPLAY_PAR_RE.sub(lambda m: "<p>\\[" + m.group(1).strip() + "\\]</p>", out)
    out = MISMATCH_DISPLAY_RE.sub(lambda m: "\\[" + m.group(1).strip() + "\\]", out)
    out = MISMATCH_INLINE_RE.sub(lambda m: "\\(" + m.group(1).strip() + "\\)", out)

    def clean_math(expr: str) -> str:
        expr = expr.replace(r"\righatrrow", r"\rightarrow")
        expr = expr.replace(r"\C^\infty", r"C^\infty")
        expr = expr.replace("{rm{", r"{\rm{")
        expr = re.sub(r"\\log_\{10\}\^([0-9]+(?:\^\{[^}]+\})?(?:[+\-][0-9]+)?)", r"\\log_{10}(\1)", expr)
        expr = re.sub(r"\\log_\{10\}\s*10\^([A-Za-z0-9]+)(\s*[+\-]\s*1)", r"\\log_{10}(10^\1\2)", expr)
        expr = re.sub(r"\\log_\{10\}\s*10\^\{([^}]+)\}(\s*[+\-]\s*1)", r"\\log_{10}(10^{\1}\2)", expr)
        expr = re.sub(r"\\log_\{10\}\s*10\^([A-Za-z0-9]+)(?!\s*[+\-]\s*1)", r"\\log_{10}(10^\1)", expr)
        expr = re.sub(r"\\log_\{10\}\s*10\^\{([^}]+)\}(?!\s*[+\-]\s*1)", r"\\log_{10}(10^{\1})", expr)
        expr = re.sub(r"\[\s*(\\log[^\]]+)\s*\]", r"\\lceil \1 \\rceil", expr)
        expr = re.sub(r"\[\s*([xnk])\s*\]", r"\\lceil \1 \\rceil", expr)
        expr = re.sub(r"\[\s*([-+]?\d+(?:\.\d+)?)\s*\]", r"\\lceil \1 \\rceil", expr)
        return expr

    def segment_repl(match: re.Match[str]) -> str:
        full = match.group(1)
        inner = match.group(2) if match.group(2) is not None else match.group(3)
        if full.startswith(r"\("):
            return r"\(" + clean_math(inner) + r"\)"
        return r"\[" + clean_math(inner) + r"\]"

    out = MATH_SEGMENT_RE.sub(segment_repl, out)
    return out


def write_hugo_html(
    file_path: Path,
    title: str,
    slug: str,
    published_at: dt.datetime,
    categories: list[str],
    tags: list[str],
    body_html: str,
) -> None:
    url_path = f"/{published_at.year:04d}/{published_at.month:02d}/{published_at.day:02d}/{slug}/"
    front_matter_lines = [
        "---",
        f"title: {yaml_quote(title)}",
        f"slug: {yaml_quote(slug)}",
        f"date: {published_at.strftime('%Y-%m-%dT%H:%M:%S')}",
        f"url: {yaml_quote(url_path)}",
    ]
    if categories:
        front_matter_lines.append("categories: [" + ", ".join(yaml_quote(x) for x in categories) + "]")
    if tags:
        front_matter_lines.append("tags: [" + ", ".join(yaml_quote(x) for x in tags) + "]")
    front_matter_lines.extend(["---", ""])

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join(front_matter_lines) + body_html, encoding="utf-8")


def main() -> int:
    args = parse_args()
    xml_path = Path(args.xml_file).resolve()
    site_root = Path(args.site_root).resolve()
    content_root = (site_root / args.content_subdir).resolve()
    media_subdir_name = Path(args.media_subdir).as_posix().strip("/")
    media_root = (site_root / "static" / media_subdir_name).resolve()

    if not xml_path.exists():
        print(f"Missing XML file: {xml_path}", file=sys.stderr)
        return 1

    tree = ET.parse(xml_path)
    root = tree.getroot()
    channel = root.find("channel")
    if channel is None:
        print("Invalid WXR: missing <channel>", file=sys.stderr)
        return 1

    base_url = safe_text(channel.find("link")) or "https://example.com/"
    items = channel.findall("item")

    written = 0
    skipped = 0
    failed_images: list[str] = []
    url_cache: dict[str, str] = {}

    for item in items:
        post_type = safe_text(item.find("wp:post_type", WP_NS))
        status = safe_text(item.find("wp:status", WP_NS))
        if post_type not in {"post", "page"} or status != "publish":
            skipped += 1
            continue

        title = html.unescape(safe_text(item.find("title")))
        post_id = safe_text(item.find("wp:post_id", WP_NS))
        raw_slug = safe_text(item.find("wp:post_name", WP_NS))
        slug = ensure_slug(raw_slug, title, post_id)

        raw_date = safe_text(item.find("wp:post_date", WP_NS))
        try:
            published_at = parse_date(raw_date)
        except ValueError:
            skipped += 1
            continue

        body_html = (item.find("content:encoded", WP_NS).text or "")
        categories: list[str] = []
        tags: list[str] = []
        for cat in item.findall("category"):
            domain = (cat.attrib.get("domain") or "").strip()
            label = html.unescape((cat.text or "").strip())
            if not label:
                continue
            if domain == "category":
                categories.append(label)
            elif domain == "post_tag":
                tags.append(label)

        rewritten_body = rewrite_attr_urls(
            html_body=body_html,
            base_url=base_url,
            post_date=published_at,
            media_root=media_root,
            media_subdir_name=media_subdir_name,
            url_cache=url_cache,
            failures=failed_images,
        )
        rewritten_body = rewrite_wp_latex_shortcodes(rewritten_body)

        rel_name = f"{published_at.strftime('%Y-%m-%d')}-{slug}.html"
        target_file = content_root / post_type / rel_name
        if not args.dry_run:
            write_hugo_html(
                file_path=target_file,
                title=title,
                slug=slug,
                published_at=published_at,
                categories=categories,
                tags=tags,
                body_html=rewritten_body,
            )
        written += 1

    print(f"Imported entries: {written}")
    print(f"Skipped entries: {skipped}")
    if failed_images:
        unique_failures = sorted(set(failed_images))
        print(f"Image download failures: {len(unique_failures)}")
        for url in unique_failures[:20]:
            print(f"- {url}")
        if len(unique_failures) > 20:
            print(f"... and {len(unique_failures) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
