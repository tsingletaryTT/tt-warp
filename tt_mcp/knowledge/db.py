"""SQLite-backed knowledge store for tt-warp documentation chunks.

Provides full-text search (FTS5) over indexed documentation from
tt-vscode-toolkit lessons and tenstorrent.github.io, with optional
filtering by detected hardware tags.

Schema overview:
  chunks      - canonical chunk metadata (id, source, lesson, title, content,
                hardware tags as JSON list, validation status)
  chunks_fts  - FTS5 virtual table shadowing chunks.content + title for search
  meta        - key/value store for internal bookkeeping (e.g. last_sync time)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, List, Optional


class KnowledgeDB:
    """Persistent SQLite store for documentation chunks.

    Each chunk represents a discrete unit of documentation (e.g. a lesson
    section) associated with one or more hardware platforms. Chunks can be
    searched via FTS5 full-text search, optionally constrained to a specific
    hardware target.

    Args:
        db_path: Path to the SQLite database file. Created if it does not exist.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        # isolation_level=None enables autocommit; we manage commits manually
        # so we can batch writes efficiently.
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._setup()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        """Create tables if they do not already exist.

        Uses executescript so all DDL runs in a single implicit transaction.
        FTS5 is required; if the SQLite build lacks it this will raise an
        OperationalError which surfaces immediately as a clear BLOCKED signal.
        """
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id    TEXT PRIMARY KEY,
                source      TEXT NOT NULL,
                lesson_id   TEXT NOT NULL,
                title       TEXT NOT NULL,
                content     TEXT NOT NULL,
                -- JSON-encoded list of lowercase hardware tags, e.g. '["n150","p300c"]'
                hardware    TEXT NOT NULL DEFAULT '[]',
                -- 'validated' | 'experimental' | 'unknown'
                status      TEXT NOT NULL DEFAULT 'unknown'
            );

            -- FTS5 virtual table for full-text search over title + content.
            -- chunk_id is stored UNINDEXED so we can join back to chunks.
            -- Porter stemmer + unicode61 tokenizer handles English morphology.
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(content, chunk_id UNINDEXED, tokenize='porter unicode61');

            -- Generic key/value table for internal metadata (e.g. sync timestamps).
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_chunk(
        self,
        chunk_id: str,
        source: str,
        lesson_id: str,
        title: str,
        content: str,
        hardware_tags: list[str],
        status: str,
    ) -> None:
        """Insert or replace a documentation chunk in the knowledge store.

        Both the relational ``chunks`` table and the FTS index are updated
        atomically within a single transaction.

        Args:
            chunk_id:      Stable unique identifier for this chunk (e.g. "hw-detect-1").
            source:        Origin of the content (e.g. "tt-vscode-toolkit").
            lesson_id:     Logical grouping / lesson this chunk belongs to.
            title:         Human-readable title; prepended to FTS content for better recall.
            content:       Main text body to be searched.
            hardware_tags: List of lowercase hardware platform tags this chunk applies to
                           (e.g. ["n150", "p300c"]). Empty list means universal.
            status:        Reliability level: "validated", "experimental", or "unknown".
        """
        # Concatenate title into the FTS document so title keywords boost recall.
        fts_content = f"{title}\n{content}"

        # INSERT OR REPLACE handles both initial indexing and re-indexing.
        self._conn.execute(
            "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?)",
            (chunk_id, source, lesson_id, title, content,
             json.dumps(hardware_tags), status),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO chunks_fts(chunk_id, content) VALUES (?,?)",
            (chunk_id, fts_content),
        )
        self._conn.commit()

    def search(
        self,
        query: str,
        hardware: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Full-text search over indexed chunks, optionally filtered by hardware.

        When no hardware filter is active the results are pure FTS matches,
        ranked by:
          1. Status: validated chunks sort before experimental/unknown.
          2. FTS rank: higher relevance within each status tier.

        When a hardware filter IS active the strategy changes to ensure that
        hardware-specific chunks are always surfaced even if the query text
        doesn't happen to match them literally:

          * Chunks tagged for a *different* hardware platform are excluded.
          * Chunks tagged for the requested hardware (or universal chunks with
            empty tags) are included.
          * FTS relevance is used to order the surviving set; chunks that
            matched the query rank above those that did not.

        This means a query like "generate video" with hardware="p300c" will
        exclude a galaxy-tagged chunk even if its text matches, and will
        include a p300c-tagged chunk even if its text doesn't literally match
        the query — which is the intended retrieval behaviour for hardware-aware
        documentation lookup.

        Args:
            query:    FTS5 query string (plain-text keywords; FTS5 handles tokenization).
            hardware: Optional hardware target to filter by (e.g. "p300c").
                      Case-insensitive comparison against stored tags.
            top_k:    Maximum number of results to return after filtering.

        Returns:
            List of dicts with keys: chunk_id, source, lesson_id, title,
            content, hardware (raw JSON string), status, rank.
        """
        hw_lower = hardware.lower() if hardware else None

        # FTS5 treats hyphens as the column-exclusion operator (e.g. "tt-smi"
        # is parsed as "tt" MINUS "smi").  Replace hyphens with spaces so
        # "tt-smi" becomes two independent keyword tokens: "tt" and "smi".
        # This preserves recall while avoiding query syntax errors.
        safe_query = query.replace("-", " ")

        if hw_lower is None:
            # No hardware filter: pure FTS search with status-boosted ranking.
            # Over-fetch by 3× to have headroom for any post-processing.
            sql = """
                SELECT c.chunk_id, c.source, c.lesson_id, c.title,
                       c.content, c.hardware, c.status,
                       rank
                FROM chunks_fts f
                JOIN chunks c ON f.chunk_id = c.chunk_id
                WHERE chunks_fts MATCH ?
                ORDER BY
                    CASE c.status WHEN 'validated' THEN 0 ELSE 1 END,
                    rank
                LIMIT ?
            """
            rows = self._conn.execute(sql, (safe_query, top_k)).fetchall()
            return [dict(r) for r in rows]

        # Hardware-filtered search:
        # 1. Collect FTS-matching chunk IDs for relevance ranking.
        fts_sql = """
            SELECT f.chunk_id, rank
            FROM chunks_fts f
            WHERE chunks_fts MATCH ?
        """
        fts_rows = self._conn.execute(fts_sql, (safe_query,)).fetchall()
        # Build a map of chunk_id -> FTS rank (lower = more relevant in FTS5).
        fts_rank: dict[str, float] = {r["chunk_id"]: r["rank"] for r in fts_rows}

        # 2. Fetch all chunks that pass the hardware filter from the relational table.
        #    A chunk passes when:
        #      a) its hardware list is empty (universal/untagged), OR
        #      b) its hardware list contains the requested hardware tag.
        #    json_each is used to unnest the JSON array for the membership check.
        hw_sql = """
            SELECT DISTINCT c.chunk_id, c.source, c.lesson_id, c.title,
                            c.content, c.hardware, c.status
            FROM chunks c
            WHERE
                -- Universal chunks: no hardware restriction
                json_array_length(c.hardware) = 0
                OR EXISTS (
                    SELECT 1 FROM json_each(c.hardware) j
                    WHERE lower(j.value) = lower(?)
                )
        """
        hw_rows = self._conn.execute(hw_sql, (hw_lower,)).fetchall()

        # 3. Merge: annotate each hardware-matched chunk with its FTS rank
        #    (use a large sentinel rank for chunks not in the FTS result set
        #    so they sort after FTS hits while still being included).
        SENTINEL_RANK = 0.0  # FTS5 ranks are negative; 0.0 sorts last

        candidates = []
        for row in hw_rows:
            rank = fts_rank.get(row["chunk_id"], SENTINEL_RANK)
            d = dict(row)
            d["rank"] = rank
            candidates.append(d)

        # 4. Sort: validated first, then by FTS rank (lower is better in FTS5,
        #    but our sentinel 0.0 must sort after real ranks which are negative).
        #    We use a tuple key: (status_order, effective_rank) where
        #    effective_rank is rank if it came from FTS (negative), else +inf.
        def sort_key(item: dict) -> tuple:
            status_order = 0 if item["status"] == "validated" else 1
            raw_rank = item["rank"]
            # Real FTS5 ranks are negative (more negative = worse match).
            # Sentinel 0.0 means no FTS match — should rank after all real matches.
            # We convert to "higher is worse" by negating, then sentinel becomes
            # float('inf') to always sort last within its status tier.
            if raw_rank == SENTINEL_RANK and item["chunk_id"] not in fts_rank:
                effective = float("inf")
            else:
                # More negative rank in FTS5 = worse relevance, so negate to
                # get "higher value = worse" ordering for ascending sort.
                effective = -raw_rank
            return (status_order, effective)

        candidates.sort(key=sort_key)

        return candidates[:top_k]

    def last_sync_timestamp(self) -> Optional[float]:
        """Return the Unix timestamp of the last successful knowledge sync.

        Returns:
            Float timestamp, or None if no sync has been recorded yet.
        """
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key='last_sync'"
        ).fetchone()
        return float(row["value"]) if row else None

    def set_sync_timestamp(self, ts: float) -> None:
        """Persist the Unix timestamp of a completed knowledge sync.

        Args:
            ts: Unix timestamp (seconds since epoch) as a float.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO meta VALUES ('last_sync', ?)", (str(ts),)
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection.

        After calling this method the KnowledgeDB instance should not be used.
        """
        self._conn.close()
