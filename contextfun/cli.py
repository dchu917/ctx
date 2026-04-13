import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
import re


# Default to a project-local store to avoid sandbox issues
DEFAULT_HOME = Path.cwd() / ".contextfun"
DEFAULT_DB = DEFAULT_HOME / "context.db"
ATTACH_DIR = DEFAULT_HOME / "attachments"
CURRENT_FILE = DEFAULT_HOME / "current.json"
SEARCH_INDEX_VERSION = "5"
SEARCH_INDEX_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    kind UNINDEXED,
    workstream_id UNINDEXED,
    session_id UNINDEXED,
    entry_id UNINDEXED,
    workstream_slug,
    workstream_title,
    session_title,
    body,
    tags,
    created_at UNINDEXED,
    tokenize = 'porter unicode61 remove_diacritics 2'
);
"""


SCHEMA = [
    "PRAGMA foreign_keys = ON;",
    """
    CREATE TABLE IF NOT EXISTS workstream (
        id INTEGER PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        description TEXT,
        tags TEXT,
        workspace TEXT,
        created_at TEXT NOT NULL,
        metadata TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS session (
        id INTEGER PRIMARY KEY,
        workstream_id INTEGER,
        title TEXT NOT NULL,
        agent TEXT,
        tags TEXT,
        workspace TEXT,
        created_at TEXT NOT NULL,
        metadata TEXT,
        FOREIGN KEY(workstream_id) REFERENCES workstream(id) ON DELETE SET NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS entry (
        id INTEGER PRIMARY KEY,
        session_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        content TEXT,
        extras TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES session(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ctx_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS workstream_source_link (
        id INTEGER PRIMARY KEY,
        workstream_id INTEGER NOT NULL,
        source TEXT NOT NULL,
        external_session_id TEXT NOT NULL,
        transcript_path TEXT,
        transcript_mtime REAL,
        message_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        metadata TEXT,
        FOREIGN KEY(workstream_id) REFERENCES workstream(id) ON DELETE CASCADE,
        UNIQUE(workstream_id, source),
        UNIQUE(source, external_session_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS session_source_link (
        id INTEGER PRIMARY KEY,
        session_id INTEGER NOT NULL,
        workstream_id INTEGER NOT NULL,
        source TEXT NOT NULL,
        external_session_id TEXT NOT NULL,
        transcript_path TEXT,
        transcript_mtime REAL,
        message_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        metadata TEXT,
        FOREIGN KEY(session_id) REFERENCES session(id) ON DELETE CASCADE,
        FOREIGN KEY(workstream_id) REFERENCES workstream(id) ON DELETE CASCADE,
        UNIQUE(session_id, source),
        UNIQUE(source, external_session_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_entry_session ON entry(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_workstream_source_link_ws ON workstream_source_link(workstream_id);",
    "CREATE INDEX IF NOT EXISTS idx_workstream_source_link_source ON workstream_source_link(source, external_session_id);",
    "CREATE INDEX IF NOT EXISTS idx_session_source_link_session ON session_source_link(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_session_source_link_workstream ON session_source_link(workstream_id);",
    "CREATE INDEX IF NOT EXISTS idx_session_source_link_source ON session_source_link(source, external_session_id);",
]


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def ensure_home(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "attachments").mkdir(parents=True, exist_ok=True)
    # current.json is created on demand


def _home_dir() -> Path:
    env_db = os.getenv("CONTEXTFUN_DB")
    if env_db:
        return Path(os.path.expanduser(env_db)).resolve().parent
    return DEFAULT_HOME


def _attach_dir() -> Path:
    return _home_dir() / "attachments"


def _current_file() -> Path:
    slot = os.getenv("CTX_AGENT_SLOT") or os.getenv("CTX_AGENT_KEY")
    if slot:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(slot)).strip("-")
        if safe:
            return _home_dir() / f"current.{safe}.json"
    return _home_dir() / CURRENT_FILE.name


def _get_current_workstream():
    cur_file = _current_file()
    if cur_file.exists():
        try:
            return json.loads(cur_file.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _set_current_workstream(conn: sqlite3.Connection, *, slug=None, wid=None):
    if wid is not None:
        row = conn.execute("SELECT id, slug, title FROM workstream WHERE id = ?", (wid,)).fetchone()
    else:
        row = conn.execute("SELECT id, slug, title FROM workstream WHERE slug = ?", (slug,)).fetchone()
    if not row:
        raise SystemExit("Workstream not found")
    data = {"id": int(row["id"]), "slug": row["slug"], "title": row["title"]}
    cur_file = _current_file()
    cur_file.parent.mkdir(parents=True, exist_ok=True)
    cur_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _ensure_search_index(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(SEARCH_INDEX_SQL)
        return True
    except sqlite3.OperationalError:
        return False


def _migrate(conn: sqlite3.Connection) -> None:
    # Create workstream table if missing
    if not _table_exists(conn, "workstream"):
        conn.executescript(
            """
            CREATE TABLE workstream (
                id INTEGER PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT,
                tags TEXT,
                workspace TEXT,
                created_at TEXT NOT NULL,
                metadata TEXT
            );
            """
        )
    # Add workstream_id to session if missing
    if not _column_exists(conn, "session", "workstream_id"):
        conn.execute("ALTER TABLE session ADD COLUMN workstream_id INTEGER")
    if not _table_exists(conn, "workstream_source_link"):
        conn.executescript(
            """
            CREATE TABLE workstream_source_link (
                id INTEGER PRIMARY KEY,
                workstream_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                external_session_id TEXT NOT NULL,
                transcript_path TEXT,
                transcript_mtime REAL,
                message_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY(workstream_id) REFERENCES workstream(id) ON DELETE CASCADE,
                UNIQUE(workstream_id, source),
                UNIQUE(source, external_session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_workstream_source_link_ws ON workstream_source_link(workstream_id);
            CREATE INDEX IF NOT EXISTS idx_workstream_source_link_source ON workstream_source_link(source, external_session_id);
            """
        )
    if not _table_exists(conn, "session_source_link"):
        conn.executescript(
            """
            CREATE TABLE session_source_link (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL,
                workstream_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                external_session_id TEXT NOT NULL,
                transcript_path TEXT,
                transcript_mtime REAL,
                message_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY(session_id) REFERENCES session(id) ON DELETE CASCADE,
                FOREIGN KEY(workstream_id) REFERENCES workstream(id) ON DELETE CASCADE,
                UNIQUE(session_id, source),
                UNIQUE(source, external_session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_session_source_link_session ON session_source_link(session_id);
            CREATE INDEX IF NOT EXISTS idx_session_source_link_workstream ON session_source_link(workstream_id);
            CREATE INDEX IF NOT EXISTS idx_session_source_link_source ON session_source_link(source, external_session_id);
            """
        )
    if not _table_exists(conn, "ctx_meta"):
        conn.execute(
            """
            CREATE TABLE ctx_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
    if _table_exists(conn, "workstream_source_link") and _table_exists(conn, "session_source_link"):
        legacy_rows = conn.execute(
            """
            SELECT * FROM workstream_source_link
            ORDER BY id ASC
            """
        ).fetchall()
        for legacy in legacy_rows:
            existing = conn.execute(
                """
                SELECT 1 FROM session_source_link
                WHERE source = ? AND external_session_id = ?
                """,
                (legacy["source"], legacy["external_session_id"]),
            ).fetchone()
            if existing:
                continue
            latest_session = conn.execute(
                """
                SELECT id FROM session
                WHERE workstream_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (legacy["workstream_id"],),
            ).fetchone()
            if not latest_session:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO session_source_link(
                    session_id, workstream_id, source, external_session_id,
                    transcript_path, transcript_mtime, message_count,
                    created_at, updated_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(latest_session["id"]),
                    int(legacy["workstream_id"]),
                    legacy["source"],
                    legacy["external_session_id"],
                    legacy["transcript_path"],
                    legacy["transcript_mtime"],
                    legacy["message_count"],
                    legacy["created_at"],
                    legacy["updated_at"],
                    legacy["metadata"],
                ),
            )
    _ensure_search_index(conn)


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _workstream_source_links(conn: sqlite3.Connection, workstream_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM workstream_source_link
        WHERE workstream_id = ?
        ORDER BY source ASC
        """,
        (workstream_id,),
    ).fetchall()


def _session_source_links(conn: sqlite3.Connection, session_id: int) -> list[sqlite3.Row]:
    if not _table_exists(conn, "session_source_link"):
        return []
    return conn.execute(
        """
        SELECT * FROM session_source_link
        WHERE session_id = ?
        ORDER BY source ASC
        """,
        (session_id,),
    ).fetchall()


def _session_source_links_for_workstream(conn: sqlite3.Connection, workstream_id: int) -> list[sqlite3.Row]:
    if not _table_exists(conn, "session_source_link"):
        return []
    return conn.execute(
        """
        SELECT * FROM session_source_link
        WHERE workstream_id = ?
        ORDER BY source ASC, session_id DESC
        """,
        (workstream_id,),
    ).fetchall()


def _session_source_links_summary(conn: sqlite3.Connection, session_id: int) -> str:
    links = _session_source_links(conn, session_id)
    if not links:
        return ""
    parts = []
    for link in links:
        parts.append(f"{link['source']}:{link['external_session_id']}")
    return ", ".join(parts)


def _source_links_summary(conn: sqlite3.Connection, workstream_id: int) -> str:
    links = _session_source_links_for_workstream(conn, workstream_id)
    if not links:
        links = _workstream_source_links(conn, workstream_id)
    if not links:
        return ""
    parts = []
    for link in links:
        session_suffix = f"->S{link['session_id']}" if "session_id" in link.keys() else ""
        parts.append(f"{link['source']}:{link['external_session_id']}{session_suffix}")
    return ", ".join(parts)


def init_db(db_path: Path, quiet: bool = False) -> None:
    ensure_home(db_path.parent)
    with connect(db_path) as conn:
        cur = conn.cursor()
        for stmt in SCHEMA:
            cur.execute(stmt)
        # Best-effort migration if existing DB lacks new fields
        _migrate(conn)
        _maybe_refresh_search_index(conn)
        conn.commit()
    if not quiet:
        print(f"Initialized DB at {db_path}")


def cmd_init(args: argparse.Namespace):
    init_db(Path(args.db))


def parse_tags(tags):
    if not tags:
        return ""
    # Normalize: comma-separated, trimmed, de-duped
    items = [t.strip() for t in tags.split(",") if t.strip()]
    dedup = []
    for t in items:
        if t not in dedup:
            dedup.append(t)
    return ",".join(dedup)


def cmd_session_new(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    with connect(db) as conn:
        ws_id = None
        if args.workstream_slug or args.workstream_id:
            ws_id = _resolve_workstream_id(conn, slug=args.workstream_slug, wid=args.workstream_id)
        else:
            cur_current = _get_current_workstream()
            if cur_current:
                # Validate it exists
                row = conn.execute("SELECT id FROM workstream WHERE id = ?", (cur_current.get("id"),)).fetchone()
                if row:
                    ws_id = int(row["id"])
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO session(workstream_id, title, agent, tags, workspace, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ws_id,
                args.title,
                args.agent,
                parse_tags(args.tags),
                os.path.abspath(args.workspace) if args.workspace else None,
                now_iso(),
                json.dumps({"summary": args.summary}) if args.summary else None,
            ),
        )
        sid = cur.lastrowid
        _index_session(conn, int(sid))
        conn.commit()
    print(sid)


def _print_sessions(rows: list[sqlite3.Row]):
    for r in rows:
        tags = f" [{r['tags']}]" if r["tags"] else ""
        agent = f" @{r['agent']}" if r["agent"] else ""
        ws = f" ({r['workspace']})" if r["workspace"] else ""
        wslug = f" #{r['workstream_slug']}" if "workstream_slug" in r.keys() and r["workstream_slug"] else ""
        print(f"{r['id']}: {r['title']}{agent}{tags}{ws}{wslug} - {r['created_at']}")


def cmd_session_list(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    q = [
        "SELECT s.*, w.slug as workstream_slug FROM session s LEFT JOIN workstream w ON s.workstream_id = w.id WHERE 1=1"
    ]
    params: list[object] = []
    if args.agent:
        q.append("AND s.agent = ?")
        params.append(args.agent)
    if args.tag:
        q.append("AND (s.tags LIKE ? OR s.tags LIKE ? OR s.tags = ?) ")
        t = args.tag
        params.extend([f"{t},%", f"%,{t}", t])
    if args.query:
        q.append("AND (s.title LIKE ?)")
        params.append(f"%{args.query}%")
    if args.workstream_slug:
        q.append("AND w.slug = ?")
        params.append(args.workstream_slug)
    q.append("ORDER BY id DESC")
    sql = " ".join(q)
    with connect(db) as conn:
        rows = conn.execute(sql, params).fetchall()
    _print_sessions(rows)


def cmd_session_show(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    with connect(db) as conn:
        s = conn.execute(
            "SELECT s.*, w.slug as workstream_slug FROM session s LEFT JOIN workstream w ON s.workstream_id = w.id WHERE s.id = ?",
            (args.id,),
        ).fetchone()
        if not s:
            print(f"Session {args.id} not found", file=sys.stderr)
            sys.exit(1)
        print(f"Session {s['id']}: {s['title']}")
        if s["workstream_slug"]:
            print(f"  Workstream: {s['workstream_slug']}")
        if s["agent"]:
            print(f"  Agent: {s['agent']}")
        if s["tags"]:
            print(f"  Tags: {s['tags']}")
        if s["workspace"]:
            print(f"  Workspace: {s['workspace']}")
        print(f"  Created: {s['created_at']}")
        if s["metadata"]:
            try:
                meta = json.loads(s["metadata"]) or {}
                if meta.get("summary"):
                    print(f"  Summary: {meta['summary']}")
            except Exception:
                pass
        linked = _session_source_links_summary(conn, int(s["id"]))
        if linked:
            print(f"  External links: {linked}")
        print("-- Entries --")
        rows = conn.execute(
            "SELECT * FROM entry WHERE session_id = ? ORDER BY id DESC",
            (args.id,),
        ).fetchall()
        for r in rows:
            header = f"[{r['id']}] {r['type']} - {r['created_at']}"
            print(header)
            if r["content"]:
                print(r["content"])  # content may be long
            if r["extras"]:
                try:
                    ex = json.loads(r["extras"]) or {}
                    if ex:
                        print(f"  extras: {json.dumps(ex)}")
                except Exception:
                    pass
            print("")


def _attachment_roots_for_session(db_path: Path, session_id: int) -> list[Path]:
    roots = [db_path.parent / "attachments" / str(session_id)]
    legacy_root = _attach_dir() / str(session_id)
    if legacy_root not in roots:
        roots.append(legacy_root)
    return roots


def _delete_session_attachments(db_path: Path, session_id: int) -> None:
    for root in _attachment_roots_for_session(db_path, session_id):
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)


def _delete_entry_attachments(db_path: Path, session_id: int, entry_id: int) -> None:
    for root in _attachment_roots_for_session(db_path, session_id):
        target = root / str(entry_id)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


def cmd_session_delete(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    with connect(db) as conn:
        row = conn.execute(
            "SELECT s.*, w.slug as workstream_slug FROM session s "
            "LEFT JOIN workstream w ON s.workstream_id = w.id "
            "WHERE s.id = ?",
            (args.id,),
        ).fetchone()
        if not row:
            print(f"Session {args.id} not found", file=sys.stderr)
            sys.exit(1)
        _delete_search_docs_for_session(conn, int(args.id))
        conn.execute("DELETE FROM session WHERE id = ?", (args.id,))
        conn.commit()

    _delete_session_attachments(db, args.id)

    workstream = f" #{row['workstream_slug']}" if row["workstream_slug"] else ""
    print(f"Deleted session {row['id']}: {row['title']}{workstream}")


def cmd_entry_load(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    with connect(db) as conn:
        row = conn.execute(
            """
            SELECT e.id, e.session_id, s.workstream_id, w.slug AS workstream_slug
            FROM entry e
            JOIN session s ON s.id = e.session_id
            LEFT JOIN workstream w ON w.id = s.workstream_id
            WHERE e.id = ?
            """,
            (args.id,),
        ).fetchone()
        if not row:
            print(f"Entry {args.id} not found", file=sys.stderr)
            sys.exit(1)
        _set_entry_load_behavior(conn, args.id, args.mode)
        conn.commit()
    print(f"Entry {args.id} load behavior set to {args.mode}")


def cmd_entry_delete(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    with connect(db) as conn:
        row = conn.execute(
            """
            SELECT e.id, e.session_id, e.type, s.workstream_id, w.slug AS workstream_slug
            FROM entry e
            JOIN session s ON s.id = e.session_id
            LEFT JOIN workstream w ON w.id = s.workstream_id
            WHERE e.id = ?
            """,
            (args.id,),
        ).fetchone()
        if not row:
            print(f"Entry {args.id} not found", file=sys.stderr)
            sys.exit(1)
        _delete_search_docs_for_entry(conn, int(args.id))
        conn.execute("DELETE FROM entry WHERE id = ?", (args.id,))
        conn.commit()

    _delete_entry_attachments(db, int(row["session_id"]), args.id)
    workstream = f" #{row['workstream_slug']}" if row["workstream_slug"] else ""
    print(f"Deleted entry {row['id']} ({row['type']}){workstream}")


def _resolve_workstream_id(conn: sqlite3.Connection, *, slug=None, wid=None) -> int:
    if wid is not None:
        row = conn.execute("SELECT id FROM workstream WHERE id = ?", (wid,)).fetchone()
        if not row:
            print(f"Workstream id {wid} not found", file=sys.stderr)
            sys.exit(1)
        return wid
    if slug:
        row = conn.execute("SELECT id FROM workstream WHERE slug = ?", (slug,)).fetchone()
        if not row:
            print(f"Workstream '{slug}' not found", file=sys.stderr)
            sys.exit(1)
        return int(row["id"])
    print("Specify --workstream-slug or --workstream-id", file=sys.stderr)
    sys.exit(2)


def _workstream_row_by_ref(conn: sqlite3.Connection, ref: str):
    return conn.execute(
        """
        SELECT *
        FROM workstream
        WHERE slug = ? OR title = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (ref, ref),
    ).fetchone()


def _slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-") or "ws"


def _workstream_name_conflict(
    conn: sqlite3.Connection,
    *,
    title: str,
    slug: str,
    exclude_id: int | None = None,
):
    if exclude_id is None:
        return conn.execute(
            "SELECT id FROM workstream WHERE slug = ? OR title = ? LIMIT 1",
            (slug, title),
        ).fetchone()
    return conn.execute(
        "SELECT id FROM workstream WHERE (slug = ? OR title = ?) AND id != ? LIMIT 1",
        (slug, title, exclude_id),
    ).fetchone()


def _unique_workstream_identity(
    conn: sqlite3.Connection,
    *,
    requested_name: str,
    requested_slug: str | None = None,
    exclude_id: int | None = None,
):
    base_name = requested_name.strip() or "Workstream"
    base_slug = requested_slug or _slugify(base_name)
    title = base_name
    slug = base_slug
    renamed = False
    index = 0
    while _workstream_name_conflict(conn, title=title, slug=slug, exclude_id=exclude_id):
        index += 1
        renamed = True
        title = f"{base_name} ({index})"
        slug = f"{base_slug}-{index}"
    return title, slug, renamed


def cmd_workstream_ensure(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    requested_name = args.name
    slug = args.slug or _slugify(requested_name)
    created = False
    renamed = False
    with connect(db) as conn:
        row = None
        name = requested_name
        if getattr(args, "unique_if_exists", False):
            name, slug, renamed = _unique_workstream_identity(
                conn,
                requested_name=requested_name,
                requested_slug=slug,
            )
        else:
            row = conn.execute("SELECT * FROM workstream WHERE slug = ?", (slug,)).fetchone()
        if not row:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO workstream(slug, title, description, tags, workspace, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    slug,
                    name,
                    None,
                    None,
                    os.path.abspath(args.workspace) if args.workspace else None,
                    now_iso(),
                    None,
                ),
            )
            wid = cur.lastrowid
            conn.commit()
            row = conn.execute("SELECT * FROM workstream WHERE id = ?", (wid,)).fetchone()
            created = True
        if args.set_current:
            _set_current_workstream(conn, slug=row["slug"], wid=None)
        _index_workstream(conn, int(row["id"]))
        conn.commit()
    result = {
        "id": int(row["id"]),
        "slug": row["slug"],
        "title": row["title"],
        "created": created,
        "renamed": renamed,
        "requested_name": requested_name,
    }
    if args.json:
        print(json.dumps(result))
    else:
        status = "created" if created else "existing"
        suffix = f" (requested '{requested_name}')" if renamed else ""
        print(f"{result['slug']} (id {result['id']}) - {status}{suffix}")


def cmd_workstream_rename(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    with connect(db) as conn:
        row = _workstream_row_by_ref(conn, args.ref)
        if not row:
            print(f"Workstream '{args.ref}' not found", file=sys.stderr)
            sys.exit(1)
        new_title, new_slug, renamed = _unique_workstream_identity(
            conn,
            requested_name=args.new_name,
            exclude_id=int(row["id"]),
        )
        conn.execute(
            "UPDATE workstream SET title = ?, slug = ? WHERE id = ?",
            (new_title, new_slug, int(row["id"])),
        )
        _index_workstream(conn, int(row["id"]))
        cur = _get_current_workstream()
        if cur and int(cur.get("id")) == int(row["id"]):
            _set_current_workstream(conn, wid=int(row["id"]))
        conn.commit()
        result = {
            "id": int(row["id"]),
            "old_slug": row["slug"],
            "old_title": row["title"],
            "slug": new_slug,
            "title": new_title,
            "renamed": renamed,
            "requested_name": args.new_name,
        }
    if args.json:
        print(json.dumps(result))
    else:
        suffix = f" (requested '{args.new_name}')" if renamed else ""
        print(f"Renamed workstream {result['old_slug']} -> {result['slug']}{suffix}")


def cmd_workstream_new(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    with connect(db) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO workstream(slug, title, description, tags, workspace, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                args.slug,
                args.title,
                args.description or None,
                parse_tags(args.tags),
                os.path.abspath(args.workspace) if args.workspace else None,
                now_iso(),
                json.dumps({"summary": args.summary}) if args.summary else None,
            ),
        )
        wid = cur.lastrowid
        _index_workstream(conn, int(wid))
        conn.commit()
    print(wid)


def _preview_text(text, limit: int = 100) -> str:
    if not text:
        return ""
    collapsed = " ".join(text.strip().split())
    if len(collapsed) > limit:
        return collapsed[: limit - 3] + "..."
    return collapsed


def _looks_like_ctx_noise(text: str) -> bool:
    collapsed = " ".join((text or "").strip().split()).lower()
    if not collapsed:
        return True
    noise_markers = (
        "base directory for this skill:",
        "launching skill:",
        "args from unknown skill:",
        "unknown skill:",
        "conversation compacted",
        "no matches found",
        "<local-command-caveat>",
        "<command-message>",
        "<command-name>",
        "<command-args>",
        "tip: press tab to queue a message when a task is running",
        "openai codex (v",
        "[rerun:",
    )
    if any(marker in collapsed for marker in noise_markers):
        return True
    if collapsed.startswith("davidchu@") and "% codex" in collapsed:
        return True
    return False


def _flatten_search_text(value) -> list[str]:
    out: list[str] = []
    if value is None:
        return out
    if isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
        return out
    if isinstance(value, (int, float, bool)):
        out.append(str(value))
        return out
    if isinstance(value, dict):
        for k, v in value.items():
            out.extend(_flatten_search_text(k))
            out.extend(_flatten_search_text(v))
        return out
    if isinstance(value, list):
        for item in value:
            out.extend(_flatten_search_text(item))
        return out
    return out


def _search_tags(*parts) -> str:
    vals = []
    for part in parts:
        if not part:
            continue
        vals.append(str(part).strip())
    return " ".join(v for v in vals if v)


def _entry_extras_search_text(extras) -> str:
    if not isinstance(extras, dict):
        return " ".join(_flatten_search_text(extras))
    filtered = {
        k: v
        for k, v in extras.items()
        if k not in {"source", "role", "attachment", "source_file", "load_behavior"}
    }
    return " ".join(_flatten_search_text(filtered))


def _entry_extras_dict(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, sqlite3.Row):
        value = raw["extras"] if "extras" in raw.keys() else None
    else:
        value = raw
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _entry_load_behavior(raw) -> str:
    extras = _entry_extras_dict(raw)
    mode = str(extras.get("load_behavior") or "default").strip().lower()
    return mode if mode in {"default", "pin", "exclude"} else "default"


def _entry_is_excluded_from_load(raw) -> bool:
    return _entry_load_behavior(raw) == "exclude"


def _entry_is_pinned_for_load(raw) -> bool:
    return _entry_load_behavior(raw) == "pin"


def _entry_role(raw) -> str:
    extras = _entry_extras_dict(raw)
    role = str(extras.get("role") or "").strip().lower()
    return role


def _entry_display_label(raw) -> str:
    entry_type = ""
    if isinstance(raw, sqlite3.Row) and "type" in raw.keys():
        entry_type = str(raw["type"] or "").strip().lower()
    elif isinstance(raw, dict):
        entry_type = str(raw.get("type") or "").strip().lower()
    role = _entry_role(raw)
    if role and role not in {"", entry_type}:
        return f"{entry_type}/{role}" if entry_type else role
    return entry_type or role or "note"


def _set_entry_load_behavior(conn: sqlite3.Connection, entry_id: int, mode: str) -> dict:
    normalized = str(mode or "").strip().lower()
    if normalized not in {"default", "pin", "exclude"}:
        print(f"Unsupported load behavior: {mode}", file=sys.stderr)
        sys.exit(2)
    row = conn.execute("SELECT * FROM entry WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        print(f"Entry {entry_id} not found", file=sys.stderr)
        sys.exit(1)
    extras = _entry_extras_dict(row)
    if normalized == "default":
        extras.pop("load_behavior", None)
    else:
        extras["load_behavior"] = normalized
    conn.execute(
        "UPDATE entry SET extras = ? WHERE id = ?",
        (json.dumps(extras) if extras else None, entry_id),
    )
    _index_entry(conn, int(entry_id))
    return extras


def _delete_search_docs_for_workstream(conn: sqlite3.Connection, workstream_id: int) -> None:
    if not _table_exists(conn, "search_index"):
        return
    conn.execute(
        "DELETE FROM search_index WHERE kind = 'workstream' AND workstream_id = ?",
        (str(workstream_id),),
    )


def _delete_search_docs_for_session(conn: sqlite3.Connection, session_id: int) -> None:
    if not _table_exists(conn, "search_index"):
        return
    conn.execute(
        "DELETE FROM search_index WHERE session_id = ?",
        (str(session_id),),
    )


def _delete_search_docs_for_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    if not _table_exists(conn, "search_index"):
        return
    conn.execute(
        "DELETE FROM search_index WHERE kind = 'entry' AND entry_id = ?",
        (str(entry_id),),
    )


def _index_workstream(conn: sqlite3.Connection, workstream_id: int) -> None:
    if not _ensure_search_index(conn):
        return
    row = conn.execute("SELECT * FROM workstream WHERE id = ?", (workstream_id,)).fetchone()
    _delete_search_docs_for_workstream(conn, workstream_id)
    if not row:
        return
    meta = {}
    if row["metadata"]:
        try:
            meta = json.loads(row["metadata"]) or {}
        except Exception:
            meta = {}
    body = "\n".join(
        [
            t
            for t in [
                row["description"] or "",
                str(meta.get("summary") or "").strip(),
                row["workspace"] or "",
            ]
            if t
        ]
    )
    conn.execute(
        """
        INSERT INTO search_index(
            kind, workstream_id, session_id, entry_id, workstream_slug, workstream_title,
            session_title, body, tags, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "workstream",
            str(workstream_id),
            "",
            "",
            row["slug"],
            row["title"],
            "",
            body,
            _search_tags(row["slug"], row["title"], row["tags"]),
            row["created_at"],
        ),
    )


def _index_session(conn: sqlite3.Connection, session_id: int) -> None:
    if not _ensure_search_index(conn):
        return
    row = conn.execute(
        """
        SELECT s.*, w.slug AS workstream_slug, w.title AS workstream_title, w.tags AS workstream_tags
        FROM session s
        LEFT JOIN workstream w ON w.id = s.workstream_id
        WHERE s.id = ?
        """,
        (session_id,),
    ).fetchone()
    _delete_search_docs_for_session(conn, session_id)
    if not row:
        return
    meta = {}
    if row["metadata"]:
        try:
            meta = json.loads(row["metadata"]) or {}
        except Exception:
            meta = {}
    body = "\n".join(
        [
            t
            for t in [
                row["title"],
                str(meta.get("summary") or "").strip(),
                row["agent"] or "",
                row["workspace"] or "",
            ]
            if t
        ]
    )
    conn.execute(
        """
        INSERT INTO search_index(
            kind, workstream_id, session_id, entry_id, workstream_slug, workstream_title,
            session_title, body, tags, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "session",
            str(row["workstream_id"] or ""),
            str(session_id),
            "",
            row["workstream_slug"] or "",
            row["workstream_title"] or "",
            row["title"],
            body,
            _search_tags(row["tags"], row["workstream_tags"], row["workstream_slug"], row["workstream_title"]),
            row["created_at"],
        ),
    )


def _index_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    if not _ensure_search_index(conn):
        return
    row = conn.execute(
        """
        SELECT e.*, s.title AS session_title, s.tags AS session_tags, s.workstream_id,
               w.slug AS workstream_slug, w.title AS workstream_title, w.tags AS workstream_tags
        FROM entry e
        JOIN session s ON s.id = e.session_id
        LEFT JOIN workstream w ON w.id = s.workstream_id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()
    _delete_search_docs_for_entry(conn, entry_id)
    if not row:
        return
    content = row["content"] or ""
    extras = {}
    if row["extras"]:
        try:
            extras = json.loads(row["extras"]) or {}
        except Exception:
            extras = {"raw_extras": row["extras"]}
    extras_text = _entry_extras_search_text(extras)
    if _looks_like_ctx_noise(content):
        return
    body = "\n".join(
        [
            t
            for t in [
                row["type"],
                content,
                extras_text,
            ]
            if t
        ]
    )
    if not body.strip():
        return
    conn.execute(
        """
        INSERT INTO search_index(
            kind, workstream_id, session_id, entry_id, workstream_slug, workstream_title,
            session_title, body, tags, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "entry",
            str(row["workstream_id"] or ""),
            str(row["session_id"]),
            str(entry_id),
            row["workstream_slug"] or "",
            row["workstream_title"] or "",
            row["session_title"] or "",
            body,
            _search_tags(
                row["session_tags"],
                row["workstream_tags"],
                row["type"],
                row["workstream_slug"],
                row["workstream_title"],
                row["session_title"],
            ),
            row["created_at"],
        ),
    )


def _rebuild_search_index(conn: sqlite3.Connection) -> None:
    if not _ensure_search_index(conn):
        return
    conn.execute("DELETE FROM search_index")
    for row in conn.execute("SELECT id FROM workstream ORDER BY id").fetchall():
        _index_workstream(conn, int(row["id"]))
    for row in conn.execute("SELECT id FROM session ORDER BY id").fetchall():
        _index_session(conn, int(row["id"]))
    for row in conn.execute("SELECT id FROM entry ORDER BY id").fetchall():
        _index_entry(conn, int(row["id"]))


def _maybe_refresh_search_index(conn: sqlite3.Connection) -> None:
    if not _ensure_search_index(conn):
        return
    if not _table_exists(conn, "ctx_meta"):
        return
    row = conn.execute(
        "SELECT value FROM ctx_meta WHERE key = 'search_index_version'"
    ).fetchone()
    current_version = row["value"] if row else None
    try:
        doc_count = int(conn.execute("SELECT COUNT(*) AS n FROM search_index").fetchone()["n"])
    except Exception:
        doc_count = 0
    if current_version != SEARCH_INDEX_VERSION or doc_count == 0:
        try:
            _rebuild_search_index(conn)
            conn.execute(
                """
                INSERT INTO ctx_meta(key, value) VALUES ('search_index_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (SEARCH_INDEX_VERSION,),
            )
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower():
                raise


def _fts_tokens(query: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_./:-]+", query or "")


def _fts_query(tokens: list[str], operator: str = "AND") -> str:
    if not tokens:
        return ""
    joiner = f" {operator.strip().upper()} "
    return joiner.join(f'"{t}"' for t in tokens)


def _load_control_counts(conn: sqlite3.Connection, workstream_id: int) -> tuple[int, int]:
    rows = conn.execute(
        """
        SELECT e.extras
        FROM entry e
        JOIN session s ON s.id = e.session_id
        WHERE s.workstream_id = ?
        """,
        (workstream_id,),
    ).fetchall()
    pinned = 0
    excluded = 0
    for row in rows:
        mode = _entry_load_behavior(row)
        if mode == "pin":
            pinned += 1
        elif mode == "exclude":
            excluded += 1
    return pinned, excluded


def _pack_entry_groups(
    conn: sqlite3.Connection,
    workstream_id: int,
    session_ids: list[int],
    *,
    max_entries: int,
    focus: set[str] | None,
) -> tuple[list[sqlite3.Row], list[sqlite3.Row], int, int]:
    pinned_rows_all = conn.execute(
        """
        SELECT e.*, s.title AS session_title
        FROM entry e
        JOIN session s ON s.id = e.session_id
        WHERE s.workstream_id = ?
        ORDER BY e.id DESC
        """,
        (workstream_id,),
    ).fetchall()
    pinned_entries: list[sqlite3.Row] = []
    excluded_count = 0
    for row in pinned_rows_all:
        if focus and row["type"] not in focus:
            continue
        mode = _entry_load_behavior(row)
        if mode == "exclude":
            excluded_count += 1
            continue
        if mode == "pin":
            pinned_entries.append(row)

    recent_entries: list[sqlite3.Row] = []
    if session_ids:
        marks = ",".join("?" for _ in session_ids)
        rows = conn.execute(
            f"""
            SELECT e.*, s.title AS session_title
            FROM entry e
            JOIN session s ON s.id = e.session_id
            WHERE e.session_id IN ({marks})
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (*session_ids, max(max_entries * 10, 120)),
        ).fetchall()
        pinned_ids = {int(row["id"]) for row in pinned_entries}
        for row in rows:
            if focus and row["type"] not in focus:
                continue
            mode = _entry_load_behavior(row)
            if mode == "exclude":
                continue
            if int(row["id"]) in pinned_ids or mode == "pin":
                continue
            recent_entries.append(row)
            if len(recent_entries) >= max_entries:
                break

    return pinned_entries, recent_entries, len(pinned_entries), excluded_count


def _workstream_one_line_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    goal = row["title"]
    if row["metadata"]:
        try:
            meta = json.loads(row["metadata"]) or {}
            goal = meta.get("summary") or goal
        except Exception:
            pass
    if not goal and row["description"]:
        goal = row["description"]
    elif row["description"] and goal == row["title"]:
        goal = row["description"]
    goal = _preview_text(goal, limit=70) or row["title"]

    latest_session = conn.execute(
        "SELECT title FROM session WHERE workstream_id = ? ORDER BY id DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    latest_entries = conn.execute(
        "SELECT e.content, e.extras FROM entry e "
        "JOIN session s ON s.id = e.session_id "
        "WHERE s.workstream_id = ? ORDER BY e.id DESC LIMIT 20",
        (row["id"],),
    ).fetchall()

    latest_task = ""
    if latest_session and latest_session["title"] not in {"New session", "Auto-ingest session"}:
        latest_task = latest_session["title"]
    for latest_entry in latest_entries:
        if _entry_is_excluded_from_load(latest_entry):
            continue
        if latest_entry["content"] and not _looks_like_ctx_noise(latest_entry["content"]):
            latest_task = _preview_text(latest_entry["content"], limit=90) or latest_task
            break
    if not latest_task:
        for latest_entry in latest_entries:
            if _entry_is_excluded_from_load(latest_entry):
                continue
            if latest_entry["content"]:
                latest_task = _preview_text(latest_entry["content"], limit=90) or latest_task
                break
    if not latest_task and latest_session:
        latest_task = latest_session["title"]
    if not latest_task:
        latest_task = "No sessions yet"

    return f"goal: {goal} | latest: {_preview_text(latest_task, limit=90)}"


def _print_workstreams(rows: list[sqlite3.Row], conn: sqlite3.Connection):
    for r in rows:
        tags = f" [{r['tags']}]" if r["tags"] else ""
        ws = f" ({r['workspace']})" if r["workspace"] else ""
        summary = _workstream_one_line_summary(conn, r)
        print(f"{r['id']}: {r['slug']} - {r['title']}{tags}{ws} - {summary}")


def cmd_workstream_list(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    q = ["SELECT * FROM workstream WHERE 1=1"]
    params: list[object] = []
    if args.tag:
        q.append("AND (tags LIKE ? OR tags LIKE ? OR tags = ?)")
        t = args.tag
        params.extend([f"{t},%", f"%,{t}", t])
    if args.query:
        q.append("AND (slug LIKE ? OR title LIKE ? OR description LIKE ?)")
        like = f"%{args.query}%"
        params.extend([like, like, like])
    q.append("ORDER BY id DESC")
    sql = " ".join(q)
    with connect(db) as conn:
        rows = conn.execute(sql, params).fetchall()
        if args.format == "slugs":
            for r in rows:
                print(r["slug"])
        else:
            _print_workstreams(rows, conn)


def cmd_workstream_show(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    with connect(db) as conn:
        if args.slug:
            w = conn.execute("SELECT * FROM workstream WHERE slug = ?", (args.slug,)).fetchone()
        else:
            w = conn.execute("SELECT * FROM workstream WHERE id = ?", (args.id,)).fetchone()
        if not w:
            print("Workstream not found", file=sys.stderr)
            sys.exit(1)
        print(f"Workstream {w['id']}: {w['slug']} - {w['title']}")
        if w["description"]:
            print(f"  Description: {w['description']}")
        if w["tags"]:
            print(f"  Tags: {w['tags']}")
        if w["workspace"]:
            print(f"  Workspace: {w['workspace']}")
        print(f"  Created: {w['created_at']}")
        if w["metadata"]:
            try:
                meta = json.loads(w["metadata"]) or {}
                if meta.get("summary"):
                    print(f"  Summary: {meta['summary']}")
            except Exception:
                pass
        linked = _source_links_summary(conn, int(w["id"]))
        if linked:
            print(f"  External links: {linked}")
        print("-- Recent Sessions --")
        rows = conn.execute(
            """
            SELECT s.* FROM session s
            WHERE s.workstream_id = ? ORDER BY s.id DESC LIMIT 10
            """,
            (w["id"],),
        ).fetchall()
        _print_sessions(rows)


def cmd_pack(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    with connect(db) as conn:
        wid = _resolve_workstream_id(conn, slug=args.workstream_slug, wid=args.workstream_id)
        w = conn.execute("SELECT * FROM workstream WHERE id = ?", (wid,)).fetchone()
        if not w:
            print("Workstream not found", file=sys.stderr)
            sys.exit(1)
        # Gather sessions and entries
        sessions = conn.execute(
            "SELECT * FROM session WHERE workstream_id = ? ORDER BY id DESC LIMIT ?",
            (wid, args.max_sessions),
        ).fetchall()
        # Compile recent entries newest first across included sessions, while
        # honoring per-entry load controls. Pinned entries are gathered across
        # the full workstream so important older context can still load.
        session_ids = [s["id"] for s in sessions]
        focus = None
        if args.focus:
            focus = {t.strip() for t in args.focus.split(",") if t.strip()}
        pinned_entries, recent_entries, pinned_count, excluded_count = _pack_entry_groups(
            conn,
            int(wid),
            session_ids,
            max_entries=args.max_entries,
            focus=focus,
        )

    # Emit text or markdown
    if args.format == "markdown":
        lines = []
        lines.append(f"# Workstream: {w['slug']} — {w['title']}")
        if w["description"]:
            lines.append("")
            lines.append(w["description"])
        if w["workspace"] or w["tags"]:
            lines.append("")
            meta = []
            if w["workspace"]:
                meta.append(f"Workspace: `{w['workspace']}`")
            if w["tags"]:
                meta.append(f"Tags: `{w['tags']}`")
            lines.append(" | ".join(meta))
        if pinned_count or excluded_count:
            lines.append("")
            lines.append(f"Load controls: {pinned_count} pinned | {excluded_count} excluded")
        if pinned_entries:
            lines.append("")
            lines.append("## Pinned context")
            for e in pinned_entries:
                preview = (e["content"] or "").strip()
                if len(preview) > 500:
                    preview = preview[:497] + "..."
                lines.append(f"- E{e['id']} S{e['session_id']} `{_entry_display_label(e)}`:\n\n  {preview}")
        if not args.brief:
            lines.append("")
            lines.append("## Recent sessions")
            for s in sessions:
                lines.append(f"- S{s['id']}: {s['title']} (@{s['agent'] or 'n/a'}) [{s['tags'] or ''}] — {s['created_at']}")
            if recent_entries:
                lines.append("")
                title = "## Recent entries"
                if focus:
                    title += f" (types: {', '.join(sorted(focus))})"
                lines.append(title)
                for e in recent_entries:
                    preview = (e["content"] or "").strip()
                    if len(preview) > 500:
                        preview = preview[:497] + "..."
                    lines.append(f"- E{e['id']} S{e['session_id']} `{_entry_display_label(e)}`:\n\n  {preview}")
        print("\n".join(lines))
    else:
        lines = []
        lines.append(f"Workstream: {w['slug']} - {w['title']}")
        if w["workspace"]:
            lines.append(f"Workspace: {w['workspace']}")
        if w["tags"]:
            lines.append(f"Tags: {w['tags']}")
        if w["description"]:
            lines.append(f"Description: {w['description']}")
        if pinned_count or excluded_count:
            lines.append(f"Load controls: {pinned_count} pinned | {excluded_count} excluded")
        if pinned_entries:
            lines.append("")
            lines.append("Pinned context:")
            for e in pinned_entries:
                preview = (e["content"] or "").strip().replace("\n", " ")
                if len(preview) > 160:
                    preview = preview[:157] + "..."
                lines.append(f"- E{e['id']} S{e['session_id']} {_entry_display_label(e)}: {preview}")
        if not args.brief:
            lines.append("")
            lines.append("Recent sessions:")
            for s in sessions:
                lines.append(f"- S{s['id']}: {s['title']} @{s['agent'] or 'n/a'} [{s['tags'] or ''}] - {s['created_at']}")
            if recent_entries:
                lines.append("")
                lines.append("Recent entries:" + (f" (types: {', '.join(sorted(focus))})" if focus else ""))
                for e in recent_entries:
                    preview = (e["content"] or "").strip().replace("\n", " ")
                    if len(preview) > 160:
                        preview = preview[:157] + "..."
                    lines.append(f"- E{e['id']} S{e['session_id']} {_entry_display_label(e)}: {preview}")
        print("\n".join(lines))


def _read_stdin_if_dash(text_arg):
    if text_arg == "-":
        return sys.stdin.read()
    return text_arg


def _copy_attachment(session_id: int, entry_id: int, src_path: Path) -> str:
    # Store attachment under ~/.contextfun/attachments/<sid>/<eid>/<filename>
    dst_dir = _attach_dir() / str(session_id) / str(entry_id)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src_path.name
    shutil.copy2(src_path, dst)
    return str(dst)


def cmd_add(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    text = _read_stdin_if_dash(args.text)
    content = text
    extras: dict[str, object] = {}
    if args.from_file:
        p = Path(args.from_file)
        if not p.exists() or not p.is_file():
            print(f"File not found: {p}", file=sys.stderr)
            sys.exit(2)
        content = p.read_text(encoding="utf-8")
        extras["source_file"] = str(p.resolve())
    entry_type = args.type

    with connect(db) as conn:
        # Confirm session exists
        s = conn.execute("SELECT id FROM session WHERE id = ?", (args.session_id,)).fetchone()
        if not s:
            print(f"Session {args.session_id} not found", file=sys.stderr)
            sys.exit(1)

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO entry(session_id, type, content, extras, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                args.session_id,
                entry_type,
                content,
                json.dumps(extras) if extras else None,
                now_iso(),
            ),
        )
        eid = cur.lastrowid

        # Handle snapshot after we have eid to place the file
        if args.snapshot:
            sp = Path(args.snapshot)
            if not sp.exists() or not sp.is_file():
                print(f"Snapshot file not found: {sp}", file=sys.stderr)
                sys.exit(2)
            stored_path = _copy_attachment(args.session_id, eid, sp)
            # Update entry extras with attachment path
            ex = extras | {"attachment": stored_path}
            conn.execute(
                "UPDATE entry SET extras = ? WHERE id = ?",
                (json.dumps(ex), eid),
            )
        _index_entry(conn, int(eid))
        conn.commit()
    print(eid)


def cmd_search(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    with connect(db) as conn:
        tokens = _fts_tokens(args.query)
        fts_q = _fts_query(tokens, "AND")
        if _table_exists(conn, "search_index") and fts_q:
            def _fts_rows(match_q: str):
                return conn.execute(
                    """
                    SELECT
                        kind, workstream_id, session_id, entry_id, workstream_slug, workstream_title,
                        session_title, created_at,
                        snippet(search_index, 7, '[', ']', ' … ', 16) AS snippet,
                        bm25(search_index, 1.0, 0.0, 0.0, 0.0, 5.0, 4.0, 3.0, 1.0, 1.0, 0.0) AS score
                    FROM search_index
                    WHERE search_index MATCH ?
                    ORDER BY score ASC
                    LIMIT ?
                    """,
                    (match_q, max(args.limit * 4, 12)),
                ).fetchall()

            rows = _fts_rows(fts_q)
            search_mode = "strict"
            if not rows and len(tokens) > 1:
                loose_q = _fts_query(tokens, "OR")
                if loose_q and loose_q != fts_q:
                    rows = _fts_rows(loose_q)
                    if rows:
                        search_mode = "loose-or"
            if not rows:
                print("No matches")
                return
            kind_priority = {"entry": 0, "session": 1, "workstream": 2}
            grouped: dict[str, dict[str, object]] = {}
            for row in rows:
                wsid = str(row["workstream_id"] or "")
                g = grouped.setdefault(
                    wsid,
                    {
                        "score": float(row["score"]),
                        "hits": 0,
                        "slug": row["workstream_slug"] or "(unscoped)",
                        "title": row["workstream_title"] or "(no title)",
                        "snippet": row["snippet"] or "",
                        "kind": row["kind"],
                    },
                )
                g["hits"] = int(g["hits"]) + 1
                if float(row["score"]) < float(g["score"]):
                    g["score"] = float(row["score"])
                if row["snippet"] and (
                    not g["snippet"]
                    or kind_priority.get(str(row["kind"]), 99) < kind_priority.get(str(g["kind"]), 99)
                ):
                    g["snippet"] = row["snippet"]
                    g["kind"] = row["kind"]

            if search_mode == "loose-or":
                print("Search mode: loose OR fallback")
                print("")
            print("Top workstreams:")
            top_groups = sorted(grouped.items(), key=lambda item: (float(item[1]["score"]), -int(item[1]["hits"])))[: args.limit]
            for wsid, info in top_groups:
                summary = ""
                if wsid:
                    ws_row = conn.execute("SELECT * FROM workstream WHERE id = ?", (int(wsid),)).fetchone()
                    if ws_row:
                        summary = _workstream_one_line_summary(conn, ws_row)
                line = f"- {info['slug']} — {summary or info['title']}"
                line += f" | hits: {info['hits']}"
                print(line)
                if info["snippet"]:
                    print(f"  best: {info['snippet']}")

            print("")
            print("Top matches:")
            display_rows = sorted(
                rows,
                key=lambda row: (kind_priority.get(str(row["kind"]), 99), float(row["score"])),
            )[: args.limit]
            for row in display_rows:
                session_part = f"S{row['session_id']} " if row["session_id"] else ""
                entry_part = f"E{row['entry_id']} " if row["entry_id"] else ""
                print(
                    f"- {row['workstream_slug'] or '(unscoped)'} / {session_part}{entry_part}{row['kind']} @ {row['created_at']}"
                )
                if row["snippet"]:
                    print(f"  {row['snippet']}")
            return

        q = (
            "SELECT e.id as entry_id, s.id as session_id, s.title, e.type, e.created_at "
            "FROM entry e JOIN session s ON s.id = e.session_id "
            "WHERE (e.content LIKE ? OR s.title LIKE ?) "
            "ORDER BY e.id DESC LIMIT ?"
        )
        like = f"%{args.query}%"
        rows = conn.execute(q, (like, like, args.limit)).fetchall()
    for r in rows:
        print(f"[E{r['entry_id']}] S{r['session_id']}: {r['title']} ({r['type']}) - {r['created_at']}")


def cmd_export(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    payload: dict[str, object] = {"exported_at": now_iso(), "sessions": []}
    with connect(db) as conn:
        if args.session_id:
            session_rows = conn.execute(
                "SELECT * FROM session WHERE id = ?", (args.session_id,)
            ).fetchall()
        else:
            session_rows = conn.execute("SELECT * FROM session").fetchall()

        for s in session_rows:
            entries = conn.execute(
                "SELECT * FROM entry WHERE session_id = ? ORDER BY id ASC",
                (s["id"],),
            ).fetchall()
            payload["sessions"].append(
                {
                    "session": dict(s),
                    "entries": [dict(e) for e in entries],
                }
            )

    data = json.dumps(payload, indent=2)
    if args.out and args.out != "-":
        Path(args.out).write_text(data, encoding="utf-8")
    else:
        print(data)


def cmd_import(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    if args.file and args.file != "-":
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        sys.exit(2)

    count_sessions = 0
    count_entries = 0
    with connect(db) as conn:
        cur = conn.cursor()
        for block in payload.get("sessions", []):
            s = block.get("session", {})
            entries = block.get("entries", [])
            cur.execute(
                """
                INSERT INTO session(id, title, agent, tags, workspace, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    s.get("id"),
                    s.get("title"),
                    s.get("agent"),
                    s.get("tags"),
                    s.get("workspace"),
                    s.get("created_at") or now_iso(),
                    s.get("metadata"),
                ),
            )
            # If id is not provided, fetch last insert id
            sid = s.get("id") or cur.lastrowid
            count_sessions += 1
            for e in entries:
                cur.execute(
                    """
                    INSERT INTO entry(id, session_id, type, content, extras, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (
                        e.get("id"),
                        sid,
                        e.get("type") or "note",
                        e.get("content"),
                        e.get("extras"),
                        e.get("created_at") or now_iso(),
                    ),
                )
                count_entries += 1
        _rebuild_search_index(conn)
        conn.commit()
    print(f"Imported {count_sessions} sessions, {count_entries} entries")


def _ensure_session_for_ingest(conn: sqlite3.Connection, workstream_slug=None, workstream_id=None, session_id=None, agent_hint=None) -> int:
    # Prefer explicit session_id
    if session_id:
        row = conn.execute("SELECT id FROM session WHERE id = ?", (session_id,)).fetchone()
        if row:
            return int(row["id"])
        print(f"Session {session_id} not found", file=sys.stderr)
        sys.exit(1)
    # Resolve workstream
    if not (workstream_slug or workstream_id):
        cur = _get_current_workstream()
        if not cur:
            print("No current workstream set; provide --workstream-slug/--workstream-id or set current.", file=sys.stderr)
            sys.exit(2)
        workstream_id = cur.get("id")
    wid = _resolve_workstream_id(conn, slug=workstream_slug, wid=workstream_id)
    # Use latest session if exists
    row = conn.execute(
        "SELECT id FROM session WHERE workstream_id = ? ORDER BY id DESC LIMIT 1",
        (wid,),
    ).fetchone()
    if row:
        return int(row["id"])
    # Otherwise create a new session placeholder
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO session(workstream_id, title, agent, tags, workspace, created_at, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            wid,
            "Auto-ingest session",
            agent_hint or "other",
            None,
            None,
            now_iso(),
            json.dumps({"summary": "Created by ingest"}),
        ),
    )
    sid = cur.lastrowid
    _index_session(conn, int(sid))
    conn.commit()
    return sid


def _chunk_text(s: str, limit: int = 4000):
    s = s or ""
    if len(s) <= limit:
        return [s]
    out = []
    start = 0
    while start < len(s):
        out.append(s[start : start + limit])
        start += limit
    return out


def cmd_ingest(args: argparse.Namespace):
    db = Path(args.db)
    init_db(db, quiet=True)
    # Read input
    if args.file and args.file != "-":
        raw = Path(args.file).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()

    fmt = (args.format or "auto").lower()
    entries_to_add = []  # list of dict(type, content, extras)
    extras_common = {"source": args.source} if args.source else {}

    def add_note(content, role=None):
        ex = dict(extras_common)
        if role:
            ex["role"] = role
        entries_to_add.append({"type": "note", "content": content, "extras": ex})

    # Decide format
    if fmt == "json" or (fmt == "auto" and raw.strip().startswith("{")):
        try:
            obj = json.loads(raw)
        except Exception:
            # fall back to text
            obj = None
        if isinstance(obj, dict):
            messages = None
            # Try common shapes
            if isinstance(obj.get("messages"), list):
                messages = obj["messages"]
            elif isinstance(obj.get("chat"), list):
                messages = obj["chat"]
            elif isinstance(obj.get("conversations"), list):
                messages = obj["conversations"]
            if messages:
                for m in messages:
                    role = m.get("role") or m.get("sender") or None
                    content = m.get("content") or m.get("text") or ""
                    # If content is a list of blocks
                    if isinstance(content, list):
                        # concatenate text-like parts
                        text_parts = []
                        for b in content:
                            if isinstance(b, str):
                                text_parts.append(b)
                            elif isinstance(b, dict):
                                val = b.get("text") or b.get("content") or ""
                                if isinstance(val, str):
                                    text_parts.append(val)
                        content = "\n".join([t for t in text_parts if t])
                    if not isinstance(content, str):
                        content = str(content)
                    if content:
                        # Chunk long content
                        for chunk in _chunk_text(content, limit=args.chunk):
                            add_note(chunk, role=role)
            else:
                # Unknown JSON; store as a single note
                add_note(json.dumps(obj, indent=2))
        else:
            # Not an object; just store text
            for chunk in _chunk_text(raw, limit=args.chunk):
                add_note(chunk)
    else:
        # Treat as text/markdown; optionally try to split by "User:" markers
        text = raw
        if fmt == "markdown" or fmt == "auto":
            # Simple heuristic split for transcripts like "User:" / "Assistant:"
            lines = text.splitlines()
            buf = []
            role = None
            def flush():
                if buf:
                    content = "\n".join(buf).strip()
                    if content:
                        for chunk in _chunk_text(content, limit=args.chunk):
                            add_note(chunk, role=role)
            for ln in lines:
                if ln.strip().lower().startswith("user:"):
                    flush(); buf = []; role = "user"; ln = ln.split(":",1)[1]
                elif ln.strip().lower().startswith("assistant:"):
                    flush(); buf = []; role = "assistant"; ln = ln.split(":",1)[1]
                buf.append(ln)
            flush()
            if entries_to_add:
                pass
            else:
                for chunk in _chunk_text(text, limit=args.chunk):
                    add_note(chunk)
        else:
            for chunk in _chunk_text(text, limit=args.chunk):
                add_note(chunk)

    # Insert entries
    with connect(db) as conn:
        sid = _ensure_session_for_ingest(
            conn,
            workstream_slug=args.workstream_slug,
            workstream_id=args.workstream_id,
            session_id=args.session_id,
            agent_hint=args.agent,
        )
        cur = conn.cursor()
        count = 0
        for item in entries_to_add:
            cur.execute(
                """
                INSERT INTO entry(session_id, type, content, extras, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    sid,
                    item["type"],
                    item["content"],
                    json.dumps(item.get("extras")) if item.get("extras") else None,
                    now_iso(),
                ),
            )
            _index_entry(conn, int(cur.lastrowid))
            count += 1
        conn.commit()
    print(f"Ingested {count} chunks into session {sid}")


def add_common_args(parser: argparse.ArgumentParser, *, use_default: bool = False):
    kwargs = {
        "help": f"Path to SQLite DB (default: {DEFAULT_DB})",
    }
    if use_default:
        kwargs["default"] = str(DEFAULT_DB)
    else:
        # Preserve a previously parsed top-level --db instead of overwriting it
        # with the subcommand default.
        kwargs["default"] = argparse.SUPPRESS
    parser.add_argument("--db", **kwargs)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="contextfun",
        description=(
            "Store and retrieve context from coding agent sessions (Codex, Claude, etc.)."
        ),
    )
    add_common_args(p, use_default=True)
    sp = p.add_subparsers(dest="cmd", required=True)

    # init
    p_init = sp.add_parser("init", help="Initialize the database")
    add_common_args(p_init)
    p_init.set_defaults(func=cmd_init)

    # workstream: set-current
    p_w_set = sp.add_parser("workstream-set-current", help="Set current workstream by slug or id")
    add_common_args(p_w_set)
    gidset = p_w_set.add_mutually_exclusive_group(required=True)
    gidset.add_argument("--slug", help="Workstream slug")
    gidset.add_argument("--id", type=int, help="Workstream id")
    def _cmd_ws_set(args: argparse.Namespace):
        init_db(Path(args.db), quiet=True)
        with connect(Path(args.db)) as conn:
            data = _set_current_workstream(conn, slug=args.slug, wid=args.id)
        print(f"Current workstream set: {data['slug']} (id {data['id']})")
    p_w_set.set_defaults(func=_cmd_ws_set)

    # workstream: current
    p_w_cur = sp.add_parser("workstream-current", help="Show current workstream if set")
    add_common_args(p_w_cur)
    def _cmd_ws_cur(args: argparse.Namespace):
        init_db(Path(args.db), quiet=True)
        cur = _get_current_workstream()
        if not cur:
            print("No current workstream set")
            return
        print(f"Current workstream: {cur.get('slug')} (id {cur.get('id')}) - {cur.get('title')}")
    p_w_cur.set_defaults(func=_cmd_ws_cur)

    # workstream new
    p_w_new = sp.add_parser("workstream-new", help="Create a new workstream")
    add_common_args(p_w_new)
    p_w_new.add_argument("slug", help="Stable identifier, e.g. 'proj-auth-refactor'")
    p_w_new.add_argument("title", help="Human-friendly title")
    p_w_new.add_argument("--description", help="Optional description")
    p_w_new.add_argument("--tags", help="Comma-separated tags", default="")
    p_w_new.add_argument("--workspace", help="Workspace root path", default="")
    p_w_new.add_argument("--summary", help="Optional summary/goal")
    p_w_new.set_defaults(func=cmd_workstream_new)

    # workstream list
    p_w_list = sp.add_parser("workstream-list", help="List workstreams")
    add_common_args(p_w_list)
    p_w_list.add_argument("--tag", help="Filter by tag")
    p_w_list.add_argument("--query", help="Search slug/title/description")
    p_w_list.add_argument("--format", choices=["plain", "slugs"], default="plain")
    p_w_list.set_defaults(func=cmd_workstream_list)

    # workstream show
    p_w_show = sp.add_parser("workstream-show", help="Show a workstream and recent sessions")
    add_common_args(p_w_show)
    gid = p_w_show.add_mutually_exclusive_group(required=True)
    gid.add_argument("--slug", help="Workstream slug")
    gid.add_argument("--id", type=int, help="Workstream id")
    p_w_show.set_defaults(func=cmd_workstream_show)

    # workstream ensure
    p_w_ens = sp.add_parser("workstream-ensure", help="Ensure a workstream exists (create if missing)")
    add_common_args(p_w_ens)
    p_w_ens.add_argument("name", help="Human-friendly name; used as title")
    p_w_ens.add_argument("--slug", help="Optional explicit slug; otherwise derived")
    p_w_ens.add_argument("--workspace", help="Optional workspace path")
    p_w_ens.add_argument("--set-current", action="store_true", help="Set as current workstream")
    p_w_ens.add_argument("--unique-if-exists", action="store_true", help="If the requested name exists, create a suffixed new workstream instead")
    p_w_ens.add_argument("--json", action="store_true", help="Output JSON result")
    p_w_ens.set_defaults(func=cmd_workstream_ensure)

    p_w_ren = sp.add_parser("workstream-rename", help="Rename a workstream by slug or title")
    add_common_args(p_w_ren)
    p_w_ren.add_argument("ref", help="Existing workstream slug or title")
    p_w_ren.add_argument("new_name", help="New human-friendly name")
    p_w_ren.add_argument("--json", action="store_true", help="Output JSON result")
    p_w_ren.set_defaults(func=cmd_workstream_rename)

    # session new
    p_s_new = sp.add_parser("session-new", help="Create a new session")
    add_common_args(p_s_new)
    p_s_new.add_argument("title", help="Short title for this session")
    p_s_new.add_argument(
        "--agent",
        choices=["codex", "claude", "openai", "other"],
        default="other",
        help="Agent type (for filtering)",
    )
    p_s_new.add_argument("--tags", help="Comma-separated tags", default="")
    p_s_new.add_argument(
        "--workspace",
        help="Optional workspace path (repo/project) for reference",
        default="",
    )
    p_s_new.add_argument("--summary", help="Optional summary/goal for the session")
    g_ws_snew = p_s_new.add_argument_group("workstream linkage")
    g_ws_snew.add_argument("--workstream-slug", help="Attach to a workstream by slug")
    g_ws_snew.add_argument("--workstream-id", type=int, help="Attach to a workstream by id")
    p_s_new.set_defaults(func=cmd_session_new)

    # session list
    p_s_list = sp.add_parser("session-list", help="List sessions")
    add_common_args(p_s_list)
    p_s_list.add_argument("--agent", help="Filter by agent")
    p_s_list.add_argument("--tag", help="Filter by tag")
    p_s_list.add_argument("--query", help="Search title substring")
    p_s_list.add_argument("--workstream-slug", help="Filter by workstream slug")
    p_s_list.set_defaults(func=cmd_session_list)

    # session show
    p_s_show = sp.add_parser("session-show", help="Show session details and entries")
    add_common_args(p_s_show)
    p_s_show.add_argument("id", type=int, help="Session id")
    p_s_show.set_defaults(func=cmd_session_show)

    # session delete
    p_s_del = sp.add_parser("session-delete", help="Delete a session by id")
    add_common_args(p_s_del)
    p_s_del.add_argument("id", type=int, help="Session id")
    p_s_del.set_defaults(func=cmd_session_delete)

    # entry load behavior
    p_e_load = sp.add_parser("entry-load", help="Set whether an entry is loaded by future packs")
    add_common_args(p_e_load)
    p_e_load.add_argument("id", type=int, help="Entry id")
    p_e_load.add_argument("mode", choices=["default", "pin", "exclude"], help="Load behavior")
    p_e_load.set_defaults(func=cmd_entry_load)

    # entry delete
    p_e_del = sp.add_parser("entry-delete", help="Delete a single entry by id")
    add_common_args(p_e_del)
    p_e_del.add_argument("id", type=int, help="Entry id")
    p_e_del.set_defaults(func=cmd_entry_delete)

    # add entry
    p_add = sp.add_parser("add", help="Add an entry to a session")
    add_common_args(p_add)
    p_add.add_argument("session_id", type=int, help="Target session id")
    p_add.add_argument(
        "--type",
        choices=["note", "cmd", "file", "link", "decision", "todo"],
        default="note",
        help="Entry type",
    )
    p_add.add_argument(
        "--text",
        help="Text content (use '-' to read from stdin)",
    )
    p_add.add_argument(
        "--from-file",
        help="Read content from a file path",
    )
    p_add.add_argument(
        "--snapshot",
        help="Also copy the given file into attachments and link it",
    )
    p_add.set_defaults(func=cmd_add)

    # add-latest (targets latest session in a workstream or current workstream)
    p_addl = sp.add_parser(
        "add-latest",
        help="Add an entry to the latest session in a workstream (or current)",
    )
    add_common_args(p_addl)
    g_addl = p_addl.add_mutually_exclusive_group()
    g_addl.add_argument("--workstream-slug", help="Workstream slug")
    g_addl.add_argument("--workstream-id", type=int, help="Workstream id")
    p_addl.add_argument(
        "--type",
        choices=["note", "cmd", "file", "link", "decision", "todo"],
        default="note",
        help="Entry type",
    )
    p_addl.add_argument("--text", help="Text content (use '-' to read from stdin)")
    p_addl.add_argument("--from-file", help="Read content from a file path")
    p_addl.add_argument("--snapshot", help="Copy file into attachments and link it")
    def _cmd_add_latest(args: argparse.Namespace):
        db = Path(args.db)
        init_db(db, quiet=True)
        with connect(db) as conn:
            if args.workstream_slug or args.workstream_id:
                wid = _resolve_workstream_id(conn, slug=args.workstream_slug, wid=args.workstream_id)
            else:
                cur = _get_current_workstream()
                if not cur:
                    print("No current workstream set; provide --workstream-slug or --workstream-id", file=sys.stderr)
                    sys.exit(2)
                wid = cur.get("id")
            row = conn.execute(
                "SELECT id FROM session WHERE workstream_id = ? ORDER BY id DESC LIMIT 1",
                (wid,),
            ).fetchone()
            if not row:
                print("No sessions yet in this workstream", file=sys.stderr)
                sys.exit(1)
            sess_id = int(row["id"])
        # Reuse cmd_add by constructing a namespace
        ns = argparse.Namespace(
            db=args.db,
            session_id=sess_id,
            type=args.type,
            text=args.text,
            from_file=args.from_file,
            snapshot=args.snapshot,
        )
        cmd_add(ns)
    p_addl.set_defaults(func=_cmd_add_latest)

    # session-latest (lookup helper)
    p_sl = sp.add_parser("session-latest", help="Get latest session id for a workstream (or current)")
    add_common_args(p_sl)
    g_sl = p_sl.add_mutually_exclusive_group()
    g_sl.add_argument("--workstream-slug", help="Workstream slug")
    g_sl.add_argument("--workstream-id", type=int, help="Workstream id")
    def _cmd_session_latest(args: argparse.Namespace):
        db = Path(args.db)
        init_db(db, quiet=True)
        with connect(db) as conn:
            if args.workstream_slug or args.workstream_id:
                wid = _resolve_workstream_id(conn, slug=args.workstream_slug, wid=args.workstream_id)
            else:
                cur = _get_current_workstream()
                if not cur:
                    print("No current workstream set; provide --workstream-slug or --workstream-id", file=sys.stderr)
                    sys.exit(2)
                wid = cur.get("id")
            row = conn.execute(
                "SELECT id FROM session WHERE workstream_id = ? ORDER BY id DESC LIMIT 1",
                (wid,),
            ).fetchone()
            if not row:
                print("No sessions yet in this workstream", file=sys.stderr)
                sys.exit(1)
            print(int(row["id"]))
    p_sl.set_defaults(func=_cmd_session_latest)

    # search
    p_search = sp.add_parser("search", help="Search workstreams, sessions, and entries")
    add_common_args(p_search)
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--limit", type=int, default=8, help="Max grouped results to show")
    p_search.set_defaults(func=cmd_search)

    # export
    p_export = sp.add_parser("export", help="Export sessions and entries to JSON")
    add_common_args(p_export)
    p_export.add_argument("--session-id", type=int, help="Export only this session")
    p_export.add_argument(
        "--out",
        default="-",
        help="Output file path or '-' for stdout",
    )
    p_export.set_defaults(func=cmd_export)

    # import
    p_import = sp.add_parser("import", help="Import sessions and entries from JSON")
    add_common_args(p_import)
    p_import.add_argument("--file", default="-", help="File path or '-' for stdin")
    p_import.set_defaults(func=cmd_import)

    # ingest (auto-capture transcripts or text)
    p_ing = sp.add_parser("ingest", help="Ingest a transcript or text into a session/workstream")
    add_common_args(p_ing)
    g_ing_ws = p_ing.add_mutually_exclusive_group()
    g_ing_ws.add_argument("--workstream-slug", help="Workstream slug (defaults to current if omitted)")
    g_ing_ws.add_argument("--workstream-id", type=int, help="Workstream id")
    p_ing.add_argument("--session-id", type=int, help="Explicit session id (otherwise latest or auto-created)")
    p_ing.add_argument("--file", default="-", help="File path or '-' for stdin")
    p_ing.add_argument("--format", choices=["auto", "text", "markdown", "json"], default="auto")
    p_ing.add_argument("--source", help="Optional source label (e.g., claude, codex, openai)")
    p_ing.add_argument("--agent", help="Agent hint if a new session must be created")
    p_ing.add_argument("--chunk", type=int, default=4000, help="Chunk size for long text")
    p_ing.set_defaults(func=cmd_ingest)

    # pack
    p_pack = sp.add_parser("pack", help="Emit a compact context pack for a workstream")
    add_common_args(p_pack)
    g_ws = p_pack.add_mutually_exclusive_group(required=True)
    g_ws.add_argument("--workstream-slug", help="Workstream slug")
    g_ws.add_argument("--workstream-id", type=int, help="Workstream id")
    p_pack.add_argument("--max-sessions", type=int, default=5, help="Max sessions to include")
    p_pack.add_argument("--max-entries", type=int, default=50, help="Max entries across sessions")
    p_pack.add_argument("--focus", help="Comma-separated entry types to include (e.g., decision,todo)")
    p_pack.add_argument("--format", choices=["text", "markdown"], default="text", help="Output format")
    p_pack.add_argument("--brief", action="store_true", help="Omit session and entry details for a minimal header")
    p_pack.set_defaults(func=cmd_pack)

    # resume (wrapper over pack with a short preamble)
    p_resume = sp.add_parser(
        "resume",
        help="Emit a ready-to-paste preamble + pack to resume a workstream",
    )
    add_common_args(p_resume)
    g_rs = p_resume.add_mutually_exclusive_group()
    g_rs.add_argument("--workstream-slug", help="Workstream slug (defaults to current if omitted)")
    g_rs.add_argument("--workstream-id", type=int, help="Workstream id")
    p_resume.add_argument("--focus", help="Comma-separated entry types (e.g., decision,todo)")
    p_resume.add_argument("--format", choices=["text", "markdown"], default="markdown")
    p_resume.add_argument("--brief", action="store_true", help="Header only with no details")
    p_resume.add_argument("--max-sessions", type=int, default=5, help="Max sessions to include")
    p_resume.add_argument("--max-entries", type=int, default=50, help="Max entries across sessions")
    def _cmd_resume(args: argparse.Namespace):
        db = Path(args.db)
        init_db(db, quiet=True)
        with connect(db) as conn:
            if args.workstream_slug or args.workstream_id:
                wid = _resolve_workstream_id(conn, slug=args.workstream_slug, wid=args.workstream_id)
            else:
                cur = _get_current_workstream()
                if not cur:
                    print("No current workstream set; provide --workstream-slug or --workstream-id", file=sys.stderr)
                    sys.exit(2)
                wid = cur.get("id")
            w = conn.execute("SELECT slug, title FROM workstream WHERE id = ?", (wid,)).fetchone()
            if not w:
                print("Workstream not found", file=sys.stderr)
                sys.exit(1)
            preamble = (
                "You are joining an ongoing workstream. The following pack includes recent sessions and entries. Read the pack and ask any clarifying questions before proceeding.\n\n"
            )
        # Reuse pack with same args
        pack_args = argparse.Namespace(
            db=args.db,
            workstream_slug=args.workstream_slug or (None if args.workstream_id else w["slug"]),
            workstream_id=args.workstream_id,
            max_sessions=args.max_sessions,
            max_entries=args.max_entries,
            focus=args.focus,
            format=args.format,
            brief=args.brief,
        )
        # Capture pack output by temporarily redirecting stdout
        from io import StringIO
        import contextlib

        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_pack(pack_args)
        pack_text = buf.getvalue()
        if args.format == "markdown":
            print(preamble + pack_text)
        else:
            print(preamble + pack_text)
    p_resume.set_defaults(func=_cmd_resume)

    # web frontend
    p_web = sp.add_parser("web", help="Serve the local ctx browser frontend")
    add_common_args(p_web)
    p_web.add_argument("--host", default="127.0.0.1", help="Host to bind")
    p_web.add_argument("--port", type=int, default=4310, help="Port to bind")
    p_web.add_argument("--open", action="store_true", help="Open the browser after starting")
    def _cmd_web(args: argparse.Namespace):
        from .web import run_server

        db = Path(args.db)
        ensure_home(db.parent)
        os.environ["CONTEXTFUN_DB"] = str(db.resolve())
        run_server(db, host=args.host, port=args.port, open_browser_flag=args.open)
    p_web.set_defaults(func=_cmd_web)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    # Ensure home dirs
    ensure_home(Path(args.db).parent)
    args.func(args)


if __name__ == "__main__":
    main()
