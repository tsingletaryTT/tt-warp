import json
import pytest
import responses as rsps_lib
from pathlib import Path
from tt_mcp.knowledge.db import KnowledgeDB
from tt_mcp.knowledge.sync import sync_lessons

REGISTRY = {
    "lessons": [
        {
            "id": "hardware-detection",
            "title": "Hardware Detection",
            "category": "first-inference",
            "supportedHardware": ["n150", "p300c"],
            "status": "validated",
        }
    ]
}
LESSON_MD = "---\nid: hardware-detection\ntitle: Hardware Detection\n---\n\n# Hardware Detection\n\nRun tt-smi to check devices.\n"

REGISTRY_URL = "https://raw.githubusercontent.com/tenstorrent/tt-vscode-toolkit/main/content/lesson-registry.json"
LESSON_URL = "https://raw.githubusercontent.com/tenstorrent/tt-vscode-toolkit/main/content/lessons/hardware-detection.md"


@rsps_lib.activate
def test_sync_lessons_indexes_content(tmp_path):
    rsps_lib.add(rsps_lib.GET, REGISTRY_URL, json=REGISTRY, status=200)
    rsps_lib.add(rsps_lib.GET, LESSON_URL, body=LESSON_MD, status=200)

    db = KnowledgeDB(tmp_path / "knowledge.db")
    synced = sync_lessons(db)
    assert synced == 1
    results = db.search("tt-smi devices")
    assert len(results) >= 1
    assert results[0]["lesson_id"] == "hardware-detection"
    assert results[0]["status"] == "validated"
    assert db.last_sync_timestamp() is not None
    db.close()


@rsps_lib.activate
def test_sync_lessons_skips_on_network_error(tmp_path):
    rsps_lib.add(rsps_lib.GET, REGISTRY_URL,
                 body=Exception("connection refused"))
    db = KnowledgeDB(tmp_path / "knowledge.db")
    synced = sync_lessons(db)
    assert synced == 0
    db.close()
