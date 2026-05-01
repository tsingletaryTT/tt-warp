import pytest
from pathlib import Path
from tt_mcp.knowledge.db import KnowledgeDB


@pytest.fixture
def db(tmp_path):
    # Yield instead of return so the connection is closed after each test,
    # preventing resource leaks and WAL/lock interference between tests.
    instance = KnowledgeDB(tmp_path / "knowledge.db")
    yield instance
    instance.close()


def test_index_and_search_basic(db):
    db.index_chunk(
        chunk_id="hw-detect-1",
        source="tt-vscode-toolkit",
        lesson_id="hardware-detection",
        title="Hardware Detection",
        content="Run tt-smi to detect your Tenstorrent device.",
        hardware_tags=["n150", "p300c"],
        status="validated",
    )
    results = db.search("detect tenstorrent device")
    assert len(results) >= 1
    assert results[0]["lesson_id"] == "hardware-detection"


def test_hardware_filter_excludes_wrong_hw(db):
    db.index_chunk("qb2-1", "tt-vscode-toolkit", "qb2-video", "QB2 Video",
                   "Generate video on QB2 hardware.",
                   hardware_tags=["galaxy"], status="validated")
    db.index_chunk("bh-1", "tt-vscode-toolkit", "bh-inference", "BH Inference",
                   "Run inference on Blackhole P300C.",
                   hardware_tags=["p300c"], status="validated")
    results = db.search("generate video", hardware="p300c")
    lesson_ids = [r["lesson_id"] for r in results]
    assert "bh-inference" in lesson_ids
    assert "qb2-video" not in lesson_ids


def test_prefers_validated_over_experimental(db):
    db.index_chunk("a", "tt-vscode-toolkit", "lesson-a", "Lesson A",
                   "inference on p300c", hardware_tags=["p300c"], status="validated")
    db.index_chunk("b", "tt-vscode-toolkit", "lesson-b", "Lesson B",
                   "inference on p300c experimental", hardware_tags=["p300c"], status="experimental")
    results = db.search("inference p300c", hardware="p300c")
    assert results[0]["status"] == "validated"


def test_sync_timestamp(db):
    assert db.last_sync_timestamp() is None
    db.set_sync_timestamp(1_700_000_000.0)
    assert db.last_sync_timestamp() == pytest.approx(1_700_000_000.0)


def test_reindex_removes_stale_fts_row(db):
    # Index a chunk with "original alpha content" first, then re-index the
    # same chunk_id with completely different content.  The stale FTS row
    # (containing "alpha") must be gone; only the new "beta" content should
    # be searchable.  Without the DELETE-before-INSERT fix, FTS5 would keep
    # both rows and "alpha" would still return a hit.
    db.index_chunk("c1", "src", "lesson-x", "Title", "original alpha content",
                   hardware_tags=[], status="validated")
    db.index_chunk("c1", "src", "lesson-x", "Title", "updated beta content",
                   hardware_tags=[], status="validated")
    assert db.search("alpha") == [], "stale FTS row still present after re-index"
    assert len(db.search("beta")) == 1, "updated content not found after re-index"
