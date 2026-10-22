"""Loads and caches the business Markdown knowledge base.

Deliberately isolated behind a small interface (`load` / `reload`) so it can
later be swapped for a database-backed source, an OpenAI vector store, an
admin-uploaded file, or a full retrieval-augmented-generation pipeline
without touching any caller.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class KnowledgeBaseError(Exception):
    pass


@dataclass(frozen=True)
class KnowledgeBase:
    content: str
    content_hash: str
    char_count: int


class KnowledgeService:
    def __init__(self, file_path: str | Path, max_characters: int) -> None:
        self._file_path = Path(file_path)
        self._max_characters = max_characters
        self._cache: KnowledgeBase | None = None

    def load(self, *, force: bool = False) -> KnowledgeBase:
        """Return the cached knowledge base, loading it on first call.

        Cache is per function-instance only (Vercel instances are stateless
        and short-lived); a cold start always re-reads and re-validates the
        file from disk.
        """
        if self._cache is not None and not force:
            return self._cache

        if not self._file_path.exists():
            raise KnowledgeBaseError(f"Knowledge base file not found: {self._file_path}")

        content = self._file_path.read_text(encoding="utf-8").strip()
        if not content:
            raise KnowledgeBaseError("Knowledge base file is empty")

        if len(content) > self._max_characters:
            raise KnowledgeBaseError(
                "Knowledge base file exceeds MAX_KNOWLEDGE_CHARACTERS "
                f"({len(content)} > {self._max_characters} characters). "
                "Split content and add retrieval (RAG) instead of sending the "
                "full file to the model."
            )

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        logger.info("knowledge_base_loaded hash=%s chars=%d", content_hash, len(content))

        self._cache = KnowledgeBase(content=content, content_hash=content_hash, char_count=len(content))
        return self._cache

    def reload(self) -> KnowledgeBase:
        return self.load(force=True)

    @property
    def is_loaded(self) -> bool:
        return self._cache is not None
