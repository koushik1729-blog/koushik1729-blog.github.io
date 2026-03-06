#!/usr/bin/env python3
"""Infer and add categories/tags for imported WordPress HTML posts/pages."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

FRONT_RE = re.compile(r"(?s)^---\n(.*?)\n---\n")
LIST_RE = re.compile(r'["\']([^"\']+)["\']')

CATEGORY_RULES = {
    "Algebraic geometry": [
        "algebraic geometry",
        "scheme",
        "spec(",
        "hartshorne",
        "variety",
    ],
    "Category theory": [
        "category theory",
        "yoneda",
        "functor",
        "natural transformation",
        "adjoint",
        "limit",
        "colimit",
    ],
    "Differential geometry": [
        "differential geometry",
        "connection",
        "curvature",
        "principal bundle",
        "kobayashi",
        "nomizu",
    ],
    "Homological algebra": [
        "snake lemma",
        "exact sequence",
        "kernel",
        "cokernel",
    ],
    "Stacks": [
        "stack",
        "fibered category",
        "descent",
        "grothendieck topology",
    ],
}

TAG_RULES = {
    "schemes": ["scheme", "spec("],
    "sheaves": ["sheaf", "stalk"],
    "yoneda-lemma": ["yoneda"],
    "stacks": ["stack", "descent"],
    "connections": ["connection", "covariant derivative"],
    "principal-bundles": ["principal bundle"],
    "hartshorne": ["hartshorne"],
    "kobayashi-nomizu": ["kobayashi", "nomizu"],
    "model-categories": ["model category"],
    "tensor-product": ["tensor product"],
}

FALLBACK_BY_SLUG = [
    ("Algebraic geometry", ["scheme", "sheaf", "spec", "hartshorne", "qcqs", "variet"]),
    ("Stacks", ["stack", "groupoid", "gerbe", "atlas", "descent"]),
    ("Differential geometry", ["connection", "bundle", "curvature", "covariant", "maurer", "rinehart"]),
    ("Lie groups", ["lie-group", "lie group"]),
    ("Lie groupoids", ["lie-groupoid", "lie groupoid"]),
    ("Homological algebra", ["snake-lemma", "exact-sequence", "kernel", "cokernel"]),
    ("Category theory", ["yoneda", "functor", "adjoint", "equalizer", "coequalizer", "epimorphism", "monomorphism", "additive"]),
    ("Linear algebra", ["tensor-product", "multilinear", "eigenvalue", "matrix"]),
    ("Analysis", ["limit", "limsup", "liminf", "infimum", "sequence"]),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="content/wp-import", help="Imported WordPress content root")
    return parser.parse_args()


def read_frontmatter(raw: str) -> tuple[str, str]:
    m = FRONT_RE.search(raw)
    if not m:
        return "", raw
    return m.group(1), raw[m.end() :]


def list_from_frontmatter(front: str, key: str) -> list[str]:
    m = re.search(rf"(?m)^{re.escape(key)}:\s*\[(.*?)\]\s*$", front)
    if not m:
        return []
    return [x.strip() for x in LIST_RE.findall(m.group(1)) if x.strip()]


def scalar_from_frontmatter(front: str, key: str) -> str:
    m = re.search(rf'(?m)^{re.escape(key)}:\s*"?(.*?)"?\s*$', front)
    if not m:
        return ""
    return m.group(1).strip()


def infer_terms(text: str, rules: dict[str, list[str]]) -> list[str]:
    low = text.lower()
    found: list[str] = []
    for term, needles in rules.items():
        if any(n in low for n in needles):
            found.append(term)
    return found


def norm_term(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def merge_terms(existing: list[str], inferred: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in existing + inferred:
        key = norm_term(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def upsert_list(front: str, key: str, values: list[str]) -> str:
    serialized = ", ".join(f'"{v}"' for v in values)
    line = f"{key}: [{serialized}]"
    if re.search(rf"(?m)^{re.escape(key)}:\s*\[.*\]\s*$", front):
        return re.sub(rf"(?m)^{re.escape(key)}:\s*\[.*\]\s*$", line, front)
    return front.rstrip() + "\n" + line + "\n"


def process_file(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    front, body = read_frontmatter(raw)
    if not front:
        return False

    existing_categories = list_from_frontmatter(front, "categories")
    existing_tags = list_from_frontmatter(front, "tags")
    slug = scalar_from_frontmatter(front, "slug")
    title = scalar_from_frontmatter(front, "title")

    inferred_categories = infer_terms(body, CATEGORY_RULES)
    inferred_tags = infer_terms(body, TAG_RULES)
    basis = (slug + " " + title + " " + body).lower()
    for fallback_cat, needles in FALLBACK_BY_SLUG:
        if any(n in basis for n in needles):
            inferred_categories.append(fallback_cat)
            break

    merged_categories = merge_terms(existing_categories, inferred_categories)
    merged_tags = merge_terms(existing_tags, inferred_tags)
    if len(merged_categories) > 1:
        merged_categories = [c for c in merged_categories if norm_term(c) != "uncategorized"]
    if not merged_categories:
        merged_categories = ["General"]

    new_front = front
    if merged_categories:
        new_front = upsert_list(new_front, "categories", merged_categories)
    if merged_tags:
        new_front = upsert_list(new_front, "tags", merged_tags)

    if new_front == front:
        return False

    path.write_text(f"---\n{new_front.rstrip()}\n---\n{body}", encoding="utf-8")
    return True


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    changed = 0
    for p in root.rglob("*.html"):
        if process_file(p):
            changed += 1
    print(f"Updated taxonomy in {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
