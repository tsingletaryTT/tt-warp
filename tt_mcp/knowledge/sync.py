"""Sync lesson content from tt-vscode-toolkit into the local SQLite knowledge store.

This module fetches the lesson registry JSON from the tt-vscode-toolkit GitHub
repository, then downloads each lesson's Markdown file, strips YAML frontmatter,
splits the body into searchable chunks, and indexes them via KnowledgeDB.

Typical call site (CLI):
    from tt_mcp.knowledge.db import KnowledgeDB
    from tt_mcp.knowledge.sync import sync_lessons

    db = KnowledgeDB(path)
    count = sync_lessons(db)
    print(f"Synced {count} lessons")

Network errors during registry fetch are treated as fatal (returns 0 immediately).
Network errors on individual lesson fetches are logged and skipped so that a single
bad URL does not abort the entire sync run.
"""

from __future__ import annotations

import re
import time
from typing import Optional

import requests
import yaml

from tt_mcp.knowledge.db import KnowledgeDB

# ---------------------------------------------------------------------------
# Remote URL constants
# ---------------------------------------------------------------------------

# The lesson registry is a JSON file listing all available lessons with metadata.
_REGISTRY_URL = (
    "https://raw.githubusercontent.com/tenstorrent/tt-vscode-toolkit"
    "/main/content/lesson-registry.json"
)

# Each lesson's Markdown file lives under content/lessons/{lesson_id}.md
_LESSON_BASE_URL = (
    "https://raw.githubusercontent.com/tenstorrent/tt-vscode-toolkit"
    "/main/content/lessons/{lesson_id}.md"
)

# Default HTTP request timeout in seconds.
_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Markdown utilities
# ---------------------------------------------------------------------------

def _strip_frontmatter(md: str) -> tuple[dict, str]:
    """Split YAML frontmatter from a Markdown document body.

    Frontmatter is expected to be a YAML block delimited by ``---`` lines at
    the very start of the file.  If the document has no frontmatter the full
    text is returned as the body with an empty metadata dict.

    Args:
        md: Raw Markdown string (may or may not have ``---`` frontmatter).

    Returns:
        A ``(meta, body)`` tuple where ``meta`` is a dict of parsed YAML keys
        (may be empty) and ``body`` is the Markdown text without the frontmatter
        block.
    """
    if md.startswith("---"):
        # Split on the first two occurrences of "---"; parts[1] = YAML, parts[2] = body
        parts = md.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                # Malformed frontmatter — treat the whole document as body.
                meta = {}
            return meta, parts[2].strip()
    return {}, md


def _chunk_markdown(text: str, max_chars: int = 2000) -> list[str]:
    """Split Markdown text into indexable chunks.

    Strategy:
    1. Split on ATX heading boundaries (``#``, ``##``, or ``###``) so each
       top-level section becomes its own chunk — this preserves semantic unity.
    2. Any section that exceeds ``max_chars`` is further split by character
       count with no overlap (simple, deterministic, avoids embedding-length
       issues).

    Blank chunks are filtered out before returning.

    Args:
        text:      Markdown body (no frontmatter) to split.
        max_chars: Soft size cap per chunk in characters (default 2000).

    Returns:
        List of non-empty stripped chunk strings.
    """
    # Split on lines that start a new heading (look-ahead keeps the heading line
    # in the following section rather than a standalone empty prefix).
    sections = re.split(r'\n(?=#{1,3} )', text)
    chunks: list[str] = []
    for section in sections:
        if len(section) <= max_chars:
            chunks.append(section.strip())
        else:
            # Section is too large — slice it into fixed-size pieces.
            for i in range(0, len(section), max_chars):
                chunks.append(section[i:i + max_chars].strip())
    # Drop empty strings that result from leading/trailing whitespace or empty sections.
    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Public sync entry point
# ---------------------------------------------------------------------------

def sync_lessons(db: KnowledgeDB, timeout: int = _TIMEOUT) -> int:
    """Fetch lessons from tt-vscode-toolkit and index them into the knowledge store.

    Workflow:
    1. Download the lesson registry JSON.  If this fails (network error, non-200
       status, JSON parse error) the function returns 0 immediately so callers can
       detect a clean no-op vs. partial results.
    2. For each lesson entry in the registry, download the corresponding Markdown
       file, parse frontmatter, chunk the body, and call ``db.index_chunk`` for
       each chunk.  Lessons whose fetch fails are silently skipped.
    3. Persist the current UTC timestamp via ``db.set_sync_timestamp`` to record
       that a sync run completed successfully (even if some individual lessons were
       skipped).

    Args:
        db:      An open ``KnowledgeDB`` instance to write into.
        timeout: HTTP request timeout in seconds (passed through to ``requests``).

    Returns:
        The number of lessons successfully indexed (0 on network failure or an
        empty registry).
    """
    # ------------------------------------------------------------------
    # Step 1: Download registry
    # ------------------------------------------------------------------
    try:
        r = requests.get(_REGISTRY_URL, timeout=timeout)
        r.raise_for_status()
        registry = r.json()
    except Exception:
        # Network error, HTTP error, or JSON parse failure — return 0 cleanly.
        return 0

    synced = 0

    # ------------------------------------------------------------------
    # Step 2: Download and index each lesson
    # ------------------------------------------------------------------
    for lesson in registry.get("lessons", []):
        lesson_id = lesson.get("id", "")
        if not lesson_id:
            # Registry entry is malformed — skip silently.
            continue

        url = _LESSON_BASE_URL.format(lesson_id=lesson_id)
        try:
            lr = requests.get(url, timeout=timeout)
            lr.raise_for_status()
            # Strip frontmatter; we only need the body for FTS indexing.
            _, body = _strip_frontmatter(lr.text)
        except Exception:
            # Network error or HTTP error on individual lesson — skip and continue.
            continue

        # Extract metadata fields from the registry entry (not the frontmatter,
        # which may be absent or incomplete).
        hw_tags = lesson.get("supportedHardware", [])
        status = lesson.get("status", "unknown")
        title = lesson.get("title", lesson_id)

        chunks = _chunk_markdown(body)

        for i, chunk in enumerate(chunks):
            db.index_chunk(
                chunk_id=f"{lesson_id}-{i}",
                source="tt-vscode-toolkit",
                lesson_id=lesson_id,
                title=title,
                content=chunk,
                hardware_tags=hw_tags,
                status=status,
            )

        synced += 1

    # ------------------------------------------------------------------
    # Step 3: Record sync timestamp so callers can check staleness
    # ------------------------------------------------------------------
    db.set_sync_timestamp(time.time())

    return synced
