"""Pattern Memory — Storage Layer (SQLite + ChromaDB)

Supports two modes:
  - Full mode: SQLite + ChromaDB (default)
  - SQLite-only mode: When ChromaDB is unavailable (graceful degradation)
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from common.logging import get_logger

logger = get_logger("pattern-memory.storage")

# Try to import chromadb — optional dependency
try:
    import chromadb
    from chromadb.errors import NotFoundError
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False
    logger.warning("chromadb not installed — running in SQLite-only mode")

from models import Pattern, Correction


class Storage:
    """Dual storage: SQLite for metadata, ChromaDB for vector search.

    If ChromaDB is unavailable, falls back to SQLite-only mode.
    Semantic search will return empty results in SQLite-only mode.
    """

    def __init__(
        self,
        db_path: str = "~/.pattern-memory/patterns.db",
        chroma_url: str = "http://localhost:8000",
        collection_name: str = "pattern_memory",
    ):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # SQLite for structured data
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_db()

        # ChromaDB for vector search (optional)
        self._chroma_available = False
        self.chroma = None
        self.collection = None
        self._collection_name = collection_name

        if HAS_CHROMADB:
            try:
                # Parse chroma_url to extract host and port
                from urllib.parse import urlparse
                parsed = urlparse(chroma_url)
                host = parsed.hostname or "127.0.0.1"
                port = parsed.port or 8000
                self.chroma = chromadb.HttpClient(host=host, port=port)
                self._chroma_available = True  # Set BEFORE _init_collection
                self.collection = self._init_collection()
            except Exception as e:
                logger.warning("ChromaDB unavailable: %s — SQLite-only mode", e)
        else:
            logger.info("Running in SQLite-only mode (no semantic search)")

    def _init_collection(self):
        """Initialize or re-initialize the ChromaDB collection handle."""
        if not self._chroma_available or self.chroma is None:
            return None
        return self.chroma.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def _ensure_collection(self):
        """Re-initialize collection handle if it's stale."""
        if not self._chroma_available:
            return False
        try:
            self.collection.count()
        except (ValueError, NotFoundError) as e:
            error_msg = str(e)
            if "does not exist" in error_msg or "Collection" in error_msg:
                self.collection = self._init_collection()
                return True
            raise
        return False

    def _chroma_op(self, method_name: str, *args, **kwargs):
        """Execute a ChromaDB operation with self-healing on stale handles."""
        if not self._chroma_available or self.collection is None:
            return None
        operation = getattr(self.collection, method_name)
        try:
            return operation(*args, **kwargs)
        except (ValueError, NotFoundError) as e:
            error_msg = str(e).lower()
            if "does not exist" in error_msg and "collection" in error_msg:
                self._ensure_collection()
                operation = getattr(self.collection, method_name)
                return operation(*args, **kwargs)
            raise

    def _init_db(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS patterns (
                id TEXT PRIMARY KEY,
                trigger TEXT NOT NULL,
                action TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                confidence REAL DEFAULT 0.3,
                use_count INTEGER DEFAULT 0,
                created_at TEXT,
                last_used TEXT,
                last_confirmed TEXT,
                applied_count INTEGER DEFAULT 0,
                last_applied TEXT,
                auto_confirmed INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS corrections (
                id TEXT PRIMARY KEY,
                original_behavior TEXT NOT NULL,
                corrected_behavior TEXT NOT NULL,
                context TEXT,
                category TEXT DEFAULT 'general',
                pattern_id TEXT,
                timestamp TEXT,
                FOREIGN KEY (pattern_id) REFERENCES patterns(id)
            );

            CREATE INDEX IF NOT EXISTS idx_patterns_category ON patterns(category);
            CREATE INDEX IF NOT EXISTS idx_patterns_confidence ON patterns(confidence DESC);
            CREATE INDEX IF NOT EXISTS idx_corrections_pattern ON corrections(pattern_id);
        """)
        self.conn.commit()

    # ── Pattern Operations ──────────────────────────────────────────────

    def store_pattern(self, pattern: Pattern) -> str:
        """Store pattern in both SQLite and ChromaDB."""
        # SQLite
        self.conn.execute(
            """INSERT OR REPLACE INTO patterns
               (id, trigger, action, category, confidence, use_count, created_at, last_used, last_confirmed, applied_count, last_applied, auto_confirmed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pattern.id, pattern.trigger, pattern.action, pattern.category,
                pattern.confidence, pattern.use_count,
                pattern.created_at.isoformat(),
                pattern.last_used.isoformat() if pattern.last_used else None,
                pattern.last_confirmed.isoformat() if pattern.last_confirmed else None,
                pattern.applied_count,
                pattern.last_applied.isoformat() if pattern.last_applied else None,
                1 if pattern.auto_confirmed else 0,
            ),
        )
        self.conn.commit()

        # ChromaDB
        if self._chroma_available:
            doc_text = f"{pattern.trigger} → {pattern.action}"
            self._chroma_op(
                "upsert",
                ids=[pattern.id],
                documents=[doc_text],
                metadatas=[{
                    "category": pattern.category,
                    "confidence": pattern.confidence,
                    "use_count": pattern.use_count,
                    "created_at": pattern.created_at.isoformat(),
                    "applied_count": pattern.applied_count,
                    "auto_confirmed": pattern.auto_confirmed,
                }],
            )

        return pattern.id

    def get_pattern(self, pattern_id: str) -> Optional[Pattern]:
        """Get a single pattern by ID."""
        row = self.conn.execute(
            "SELECT * FROM patterns WHERE id = ?", (pattern_id,)
        ).fetchone()
        if not row:
            return None
        return Pattern(
            id=row["id"], trigger=row["trigger"], action=row["action"],
            category=row["category"], confidence=row["confidence"],
            use_count=row["use_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_used=datetime.fromisoformat(row["last_used"]) if row["last_used"] else None,
            last_confirmed=datetime.fromisoformat(row["last_confirmed"]) if row["last_confirmed"] else None,
            applied_count=row["applied_count"] if row["applied_count"] else 0,
            last_applied=datetime.fromisoformat(row["last_applied"]) if row["last_applied"] else None,
            auto_confirmed=bool(row["auto_confirmed"]) if row["auto_confirmed"] else False,
        )

    def update_pattern(self, pattern: Pattern):
        """Update an existing pattern."""
        self.store_pattern(pattern)  # UPSERT handles it

    def delete_pattern(self, pattern_id: str):
        """Delete a pattern from both stores."""
        self.conn.execute("DELETE FROM patterns WHERE id = ?", (pattern_id,))
        self.conn.commit()
        if self._chroma_available:
            self._chroma_op("delete", ids=[pattern_id])

    def list_patterns(
        self,
        category: Optional[str] = None,
        min_confidence: float = 0.0,
        sort_by: str = "confidence",
        limit: int = 50,
    ) -> list[Pattern]:
        """List patterns with optional filtering."""
        query = "SELECT * FROM patterns WHERE confidence >= ?"
        params: list = [min_confidence]

        if category:
            query += " AND category = ?"
            params.append(category)

        sort_map = {
            "confidence": "confidence DESC",
            "recent": "created_at DESC",
            "usage": "use_count DESC",
        }
        query += f" ORDER BY {sort_map.get(sort_by, 'confidence DESC')}"
        query += " LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [
            Pattern(
                id=r["id"], trigger=r["trigger"], action=r["action"],
                category=r["category"], confidence=r["confidence"],
                use_count=r["use_count"],
                created_at=datetime.fromisoformat(r["created_at"]),
                last_used=datetime.fromisoformat(r["last_used"]) if r["last_used"] else None,
                last_confirmed=datetime.fromisoformat(r["last_confirmed"]) if r["last_confirmed"] else None,
                applied_count=r["applied_count"] if r["applied_count"] else 0,
                last_applied=datetime.fromisoformat(r["last_applied"]) if r["last_applied"] else None,
                auto_confirmed=bool(r["auto_confirmed"]) if r["auto_confirmed"] else False,
            )
            for r in rows
        ]

    def search_patterns(self, query: str, limit: int = 10) -> list[dict]:
        """Semantic search for patterns via ChromaDB.

        Returns empty list in SQLite-only mode.
        """
        if not self._chroma_available:
            logger.debug("Semantic search unavailable (SQLite-only mode)")
            return []

        try:
            actual_count = self.collection.count() or 1
        except (ValueError, NotFoundError):
            actual_count = limit

        results = self._chroma_op(
            "query",
            query_texts=[query],
            n_results=min(limit, actual_count),
        )
        matches = []
        if results and results["ids"] and results["ids"][0]:
            for i, pid in enumerate(results["ids"][0]):
                pattern = self.get_pattern(pid)
                if pattern:
                    matches.append({
                        "pattern": pattern.to_dict(),
                        "distance": results["distances"][0][i] if results["distances"] else None,
                    })
        return matches

    # ── Correction Operations ───────────────────────────────────────────

    def store_correction(self, correction: Correction) -> str:
        """Store a correction in SQLite."""
        self.conn.execute(
            """INSERT INTO corrections
               (id, original_behavior, corrected_behavior, context, category, pattern_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                correction.id, correction.original_behavior,
                correction.corrected_behavior, correction.context,
                correction.category, correction.pattern_id,
                correction.timestamp.isoformat(),
            ),
        )
        self.conn.commit()
        return correction.id

    def get_corrections_for_pattern(self, pattern_id: str) -> list[Correction]:
        """Get all corrections linked to a pattern."""
        rows = self.conn.execute(
            "SELECT * FROM corrections WHERE pattern_id = ? ORDER BY timestamp DESC",
            (pattern_id,),
        ).fetchall()
        return [
            Correction(
                id=r["id"],
                original_behavior=r["original_behavior"],
                corrected_behavior=r["corrected_behavior"],
                context=r["context"],
                category=r["category"],
                pattern_id=r["pattern_id"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
            )
            for r in rows
        ]

    def get_recent_corrections(self, limit: int = 10) -> list[Correction]:
        """Get most recent corrections."""
        rows = self.conn.execute(
            "SELECT * FROM corrections ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            Correction(
                id=r["id"],
                original_behavior=r["original_behavior"],
                corrected_behavior=r["corrected_behavior"],
                context=r["context"],
                category=r["category"],
                pattern_id=r["pattern_id"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
            )
            for r in rows
        ]

    def count_patterns(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]

    def count_corrections(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]

    def close(self):
        self.conn.close()
