#!/usr/bin/env python3
"""Normalize WordPress $latex ...$ shortcodes into MathJax delimiters."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

FRONT_RE = re.compile(r"(?s)^---\n.*?\n---\n")
LATEX_SHORTCODE_RE = re.compile(r"\$latex\s+(.+?)\$", re.DOTALL)
DISPLAY_PAR_RE = re.compile(r"(?s)<p>\s*\\\((.+?)\\\)\s*</p>")
MISMATCH_DISPLAY_RE = re.compile(r"\\\[([^<]*?)\\\)")
MISMATCH_INLINE_RE = re.compile(r"\\\(([^<]*?)\\\]")
MATH_SEGMENT_RE = re.compile(r"(\\\((.+?)\\\)|\\\[(.+?)\\\])", re.DOTALL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="content/wp-import", help="Root directory for imported WP files")
    return parser.parse_args()


def transform_body(body: str) -> str:
    def repl(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        return r"\(" + expr + r"\)"

    out = LATEX_SHORTCODE_RE.sub(repl, body)
    out = DISPLAY_PAR_RE.sub(lambda m: "<p>\\[" + m.group(1).strip() + "\\]</p>", out)
    out = MISMATCH_DISPLAY_RE.sub(lambda m: "\\[" + m.group(1).strip() + "\\]", out)
    out = MISMATCH_INLINE_RE.sub(lambda m: "\\(" + m.group(1).strip() + "\\)", out)

    def clean_math(expr: str) -> str:
        expr = expr.replace(r"\righatrrow", r"\rightarrow")
        expr = expr.replace(r"\C^\infty", r"C^\infty")
        expr = expr.replace("{rm{", r"{\rm{")
        # Fix malformed logs produced by source conversion.
        expr = re.sub(r"\\log_\{10\}\^([0-9]+(?:\^\{[^}]+\})?(?:[+\-][0-9]+)?)", r"\\log_{10}(\1)", expr)
        # \log_{10}10^k+1 -> \log_{10}(10^k+1)
        expr = re.sub(r"\\log_\{10\}\s*10\^([A-Za-z0-9]+)(\s*[+\-]\s*1)", r"\\log_{10}(10^\1\2)", expr)
        # \log_{10}10^{k}+1 -> \log_{10}(10^{k}+1)
        expr = re.sub(r"\\log_\{10\}\s*10\^\{([^}]+)\}(\s*[+\-]\s*1)", r"\\log_{10}(10^{\1}\2)", expr)
        # \log_{10}10^k -> \log_{10}(10^k)
        expr = re.sub(r"\\log_\{10\}\s*10\^([A-Za-z0-9]+)(?!\s*[+\-]\s*1)", r"\\log_{10}(10^\1)", expr)
        # \log_{10}10^{k} -> \log_{10}(10^{k})
        expr = re.sub(r"\\log_\{10\}\s*10\^\{([^}]+)\}(?!\s*[+\-]\s*1)", r"\\log_{10}(10^{\1})", expr)
        # Normalize WordPress-style ceiling notation for cleaner MathJax rendering.
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


def process_file(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    m = FRONT_RE.match(raw)
    if not m:
        return False
    front = raw[: m.end()]
    body = raw[m.end() :]
    new_body = transform_body(body)
    if new_body == body:
        return False
    path.write_text(front + new_body, encoding="utf-8")
    return True


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    changed = 0
    for file in root.rglob("*.html"):
        if process_file(file):
            changed += 1
    print(f"Normalized LaTeX shortcodes in {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
