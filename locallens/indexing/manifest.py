from __future__ import annotations

import sqlite3
import time
from pathlib import Path, PurePosixPath, PureWindowsPath


class ManifestStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init(self) -> None:
        with self._connect() as conn:
            self._ensure_files_table(conn)
            self._ensure_units_table(conn)
            self._ensure_cache_entries_table(conn)
            self._ensure_indexes(conn)

    def get_file(
        self, workspace_id: str, root_id: str, relative_path: str
    ) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT file_id, content_hash, mtime_ns, size_bytes,
                       text_embedding_profile, vision_embedding_profile,
                       extractor_profile
                FROM files WHERE workspace_id=? AND root_id=? AND relative_path=?
                """,
                (workspace_id, root_id, relative_path),
            ).fetchone()
        if row is None:
            return None
        return {
            "file_id": row[0],
            "content_hash": row[1],
            "mtime_ns": row[2],
            "size_bytes": row[3],
            "text_embedding_profile": row[4],
            "vision_embedding_profile": row[5],
            "extractor_profile": row[6],
        }

    def upsert_file(
        self,
        workspace_id: str,
        root_id: str,
        relative_path: str,
        file_id: str,
        content_hash: str,
        mtime_ns: int,
        size_bytes: int,
        text_embedding_profile: str,
        vision_embedding_profile: str,
        extractor_profile: str,
        point_ids: list[tuple[str, int]],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO files(
                  workspace_id, root_id, relative_path, file_id, content_hash,
                  mtime_ns, size_bytes, text_embedding_profile,
                  vision_embedding_profile, extractor_profile, last_indexed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, root_id, relative_path) DO UPDATE SET
                  file_id=excluded.file_id,
                  content_hash=excluded.content_hash,
                  mtime_ns=excluded.mtime_ns,
                  size_bytes=excluded.size_bytes,
                  text_embedding_profile=excluded.text_embedding_profile,
                  vision_embedding_profile=excluded.vision_embedding_profile,
                  extractor_profile=excluded.extractor_profile,
                  last_indexed_at=excluded.last_indexed_at
                """,
                (
                    workspace_id,
                    root_id,
                    relative_path,
                    file_id,
                    content_hash,
                    mtime_ns,
                    size_bytes,
                    text_embedding_profile,
                    vision_embedding_profile,
                    extractor_profile,
                    time.time(),
                ),
            )
            conn.execute(
                """
                DELETE FROM units
                WHERE workspace_id=? AND root_id=? AND relative_path=?
                """,
                (workspace_id, root_id, relative_path),
            )
            conn.executemany(
                """
                INSERT INTO units(workspace_id, root_id, relative_path, unit_id, point_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (workspace_id, root_id, relative_path, unit_id, point_id)
                    for unit_id, point_id in point_ids
                ],
            )

    def unit_point_ids(
        self, workspace_id: str, root_id: str, relative_path: str
    ) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT point_id FROM units
                WHERE workspace_id=? AND root_id=? AND relative_path=?
                """,
                (workspace_id, root_id, relative_path),
            ).fetchall()
        return [int(row[0]) for row in rows]

    def has_unit(
        self,
        workspace_id: str,
        root_id: str,
        relative_path: str,
        unit_id: str,
        content_hash: str | None = None,
        text_embedding_profile: str | None = None,
        vision_embedding_profile: str | None = None,
    ) -> bool:
        conditions = [
            "u.workspace_id=?",
            "u.root_id=?",
            "u.relative_path=?",
            "u.unit_id=?",
        ]
        values: list[object] = [workspace_id, root_id, relative_path, unit_id]
        if content_hash is not None:
            conditions.append("f.content_hash=?")
            values.append(content_hash)
        if text_embedding_profile is not None:
            conditions.append("f.text_embedding_profile=?")
            values.append(text_embedding_profile)
        if vision_embedding_profile is not None:
            conditions.append("f.vision_embedding_profile=?")
            values.append(vision_embedding_profile)
        query = f"""
            SELECT 1
            FROM units u
            JOIN files f
              ON f.workspace_id=u.workspace_id
             AND f.root_id=u.root_id
             AND f.relative_path=u.relative_path
            WHERE {' AND '.join(conditions)}
            LIMIT 1
        """
        with self._connect() as conn:
            row = conn.execute(query, values).fetchone()
        return row is not None

    def known_paths(self, workspace_id: str, root_id: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT relative_path FROM files WHERE workspace_id=? AND root_id=?",
                (workspace_id, root_id),
            ).fetchall()
        return {row[0] for row in rows}

    def matching_paths(
        self,
        workspace_id: str,
        path_prefix: str,
        root_id: str | None = None,
    ) -> set[str]:
        prefix = path_prefix.strip("/")
        if not prefix:
            return set()
        conditions = ["workspace_id=?"]
        values: list[object] = [workspace_id]
        if root_id:
            conditions.append("root_id=?")
            values.append(root_id)
        conditions.append(
            "(relative_path = ? COLLATE NOCASE OR relative_path LIKE ? ESCAPE '\\' COLLATE NOCASE)"
        )
        escaped_prefix = _escape_like(prefix)
        values.extend([prefix, f"{escaped_prefix}/%"])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT relative_path FROM files WHERE {' AND '.join(conditions)}",
                values,
            ).fetchall()
        return {row[0] for row in rows}

    def unit_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM units").fetchone()
        return int(row[0])

    def remove_file(
        self, workspace_id: str, root_id: str, relative_path: str
    ) -> list[int]:
        point_ids = self.unit_point_ids(workspace_id, root_id, relative_path)
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM units
                WHERE workspace_id=? AND root_id=? AND relative_path=?
                """,
                (workspace_id, root_id, relative_path),
            )
            conn.execute(
                """
                DELETE FROM files
                WHERE workspace_id=? AND root_id=? AND relative_path=?
                """,
                (workspace_id, root_id, relative_path),
            )
        return point_ids

    def stage_cache_entry(
        self,
        *,
        cache_key: str,
        workspace_id: str,
        root_id: str,
        relative_path: str,
        file_id: str,
        content_hash: str,
        entry_type: str,
        payload_sha256: str,
        blob_rel_path: str,
        unit_id: str = "",
    ) -> None:
        _validate_cache_blob_rel_path(blob_rel_path)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cache_entries(
                  cache_key, workspace_id, root_id, relative_path, file_id,
                  unit_id, content_hash, entry_type, payload_sha256,
                  blob_rel_path, state, created_at, committed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'staged', ?, 0)
                ON CONFLICT(cache_key) DO UPDATE SET
                  workspace_id=excluded.workspace_id,
                  root_id=excluded.root_id,
                  relative_path=excluded.relative_path,
                  file_id=excluded.file_id,
                  unit_id=excluded.unit_id,
                  content_hash=excluded.content_hash,
                  entry_type=excluded.entry_type,
                  payload_sha256=excluded.payload_sha256,
                  blob_rel_path=excluded.blob_rel_path,
                  state='staged',
                  created_at=excluded.created_at,
                  committed_at=0
                """,
                (
                    cache_key,
                    workspace_id,
                    root_id,
                    relative_path,
                    file_id,
                    unit_id,
                    content_hash,
                    entry_type,
                    payload_sha256,
                    blob_rel_path.replace("\\", "/"),
                    time.time(),
                ),
            )

    def commit_staged_cache_entries(
        self,
        workspace_id: str,
        root_id: str,
        relative_path: str,
        content_hash: str,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE cache_entries
                SET state='committed', committed_at=?
                WHERE workspace_id=?
                  AND root_id=?
                  AND relative_path=?
                  AND content_hash=?
                  AND state='staged'
                """,
                (time.time(), workspace_id, root_id, relative_path, content_hash),
            )
        return int(cursor.rowcount)

    def discard_staged_cache_entries(
        self,
        workspace_id: str,
        root_id: str,
        relative_path: str,
    ) -> list[str]:
        return self._delete_cache_entries(
            workspace_id=workspace_id,
            root_id=root_id,
            relative_path=relative_path,
            state="staged",
        )

    def remove_cache_entries_for_file(
        self,
        workspace_id: str,
        root_id: str,
        relative_path: str,
        content_hash: str | None = None,
    ) -> list[str]:
        return self._delete_cache_entries(
            workspace_id=workspace_id,
            root_id=root_id,
            relative_path=relative_path,
            content_hash=content_hash,
        )

    def cache_entry_count(
        self,
        *,
        workspace_id: str | None = None,
        root_id: str | None = None,
        relative_path: str | None = None,
        state: str | None = None,
    ) -> int:
        conditions: list[str] = []
        values: list[object] = []
        if workspace_id is not None:
            conditions.append("workspace_id=?")
            values.append(workspace_id)
        if root_id is not None:
            conditions.append("root_id=?")
            values.append(root_id)
        if relative_path is not None:
            conditions.append("relative_path=?")
            values.append(relative_path)
        if state is not None:
            conditions.append("state=?")
            values.append(state)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM cache_entries{where}", values
            ).fetchone()
        return int(row[0])

    def committed_cache_entry(
        self,
        *,
        cache_key: str,
        workspace_id: str,
        root_id: str,
        relative_path: str,
        content_hash: str,
        entry_type: str,
    ) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  c.file_id, c.unit_id, c.payload_sha256, c.blob_rel_path,
                  c.committed_at
                FROM cache_entries c
                JOIN files f
                  ON f.workspace_id=c.workspace_id
                 AND f.root_id=c.root_id
                 AND f.relative_path=c.relative_path
                 AND f.file_id=c.file_id
                 AND f.content_hash=c.content_hash
                WHERE c.cache_key=?
                  AND c.workspace_id=?
                  AND c.root_id=?
                  AND c.relative_path=?
                  AND c.content_hash=?
                  AND c.entry_type=?
                  AND c.state='committed'
                LIMIT 1
                """,
                (
                    cache_key,
                    workspace_id,
                    root_id,
                    relative_path,
                    content_hash,
                    entry_type,
                ),
            ).fetchone()
        if row is None:
            return None
        return {
            "cache_key": cache_key,
            "workspace_id": workspace_id,
            "root_id": root_id,
            "relative_path": relative_path,
            "file_id": row[0],
            "unit_id": row[1],
            "content_hash": content_hash,
            "entry_type": entry_type,
            "payload_sha256": row[2],
            "blob_rel_path": row[3],
            "committed_at": row[4],
        }

    def _delete_cache_entries(
        self,
        *,
        workspace_id: str,
        root_id: str,
        relative_path: str,
        content_hash: str | None = None,
        state: str | None = None,
    ) -> list[str]:
        conditions = ["workspace_id=?", "root_id=?", "relative_path=?"]
        values: list[object] = [workspace_id, root_id, relative_path]
        if content_hash is not None:
            conditions.append("content_hash=?")
            values.append(content_hash)
        if state is not None:
            conditions.append("state=?")
            values.append(state)
        where = " AND ".join(conditions)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT blob_rel_path FROM cache_entries WHERE {where}", values
            ).fetchall()
            conn.execute(f"DELETE FROM cache_entries WHERE {where}", values)
        return [str(row[0]) for row in rows]

    def purge(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM units")
            conn.execute("DELETE FROM files")
            conn.execute("DELETE FROM cache_entries")
        with self._connect() as conn:
            conn.execute("VACUUM")

    @staticmethod
    def _add_column_if_missing(
        conn: sqlite3.Connection, table_name: str, column_name: str, schema: str
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        if column_name not in {row[1] for row in rows}:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {schema}")

    def _ensure_files_table(self, conn: sqlite3.Connection) -> None:
        if not self._table_exists(conn, "files"):
            self._create_files_table(conn)
            return
        if self._primary_key_columns(conn, "files") != [
            "workspace_id",
            "root_id",
            "relative_path",
        ]:
            self._rebuild_files_table(conn)
        self._add_column_if_missing(
            conn, "files", "text_embedding_profile", "TEXT NOT NULL DEFAULT ''"
        )
        self._add_column_if_missing(
            conn, "files", "vision_embedding_profile", "TEXT NOT NULL DEFAULT ''"
        )
        self._add_column_if_missing(
            conn, "files", "extractor_profile", "TEXT NOT NULL DEFAULT ''"
        )
        self._add_column_if_missing(
            conn, "files", "last_indexed_at", "REAL NOT NULL DEFAULT 0"
        )

    def _ensure_units_table(self, conn: sqlite3.Connection) -> None:
        if not self._table_exists(conn, "units"):
            self._create_units_table(conn)
            return
        if self._primary_key_columns(conn, "units") != [
            "workspace_id",
            "root_id",
            "relative_path",
            "unit_id",
        ]:
            self._rebuild_units_table(conn)

    def _ensure_cache_entries_table(self, conn: sqlite3.Connection) -> None:
        if not self._table_exists(conn, "cache_entries"):
            self._create_cache_entries_table(conn)
            return

    @staticmethod
    def _ensure_indexes(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_files_workspace_root_path_nocase
            ON files(workspace_id, root_id, relative_path COLLATE NOCASE)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_files_workspace_path_nocase
            ON files(workspace_id, relative_path COLLATE NOCASE)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cache_entries_file_state
            ON cache_entries(workspace_id, root_id, relative_path, state)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cache_entries_file_content
            ON cache_entries(workspace_id, root_id, relative_path, content_hash)
            """
        )

    @staticmethod
    def _create_files_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE files (
                workspace_id TEXT NOT NULL DEFAULT 'default',
                root_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                file_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                mtime_ns INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                text_embedding_profile TEXT NOT NULL DEFAULT '',
                vision_embedding_profile TEXT NOT NULL DEFAULT '',
                extractor_profile TEXT NOT NULL DEFAULT '',
                last_indexed_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (workspace_id, root_id, relative_path)
            )
            """
        )

    @staticmethod
    def _create_units_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE units (
                workspace_id TEXT NOT NULL DEFAULT 'default',
                root_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                point_id INTEGER NOT NULL,
                PRIMARY KEY (workspace_id, root_id, relative_path, unit_id)
            )
            """
        )

    @staticmethod
    def _create_cache_entries_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE cache_entries (
                cache_key TEXT NOT NULL PRIMARY KEY,
                workspace_id TEXT NOT NULL DEFAULT 'default',
                root_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                file_id TEXT NOT NULL,
                unit_id TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                blob_rel_path TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('staged', 'committed')),
                created_at REAL NOT NULL DEFAULT 0,
                committed_at REAL NOT NULL DEFAULT 0
            )
            """
        )

    def _rebuild_files_table(self, conn: sqlite3.Connection) -> None:
        columns = self._column_names(conn, "files")
        conn.execute("ALTER TABLE files RENAME TO files_old")
        self._create_files_table(conn)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO files(
                workspace_id, root_id, relative_path, file_id, content_hash,
                mtime_ns, size_bytes, text_embedding_profile,
                vision_embedding_profile, extractor_profile, last_indexed_at
            )
            SELECT
                {self._select_column_or_default(columns, "workspace_id", "'default'")},
                root_id,
                relative_path,
                file_id,
                content_hash,
                mtime_ns,
                size_bytes,
                {self._select_column_or_default(columns, "text_embedding_profile", "''")},
                {self._select_column_or_default(columns, "vision_embedding_profile", "''")},
                {self._select_column_or_default(columns, "extractor_profile", "''")},
                {self._select_column_or_default(columns, "last_indexed_at", "0")}
            FROM files_old
            """
        )
        conn.execute("DROP TABLE files_old")

    def _rebuild_units_table(self, conn: sqlite3.Connection) -> None:
        columns = self._column_names(conn, "units")
        conn.execute("ALTER TABLE units RENAME TO units_old")
        self._create_units_table(conn)
        conn.execute(
            f"""
            INSERT OR REPLACE INTO units(
                workspace_id, root_id, relative_path, unit_id, point_id
            )
            SELECT
                {self._select_column_or_default(columns, "workspace_id", "'default'")},
                root_id,
                relative_path,
                unit_id,
                point_id
            FROM units_old
            """
        )
        conn.execute("DROP TABLE units_old")

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}

    @staticmethod
    def _primary_key_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row[1] for row in sorted((row for row in rows if row[5]), key=lambda r: r[5])]

    @staticmethod
    def _select_column_or_default(
        columns: set[str], column_name: str, default_sql: str
    ) -> str:
        return column_name if column_name in columns else default_sql


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_cache_blob_rel_path(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("cache blob path must be relative")
    normalized = value.replace("\\", "/")
    if normalized.startswith(("file:", "//")):
        raise ValueError("cache blob path must be relative")
    if PureWindowsPath(value).is_absolute() or PurePosixPath(normalized).is_absolute():
        raise ValueError("cache blob path must be relative")
    if len(normalized) >= 2 and normalized[1] == ":":
        raise ValueError("cache blob path must be relative")
    parts = PurePosixPath(normalized).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("cache blob path must not escape cache root")
