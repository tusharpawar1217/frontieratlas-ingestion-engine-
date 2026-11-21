"""
SQLite storage layer for the pipeline.
Manages records, seen tracking, and raw payload storage.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiosqlite
from loguru import logger

from src.config import get_config, get_env_settings
from src.models import Record, EntityMappingEntry


class Storage:
    """
    SQLite-based storage for pipeline data.
    Designed to be swappable with PostgreSQL/Redis later.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize storage.
        
        Args:
            db_path: Path to SQLite database file
        """
        if db_path is None:
            env_settings = get_env_settings()
            db_path = env_settings.database_path
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection: Optional[aiosqlite.Connection] = None
        self._checkpoint_counter = 0
        self._checkpoint_interval = get_config().storage.checkpoint_interval
    
    async def connect(self) -> None:
        """Establish database connection and create tables."""
        self.connection = await aiosqlite.connect(str(self.db_path))
        # Enable WAL mode for better concurrency
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA synchronous=NORMAL")
        await self.connection.execute("PRAGMA cache_size=-64000")  # 64MB cache
        await self.create_tables()
        logger.info(f"Connected to database: {self.db_path}")
    
    async def close(self) -> None:
        """Close database connection."""
        if self.connection:
            await self.connection.close()
            self.connection = None
            logger.info("Database connection closed")
    
    async def create_tables(self) -> None:
        """Create all required tables."""
        
        # Records table (stores all ingested records)
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                content_json TEXT NOT NULL,
                content_hash TEXT,
                collected_at TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_record_type (record_type),
                INDEX idx_source_name (source_name),
                INDEX idx_content_hash (content_hash),
                INDEX idx_collected_at (collected_at)
            )
        """)
        
        # Seen URLs table
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS seen_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_url TEXT UNIQUE NOT NULL,
                content_hash TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                seen_count INTEGER DEFAULT 1,
                INDEX idx_canonical_url (canonical_url)
            )
        """)
        
        # Seen content table
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS seen_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_hash TEXT UNIQUE NOT NULL,
                source_url TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                INDEX idx_content_hash (content_hash)
            )
        """)
        
        # Entity mappings table
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS entity_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_name TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                match_method TEXT NOT NULL,
                score REAL,
                source_url TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                INDEX idx_raw_name (raw_name),
                INDEX idx_canonical_name (canonical_name)
            )
        """)
        
        # Raw payloads table (stores original fetched content)
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS raw_payloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                payload BLOB NOT NULL,
                fetched_at TEXT NOT NULL,
                status_code INTEGER,
                headers_json TEXT,
                INDEX idx_url (url),
                INDEX idx_content_hash (content_hash)
            )
        """)
        
        # Failed records table (for debugging)
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS failed_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                error_type TEXT NOT NULL,
                error_message TEXT,
                raw_data TEXT,
                failed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_source_name (source_name),
                INDEX idx_error_type (error_type)
            )
        """)
        
        await self.connection.commit()
        logger.debug("Database tables created/verified")
    
    async def save_record(self, record: Record) -> int:
        """
        Save a validated record to the database.
        
        Args:
            record: Validated record object
            
        Returns:
            Record ID
        """
        record_dict = record.model_dump(mode='json')
        content_json = json.dumps(record_dict)
        
        cursor = await self.connection.execute(
            """
            INSERT INTO records (record_type, source_name, source_url, content_json, 
                               content_hash, collected_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.recordType,
                record.source.name,
                record.source.url,
                content_json,
                record.meta.get("content_hash") if record.meta else None,
                record.collectedAt.isoformat(),
            )
        )
        
        record_id = cursor.lastrowid
        
        # Checkpoint periodically
        self._checkpoint_counter += 1
        if self._checkpoint_counter >= self._checkpoint_interval:
            await self.connection.commit()
            self._checkpoint_counter = 0
            logger.debug(f"Checkpoint: committed {self._checkpoint_interval} records")
        
        return record_id
    
    async def save_raw_payload(
        self,
        url: str,
        content_hash: str,
        payload: bytes,
        status_code: int,
        headers: dict[str, str]
    ) -> int:
        """
        Save raw HTTP response payload.
        
        Args:
            url: URL that was fetched
            content_hash: Content hash
            payload: Raw response body
            status_code: HTTP status code
            headers: Response headers
            
        Returns:
            Payload ID
        """
        cursor = await self.connection.execute(
            """
            INSERT INTO raw_payloads (url, content_hash, payload, fetched_at, 
                                     status_code, headers_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                content_hash,
                payload,
                datetime.utcnow().isoformat(),
                status_code,
                json.dumps(headers),
            )
        )
        
        return cursor.lastrowid
    
    async def is_url_seen(self, canonical_url: str) -> bool:
        """Check if a URL has been seen."""
        cursor = await self.connection.execute(
            "SELECT 1 FROM seen_urls WHERE canonical_url = ? LIMIT 1",
            (canonical_url,)
        )
        result = await cursor.fetchone()
        return result is not None
    
    async def mark_url_seen(self, canonical_url: str, content_hash: Optional[str] = None) -> None:
        """Mark a URL as seen."""
        now = datetime.utcnow().isoformat()
        
        # Try to update existing record
        cursor = await self.connection.execute(
            """
            UPDATE seen_urls 
            SET last_seen = ?, seen_count = seen_count + 1, content_hash = COALESCE(?, content_hash)
            WHERE canonical_url = ?
            """,
            (now, content_hash, canonical_url)
        )
        
        # If no rows updated, insert new record
        if cursor.rowcount == 0:
            await self.connection.execute(
                """
                INSERT INTO seen_urls (canonical_url, content_hash, first_seen, last_seen)
                VALUES (?, ?, ?, ?)
                """,
                (canonical_url, content_hash, now, now)
            )
    
    async def is_content_seen(self, content_hash: str) -> bool:
        """Check if content has been seen."""
        cursor = await self.connection.execute(
            "SELECT 1 FROM seen_content WHERE content_hash = ? LIMIT 1",
            (content_hash,)
        )
        result = await cursor.fetchone()
        return result is not None
    
    async def mark_content_seen(self, content_hash: str, source_url: Optional[str] = None) -> None:
        """Mark content as seen."""
        now = datetime.utcnow().isoformat()
        
        # Try to update existing record
        cursor = await self.connection.execute(
            """
            UPDATE seen_content 
            SET last_seen = ?, source_url = COALESCE(?, source_url)
            WHERE content_hash = ?
            """,
            (now, source_url, content_hash)
        )
        
        # If no rows updated, insert new record
        if cursor.rowcount == 0:
            await self.connection.execute(
                """
                INSERT INTO seen_content (content_hash, source_url, first_seen, last_seen)
                VALUES (?, ?, ?, ?)
                """,
                (content_hash, source_url, now, now)
            )
    
    async def get_url_first_seen(self, canonical_url: str) -> Optional[datetime]:
        """Get first seen timestamp for a URL."""
        cursor = await self.connection.execute(
            "SELECT first_seen FROM seen_urls WHERE canonical_url = ?",
            (canonical_url,)
        )
        result = await cursor.fetchone()
        if result:
            return datetime.fromisoformat(result[0])
        return None
    
    async def save_entity_mapping(self, mapping: EntityMappingEntry) -> int:
        """Save an entity mapping entry."""
        cursor = await self.connection.execute(
            """
            INSERT INTO entity_mappings (raw_name, canonical_name, match_method, 
                                        score, source_url, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                mapping.raw_name,
                mapping.canonical_name,
                mapping.match_method,
                mapping.score,
                mapping.source_url,
                mapping.timestamp.isoformat(),
            )
        )
        return cursor.lastrowid
    
    async def save_failed_record(
        self,
        source_name: str,
        source_url: str,
        error_type: str,
        error_message: str,
        raw_data: Optional[dict[str, Any]] = None
    ) -> int:
        """Save a failed record for debugging."""
        cursor = await self.connection.execute(
            """
            INSERT INTO failed_records (source_name, source_url, error_type, 
                                       error_message, raw_data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                source_name,
                source_url,
                error_type,
                error_message,
                json.dumps(raw_data) if raw_data else None,
            )
        )
        return cursor.lastrowid
    
    async def get_record_counts(self) -> dict[str, int]:
        """Get count of records by type."""
        cursor = await self.connection.execute(
            "SELECT record_type, COUNT(*) FROM records GROUP BY record_type"
        )
        results = await cursor.fetchall()
        return {row[0]: row[1] for row in results}
    
    async def get_entity_mappings(self) -> list[EntityMappingEntry]:
        """Get all entity mappings."""
        cursor = await self.connection.execute(
            """
            SELECT raw_name, canonical_name, match_method, score, source_url, timestamp
            FROM entity_mappings
            ORDER BY timestamp DESC
            """
        )
        results = await cursor.fetchall()
        
        mappings = []
        for row in results:
            mappings.append(EntityMappingEntry(
                raw_name=row[0],
                canonical_name=row[1],
                match_method=row[2],
                score=row[3],
                source_url=row[4],
                timestamp=datetime.fromisoformat(row[5]),
            ))
        
        return mappings
    
    async def get_all_records(self, record_type: Optional[str] = None) -> list[dict[str, Any]]:
        """Get all records, optionally filtered by type."""
        if record_type:
            cursor = await self.connection.execute(
                "SELECT content_json FROM records WHERE record_type = ?",
                (record_type,)
            )
        else:
            cursor = await self.connection.execute(
                "SELECT content_json FROM records"
            )
        
        results = await cursor.fetchall()
        return [json.loads(row[0]) for row in results]
    
    async def commit(self) -> None:
        """Commit pending transactions."""
        if self.connection:
            await self.connection.commit()
            self._checkpoint_counter = 0
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.connection:
            await self.commit()
        await self.close()
