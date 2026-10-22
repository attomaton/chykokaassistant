from __future__ import annotations

import pytest

from services.knowledge_service import KnowledgeBaseError, KnowledgeService


def test_loads_and_caches_existing_file(tmp_path):
    file_path = tmp_path / "business.md"
    file_path.write_text("# My Business\nWe sell widgets.", encoding="utf-8")

    service = KnowledgeService(file_path, max_characters=1000)
    kb = service.load()

    assert kb.char_count == len(file_path.read_text(encoding="utf-8").strip())
    assert len(kb.content_hash) == 16
    assert service.is_loaded is True

    # Cached: mutating the file should not change the cached content until reload().
    file_path.write_text("# Changed", encoding="utf-8")
    cached = service.load()
    assert cached.content_hash == kb.content_hash

    reloaded = service.reload()
    assert reloaded.content_hash != kb.content_hash


def test_missing_file_raises(tmp_path):
    missing_path = tmp_path / "does-not-exist.md"
    service = KnowledgeService(missing_path, max_characters=1000)
    with pytest.raises(KnowledgeBaseError):
        service.load()


def test_empty_file_raises(tmp_path):
    file_path = tmp_path / "empty.md"
    file_path.write_text("   \n  ", encoding="utf-8")
    service = KnowledgeService(file_path, max_characters=1000)
    with pytest.raises(KnowledgeBaseError):
        service.load()


def test_oversized_file_raises(tmp_path):
    file_path = tmp_path / "big.md"
    file_path.write_text("x" * 200, encoding="utf-8")
    service = KnowledgeService(file_path, max_characters=100)
    with pytest.raises(KnowledgeBaseError):
        service.load()
