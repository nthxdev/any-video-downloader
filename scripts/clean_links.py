#!/usr/bin/env python3
"""Extract unique HTTP(S) URLs from a text-like file."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

URL_RE = re.compile(r"https?://[^\s<>{}\[\]\"']+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?)]}"


def normalize_url(candidate: str) -> str | None:
    """Return a normalized valid HTTP(S) URL, or None."""
    value = candidate.strip()
    while value and value[-1] in TRAILING_PUNCTUATION:
        if value[-1] == ")" and value.count("(") >= value.count(")"):
            break
        value = value[:-1]
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return None
        if any(char.isspace() for char in parsed.netloc):
            return None
        port = parsed.port
        if port is not None and not 0 < port < 65536:
            return None
    except (ValueError, UnicodeError):
        return None
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


def extract_links(text: str) -> tuple[list[str], int]:
    """Extract valid unique links, preserving first-seen order."""
    links: list[str] = []
    seen: set[str] = set()
    duplicates = 0
    for match in URL_RE.finditer(text):
        url = normalize_url(match.group(0))
        if url is None:
            continue
        if url in seen:
            duplicates += 1
            continue
        seen.add(url)
        links.append(url)
    return links, duplicates


def clean_file(path: Path) -> tuple[int, int]:
    """Back up and clean *path*, returning (retained, duplicate_count)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Could not read {path}: {exc}") from exc

    backup = path.with_name(f"{path.stem}.original{path.suffix}")
    if not backup.exists():
        try:
            shutil.copy2(path, backup)
        except OSError as exc:
            raise RuntimeError(f"Could not create backup {backup}: {exc}") from exc

    links, duplicates = extract_links(text)
    try:
        path.write_text("".join(f"{url}\n" for url in links), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not write {path}: {exc}") from exc
    return len(links), duplicates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", type=Path)
    args = parser.parse_args(argv)
    try:
        count, duplicates = clean_file(args.input_file)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Links found: {count}")
    print(f"Duplicates removed: {duplicates}")
    print(f"Output file: {args.input_file.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
