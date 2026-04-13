#!/usr/bin/env python3
import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
import shutil
import json
import re
from typing import List, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextfun.cli import (
    _attach_dir,
    _current_workspace_path as _ctx_current_workspace_path,
    _effective_workspace_for_workstream,
    _index_entry,
    _index_session,
    _index_workstream,
    _workspace_relation,
    now_iso,
)

LIB = ROOT / "lib"


def run_ctx(args_list, input_data=None):
    cmd = ["python3", "-m", "contextfun"]
    db = os.getenv("CONTEXTFUN_DB")
    if db:
        cmd += ["--db", db]
    cmd += args_list
    try:
        env = os.environ.copy()
        # Ensure our installed lib path is visible to Python
        if LIB.exists():
            env["PYTHONPATH"] = (
                (str(LIB) + os.pathsep + env.get("PYTHONPATH", "")) if env.get("PYTHONPATH") else str(LIB)
            )
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            env=env,
            input=(input_data.encode() if isinstance(input_data, str) else None),
        )
        return out.decode()
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.output.decode())
        sys.exit(e.returncode)


def run_ctx_passthrough(args_list):
    cmd = ["python3", "-m", "contextfun"]
    db = os.getenv("CONTEXTFUN_DB")
    if db:
        cmd += ["--db", db]
    cmd += args_list
    env = os.environ.copy()
    if LIB.exists():
        env["PYTHONPATH"] = (
            (str(LIB) + os.pathsep + env.get("PYTHONPATH", "")) if env.get("PYTHONPATH") else str(LIB)
        )
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def _invocation_workspace() -> str:
    try:
        return _ctx_current_workspace_path()
    except Exception:
        try:
            return str(Path.cwd().resolve())
        except Exception:
            return str(Path.cwd())


def ensure_workstream(name, set_current=False, unique_if_exists=False):
    args = ["workstream-ensure", name]
    workspace = _invocation_workspace()
    if workspace:
        args += ["--workspace", workspace]
    if set_current:
        args.append("--set-current")
    if unique_if_exists:
        args.append("--unique-if-exists")
    args.append("--json")
    out = run_ctx(args)
    import json

    return json.loads(out)


def rename_workstream(ref: str, new_name: str):
    out = run_ctx(["workstream-rename", ref, new_name, "--json"])
    return json.loads(out)


def create_session(agent=None, title: str = "New session"):
    args = ["session-new", title]
    workspace = _invocation_workspace()
    if workspace:
        args += ["--workspace", workspace]
    if agent:
        args += ["--agent", agent]
    return int(run_ctx(args).strip())


def pack(slug, focus=None, fmt="markdown", brief=False, max_sessions: Optional[int] = None, max_entries: Optional[int] = None):
    args = ["resume", "--workstream-slug", slug, "--format", fmt]
    if focus:
        args += ["--focus", focus]
    if brief:
        args.append("--brief")
    if max_sessions is not None:
        args += ["--max-sessions", str(max_sessions)]
    if max_entries is not None:
        args += ["--max-entries", str(max_entries)]
    return run_ctx(args)


def workstream_pack(
    slug,
    focus=None,
    fmt="markdown",
    brief=False,
    max_sessions: Optional[int] = None,
    max_entries: Optional[int] = None,
):
    args = ["pack", "--workstream-slug", slug, "--format", fmt]
    if focus:
        args += ["--focus", focus]
    if brief:
        args.append("--brief")
    if max_sessions is not None:
        args += ["--max-sessions", str(max_sessions)]
    if max_entries is not None:
        args += ["--max-entries", str(max_entries)]
    return run_ctx(args)


def _json_loads_safe(raw: Optional[str]) -> Dict[str, object]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _preview_text(text: Optional[str], limit: int = 140) -> str:
    value = (text or "").strip().replace("\n", " ")
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _entry_load_behavior(row: sqlite3.Row) -> str:
    extras = _json_loads_safe(row["extras"]) if "extras" in row.keys() else {}
    mode = str(extras.get("load_behavior") or "default").strip().lower()
    return mode if mode in {"default", "pin", "exclude"} else "default"


def _entry_role(row: sqlite3.Row) -> str:
    extras = _json_loads_safe(row["extras"]) if "extras" in row.keys() else {}
    return str(extras.get("role") or "").strip().lower()


def _looks_like_ctx_noise(text: Optional[str]) -> bool:
    value = " ".join((text or "").strip().split()).lower()
    if not value:
        return True
    noise_markers = (
        "base directory for this skill:",
        "launching skill:",
        "args from unknown skill:",
        "unknown skill:",
        "claude code v",
        "<local-command-caveat>",
        "<command-message>",
        "<command-name>",
        "<command-args>",
        "# agents.md instructions for ",
        "<environment_context>",
        "supported chat-style commands in this repo:",
        "using the `ctx-",
        "running `ctx ",
        "resumed `",
        "## ctx loaded:",
        "contextfun agent guide",
        "[exec_command] {\"cmd\":\"ctx ",
        "[exec_command] {\"cmd\":\"bash ~/.codex/skills/ctx-",
        "[exec_command] {\"cmd\":\"python3 scripts/ctx_cmd.py",
        "tip: press tab to queue a message when a task is running",
        "openai codex (v",
        "[rerun:",
    )
    if any(marker in value for marker in noise_markers):
        return True
    if value in {"no files found", "claude transcript line", "codex transcript line"}:
        return True
    if value.startswith("[image source:"):
        return True
    if "exceeds maximum allowed tokens" in value:
        return True
    if any(cmd in value for cmd in ("ctx start ", "ctx resume ", "ctx list", "ctx search ", "ctx delete ", "ctx branch ")):
        if len(value) < 220:
            return True
    if value.startswith("ctx ") and len(value) < 120:
        return True
    if "name: ctx-" in value:
        return True
    if value.startswith("davidchu@") and "% codex" in value:
        return True
    return False


def _load_char_budget() -> int:
    raw = os.getenv("CTX_LOAD_CHAR_BUDGET", "24000")
    try:
        return max(4000, int(raw))
    except Exception:
        return 24000


def _should_compress(explicit: bool, disabled: bool) -> bool:
    if explicit and disabled:
        print("Choose only one of --compress or --no-compress", file=sys.stderr)
        sys.exit(2)
    if explicit:
        return True
    if disabled:
        return False
    raw = str(os.getenv("CTX_COMPRESS_DEFAULT", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _db_path() -> Path:
    env_db = os.getenv("CONTEXTFUN_DB")
    if env_db:
        return Path(os.path.expanduser(env_db)).resolve()
    return (ROOT / ".contextfun" / "context.db").resolve()


def lookup_workstream(name: str) -> Optional[Dict[str, object]]:
    db = _db_path()
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, slug, title FROM workstream WHERE slug = ? OR title = ? ORDER BY id DESC LIMIT 1",
            (name, name),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"id": int(row["id"]), "slug": row["slug"], "title": row["title"]}


def require_workstream(name: str, *, set_current: bool = False) -> Dict[str, object]:
    ws = lookup_workstream(name)
    if not ws:
        print(
            f"No workstream matching '{name}' exists.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if set_current:
        run_ctx(["workstream-set-current", "--slug", str(ws["slug"])])
        cur = current_workstream()
        if cur:
            ws = cur
    return ws


def current_workstream() -> Optional[Dict[str, object]]:
    home = _db_path().parent
    slot = os.getenv("CTX_AGENT_SLOT") or os.getenv("CTX_AGENT_KEY")
    if slot:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(slot)).strip("-")
        cur_file = home / f"current.{safe}.json"
    else:
        cur_file = home / "current.json"
    if not cur_file.exists():
        return None
    try:
        cur = json.loads(cur_file.read_text(encoding="utf-8"))
        return {"id": int(cur["id"]), "slug": cur["slug"], "title": cur.get("title", cur["slug"])}
    except Exception:
        return None


def _connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def _copy_branch_attachment(extras: Dict[str, object], new_session_id: int, new_entry_id: int) -> Dict[str, object]:
    attachment = extras.get("attachment")
    if not attachment:
        return extras
    src = Path(str(attachment))
    if not src.exists() or not src.is_file():
        return extras
    dst_dir = _attach_dir() / str(new_session_id) / str(new_entry_id)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    shutil.copy2(src, dst)
    updated = dict(extras)
    updated["attachment"] = str(dst)
    return updated


def _clone_workstream_snapshot(
    source_workstream: Dict[str, object],
    target_workstream: Dict[str, object],
    *,
    default_agent: Optional[str],
) -> int:
    source_id = int(source_workstream["id"])
    target_id = int(target_workstream["id"])
    latest_new_session_id: Optional[int] = None

    with _connect_db() as conn:
        source_row = conn.execute("SELECT * FROM workstream WHERE id = ?", (source_id,)).fetchone()
        target_row = conn.execute("SELECT * FROM workstream WHERE id = ?", (target_id,)).fetchone()
        if not source_row or not target_row:
            raise SystemExit("Branch clone failed: workstream not found")

        source_meta = _json_loads_safe(source_row["metadata"])
        target_meta = _json_loads_safe(target_row["metadata"])
        target_meta["branch_from"] = {
            "id": source_id,
            "slug": source_row["slug"],
            "title": source_row["title"],
            "branched_at": now_iso(),
        }
        source_summary = (
            str(source_row["description"] or "").strip()
            or str(source_meta.get("summary") or "").strip()
            or str(source_row["title"] or "").strip()
        )
        if source_summary:
            target_meta["branch_summary"] = source_summary
        conn.execute(
            "UPDATE workstream SET metadata = ? WHERE id = ?",
            (json.dumps(target_meta) if target_meta else None, target_id),
        )
        _index_workstream(conn, target_id)

        source_sessions = conn.execute(
            """
            SELECT * FROM session
            WHERE workstream_id = ?
            ORDER BY id ASC
            """,
            (source_id,),
        ).fetchall()

        cur = conn.cursor()
        for source_session in source_sessions:
            session_meta = _json_loads_safe(source_session["metadata"])
            session_meta["branch_snapshot_from"] = {
                "workstream_id": source_id,
                "workstream_slug": source_row["slug"],
                "session_id": int(source_session["id"]),
                "session_title": source_session["title"],
            }
            cur.execute(
                """
                INSERT INTO session(workstream_id, title, agent, tags, workspace, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_id,
                    source_session["title"],
                    source_session["agent"],
                    source_session["tags"],
                    source_session["workspace"],
                    source_session["created_at"],
                    json.dumps(session_meta) if session_meta else None,
                ),
            )
            latest_new_session_id = int(cur.lastrowid)
            _index_session(conn, latest_new_session_id)

            source_entries = conn.execute(
                """
                SELECT * FROM entry
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (int(source_session["id"]),),
            ).fetchall()
            for source_entry in source_entries:
                entry_extras = _json_loads_safe(source_entry["extras"])
                entry_extras["branch_snapshot_from"] = {
                    "workstream_id": source_id,
                    "workstream_slug": source_row["slug"],
                    "session_id": int(source_session["id"]),
                    "entry_id": int(source_entry["id"]),
                }
                cur.execute(
                    """
                    INSERT INTO entry(session_id, type, content, extras, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        latest_new_session_id,
                        source_entry["type"],
                        source_entry["content"],
                        json.dumps(entry_extras) if entry_extras else None,
                        source_entry["created_at"],
                    ),
                )
                new_entry_id = int(cur.lastrowid)
                updated_extras = _copy_branch_attachment(entry_extras, latest_new_session_id, new_entry_id)
                if updated_extras != entry_extras:
                    conn.execute(
                        "UPDATE entry SET extras = ? WHERE id = ?",
                        (json.dumps(updated_extras), new_entry_id),
                    )
                _index_entry(conn, new_entry_id)

        if latest_new_session_id is None:
            empty_meta = {
                "branch_snapshot_from": {
                    "workstream_id": source_id,
                    "workstream_slug": source_row["slug"],
                    "empty_source": True,
                }
            }
            cur.execute(
                """
                INSERT INTO session(workstream_id, title, agent, tags, workspace, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_id,
                    f"Branch from {source_row['slug']}",
                    default_agent,
                    None,
                    source_row["workspace"],
                    now_iso(),
                    json.dumps(empty_meta),
                ),
            )
            latest_new_session_id = int(cur.lastrowid)
            _index_session(conn, latest_new_session_id)

        conn.commit()

    return latest_new_session_id


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def latest_session_id(workstream_slug: Optional[str] = None, workstream_id: Optional[int] = None) -> Optional[int]:
    db = _db_path()
    if not db.exists():
        return None
    with _connect_db() as conn:
        if workstream_slug or workstream_id:
            if workstream_slug:
                row = conn.execute("SELECT id FROM workstream WHERE slug = ?", (workstream_slug,)).fetchone()
            else:
                row = conn.execute("SELECT id FROM workstream WHERE id = ?", (workstream_id,)).fetchone()
            if not row:
                return None
            wid = int(row["id"])
        else:
            cur = current_workstream()
            if not cur:
                return None
            wid = int(cur["id"])
        row = conn.execute(
            "SELECT id FROM session WHERE workstream_id = ? ORDER BY id DESC LIMIT 1",
            (wid,),
        ).fetchone()
        return int(row["id"]) if row else None


def _create_session_for_workstream(workstream: Dict[str, object], agent: Optional[str] = None, title: str = "New session") -> int:
    sid = create_session(agent=agent, title=title)
    with _connect_db() as conn:
        conn.execute(
            "UPDATE session SET workstream_id = ? WHERE id = ?",
            (int(workstream["id"]), sid),
        )
        conn.commit()
    return sid


def _workstream_repo_info(workstream: Dict[str, object]) -> Tuple[str, str]:
    ws_row = _workstream_row_by_slug(str(workstream["slug"]))
    if not ws_row:
        return "", "unknown"
    with _connect_db() as conn:
        workspace = _effective_workspace_for_workstream(conn, ws_row)
    relation = _workspace_relation(_invocation_workspace(), workspace)
    return workspace, relation


def _assert_repo_guard(workstream: Dict[str, object], *, allow_other_repo: bool, override_command: str) -> None:
    workspace, relation = _workstream_repo_info(workstream)
    current_workspace = _invocation_workspace()
    if relation != "other" or allow_other_repo:
        return
    repo_label = workspace or "unknown repo"
    print(
        (
            f"Workstream '{workstream['slug']}' belongs to another repo: {repo_label}\n"
            f"Current repo: {current_workspace}\n"
            f"Use '{override_command} --allow-other-repo' if you really want to continue here."
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)


def _session_rows_for_workstream(workstream_id: int) -> List[sqlite3.Row]:
    db = _db_path()
    if not db.exists():
        return []
    with _connect_db() as conn:
        return conn.execute(
            """
            SELECT * FROM session
            WHERE workstream_id = ?
            ORDER BY id DESC
            """,
            (workstream_id,),
        ).fetchall()


def _session_source_links_for_workstream(workstream_id: int) -> List[sqlite3.Row]:
    db = _db_path()
    if not db.exists():
        return []
    with _connect_db() as conn:
        if not _table_exists(conn, "session_source_link"):
            return []
        return conn.execute(
            """
            SELECT * FROM session_source_link
            WHERE workstream_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (workstream_id,),
        ).fetchall()


def _session_source_links_for_session(session_id: int) -> List[sqlite3.Row]:
    db = _db_path()
    if not db.exists():
        return []
    with _connect_db() as conn:
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


def _session_source_link(session_id: int, source: str) -> Optional[sqlite3.Row]:
    db = _db_path()
    if not db.exists():
        return None
    with _connect_db() as conn:
        if not _table_exists(conn, "session_source_link"):
            return None
        return conn.execute(
            """
            SELECT * FROM session_source_link
            WHERE session_id = ? AND source = ?
            """,
            (session_id, source),
        ).fetchone()


def _backfill_session_links_for_workstream(workstream_id: int) -> None:
    db = _db_path()
    if not db.exists():
        return
    with _connect_db() as conn:
        if not _table_exists(conn, "session_source_link") or not _table_exists(conn, "workstream_source_link"):
            return
        existing = conn.execute(
            "SELECT 1 FROM session_source_link WHERE workstream_id = ? LIMIT 1",
            (workstream_id,),
        ).fetchone()
        if existing:
            return
        latest_session = conn.execute(
            """
            SELECT id FROM session
            WHERE workstream_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (workstream_id,),
        ).fetchone()
        if not latest_session:
            return
        legacy_links = conn.execute(
            """
            SELECT * FROM workstream_source_link
            WHERE workstream_id = ?
            ORDER BY id ASC
            """,
            (workstream_id,),
        ).fetchall()
        for link in legacy_links:
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
                    workstream_id,
                    link["source"],
                    link["external_session_id"],
                    link["transcript_path"],
                    link["transcript_mtime"],
                    link["message_count"],
                    link["created_at"],
                    link["updated_at"],
                    link["metadata"],
                ),
            )
        conn.commit()


def _latest_detached_session_id(workstream_id: int) -> Optional[int]:
    _backfill_session_links_for_workstream(workstream_id)
    db = _db_path()
    if not db.exists():
        return None
    with _connect_db() as conn:
        if not _table_exists(conn, "session_source_link"):
            row = conn.execute(
                """
                SELECT id FROM session
                WHERE workstream_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (workstream_id,),
            ).fetchone()
            return int(row["id"]) if row else None
        row = conn.execute(
            """
            SELECT s.id
            FROM session s
            LEFT JOIN session_source_link l ON l.session_id = s.id
            WHERE s.workstream_id = ? AND l.id IS NULL
            ORDER BY s.id DESC
            LIMIT 1
            """,
            (workstream_id,),
        ).fetchone()
        return int(row["id"]) if row else None


def _workstream_source_link(workstream_id: int, source: str) -> Optional[sqlite3.Row]:
    db = _db_path()
    if not db.exists():
        return None
    with _connect_db() as conn:
        return conn.execute(
            """
            SELECT * FROM workstream_source_link
            WHERE workstream_id = ? AND source = ?
            """,
            (workstream_id, source),
        ).fetchone()


def _workstream_source_links(workstream_id: int) -> List[sqlite3.Row]:
    db = _db_path()
    if not db.exists():
        return []
    with _connect_db() as conn:
        return conn.execute(
            """
            SELECT * FROM workstream_source_link
            WHERE workstream_id = ?
            ORDER BY source ASC
            """,
            (workstream_id,),
        ).fetchall()


def _workstream_row_by_slug(slug: str) -> Optional[sqlite3.Row]:
    db = _db_path()
    if not db.exists():
        return None
    with _connect_db() as conn:
        return conn.execute(
            "SELECT * FROM workstream WHERE slug = ?",
            (slug,),
        ).fetchone()


def _session_row(session_id: int) -> Optional[sqlite3.Row]:
    db = _db_path()
    if not db.exists():
        return None
    with _connect_db() as conn:
        return conn.execute(
            """
            SELECT s.*, w.slug AS workstream_slug
            FROM session s
            LEFT JOIN workstream w ON w.id = s.workstream_id
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()


def _recent_entry_rows(workstream_id: int, limit: int = 4) -> List[sqlite3.Row]:
    db = _db_path()
    if not db.exists():
        return []
    with _connect_db() as conn:
        rows = conn.execute(
            """
            SELECT e.*, s.title AS session_title
            FROM entry e
            JOIN session s ON s.id = e.session_id
            WHERE s.workstream_id = ?
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (workstream_id, max(limit * 5, 20)),
        ).fetchall()
    visible = [row for row in rows if _entry_load_behavior(row) != "exclude"]
    meaningful = [
        row
        for row in visible
        if _entry_role(row) not in {"developer", "system"} and not _looks_like_ctx_noise(row["content"])
    ]
    return meaningful[:limit] if meaningful else visible[:limit]


def _load_control_counts(workstream_id: int) -> Tuple[int, int]:
    db = _db_path()
    if not db.exists():
        return 0, 0
    with _connect_db() as conn:
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


def _workstream_goal_text(workstream_row: sqlite3.Row) -> str:
    meta = _json_loads_safe(workstream_row["metadata"])
    return (
        (workstream_row["description"] or "").strip()
        or str(meta.get("summary") or "").strip()
        or str(workstream_row["title"])
    )


def _source_links_text(workstream_id: int, session_id: Optional[int] = None) -> str:
    if session_id is not None:
        links = _session_source_links_for_session(session_id)
        if links:
            return ", ".join(f"{row['source']}:{row['external_session_id']}" for row in links)
    _backfill_session_links_for_workstream(workstream_id)
    links = _session_source_links_for_workstream(workstream_id)
    if links:
        return ", ".join(
            f"{row['source']}:{row['external_session_id']}->S{row['session_id']}"
            for row in links
        )
    links = _workstream_source_links(workstream_id)
    if not links:
        return "none"
    return ", ".join(f"{row['source']}:{row['external_session_id']}" for row in links)


def _resume_pack_text(
    slug: str,
    *,
    focus: Optional[str],
    fmt: str,
    brief: bool,
    max_sessions: int,
    max_entries: int,
) -> str:
    preamble = (
        "You are joining an ongoing workstream. The following pack includes recent sessions and entries. "
        "Read the pack and ask any clarifying questions before proceeding.\n\n"
    )
    return preamble + workstream_pack(
        slug,
        focus=focus,
        fmt=fmt,
        brief=brief,
        max_sessions=max_sessions,
        max_entries=max_entries,
    )


def _select_loaded_pack(
    slug: str,
    *,
    focus: Optional[str],
    fmt: str,
    brief: bool,
) -> Tuple[str, str]:
    budget = _load_char_budget()
    candidates = [
        ("full", dict(focus=focus, brief=brief, max_sessions=12, max_entries=240)),
        ("trimmed", dict(focus=focus, brief=brief, max_sessions=6, max_entries=90)),
        ("compressed", dict(focus=focus, brief=False, max_sessions=4, max_entries=28)),
        ("brief", dict(focus=focus, brief=True, max_sessions=2, max_entries=12)),
    ]
    fallback_text = ""
    fallback_mode = "brief"
    for mode, opts in candidates:
        text = _resume_pack_text(slug, fmt=fmt, **opts)
        fallback_text = text
        fallback_mode = mode
        if len(text) <= budget:
            return mode, text
    return fallback_mode, fallback_text


def _render_loaded_output(
    workstream: Dict[str, object],
    *,
    session_id: int,
    action_label: str,
    focus: Optional[str],
    fmt: str,
    brief: bool,
    compress: bool,
) -> str:
    ws_row = _workstream_row_by_slug(str(workstream["slug"]))
    session = _session_row(session_id) if session_id else None
    if not ws_row:
        if compress:
            return _resume_pack_text(str(workstream["slug"]), focus=focus, fmt=fmt, brief=brief, max_sessions=5, max_entries=50)
        return _resume_pack_text(str(workstream["slug"]), focus=focus, fmt=fmt, brief=brief, max_sessions=12, max_entries=240)
    recent_entries = _recent_entry_rows(int(ws_row["id"]), limit=4)
    pinned_count, excluded_count = _load_control_counts(int(ws_row["id"]))
    current_workspace = _invocation_workspace()
    with _connect_db() as conn:
        effective_workspace = _effective_workspace_for_workstream(conn, ws_row)
    workspace_relation = _workspace_relation(current_workspace, effective_workspace)
    workspace_note = ""
    if effective_workspace:
        if workspace_relation == "current":
            workspace_note = f"this repo (`{effective_workspace}`)" if fmt == "markdown" else f"this repo ({effective_workspace})"
        elif current_workspace:
            workspace_note = (
                f"warning: this workstream was in `{effective_workspace}`; current repo is `{current_workspace}`"
                if fmt == "markdown"
                else f"warning: this workstream was in {effective_workspace}; current repo is {current_workspace}"
            )
        else:
            workspace_note = f"`{effective_workspace}`" if fmt == "markdown" else effective_workspace
    else:
        workspace_note = "unknown"
    if compress:
        pack_mode, pack_text = _select_loaded_pack(str(workstream["slug"]), focus=focus, fmt=fmt, brief=brief)
    else:
        pack_mode = "full"
        pack_text = _resume_pack_text(
            str(workstream["slug"]),
            focus=focus,
            fmt=fmt,
            brief=brief,
            max_sessions=12,
            max_entries=240,
        )
    goal = _workstream_goal_text(ws_row)
    links = _source_links_text(int(ws_row["id"]), session_id=session_id)
    recent_lines = []
    if recent_entries:
        for row in recent_entries:
            role = _entry_role(row)
            label = f"{row['type']}/{role}" if role and role != row["type"] else row["type"]
            recent_lines.append(
                f"- S{row['session_id']} `{label}`: {_preview_text(row['content'], limit=110)}"
            )
    else:
        recent_lines.append("- No entries yet")

    session_label = "n/a"
    if session:
        session_label = f"S{session['id']} {session['title']} (@{session['agent'] or 'n/a'}) — {session['created_at']}"

    continuation_lines_md: List[str] = []
    continuation_lines_text: List[str] = []
    guidance_lines_md: List[str] = []
    guidance_lines_text: List[str] = []
    if action_label.startswith("resumed"):
        continuation_lines_md = [
            f"- Continuation: new context from this conversation will now be appended to `{workstream['slug']}`.",
            f"- Branching: if you want to explore without changing `{workstream['slug']}`, create a branch first with `ctx branch {workstream['slug']} <new-name>`.",
        ]
        continuation_lines_text = [
            f"Continuation: new context from this conversation will now be appended to {workstream['slug']}.",
            f"Branching: if you want to explore without changing {workstream['slug']}, create a branch first with: ctx branch {workstream['slug']} <new-name>",
        ]
        guidance_lines_md = [
            "- Assistant: make it explicit that new context from this conversation will now be appended to this workstream.",
            "- Assistant: if the user wants a separate path that does not change this workstream, tell them to create a branch first.",
        ]
        guidance_lines_text = [
            "- Assistant: make it explicit that new context from this conversation will now be appended to this workstream.",
            "- Assistant: if the user wants a separate path that does not change this workstream, tell them to create a branch first.",
        ]

    if fmt == "markdown":
        lines = [
            f"## ctx loaded: `{workstream['slug']}`",
            "",
            f"- Action: {action_label}",
            f"- Session: {session_label}",
            f"- Goal: {goal}",
            f"- Repo: {workspace_note}",
            f"- Linked transcripts: {links}",
            f"- Load controls: {pinned_count} pinned | {excluded_count} excluded",
            f"- Pack mode: {pack_mode}",
            *continuation_lines_md,
            "- Tip: In Codex, use `ctrl-t` to inspect the full command output. In Claude, expand the tool output block in the UI.",
            "",
            "### Last things",
            *recent_lines,
            "",
            "### How To Use This Load",
            "",
            "- In Codex, press `ctrl-t` to inspect the full command output if the full pack is collapsed.",
            "- In Claude, expand the tool output block to inspect the full pack.",
            "- Assistant: summarize this workstream briefly, mention the latest relevant activity, and ask how the user wants to proceed.",
            *guidance_lines_md,
            "- Assistant: do not paste the full ctx pack back unless the user explicitly asks for it.",
            "",
            "---",
            "",
            "<ctx-pack>",
            "",
            pack_text,
            "",
            "</ctx-pack>",
        ]
        return "\n".join(lines)

    lines = [
        f"ctx loaded: {workstream['slug']}",
        f"Action: {action_label}",
        f"Session: {session_label}",
        f"Goal: {goal}",
        f"Repo: {workspace_note}",
        f"Linked transcripts: {links}",
        f"Load controls: {pinned_count} pinned | {excluded_count} excluded",
        f"Pack mode: {pack_mode}",
        *continuation_lines_text,
        "Tip: In Codex, use ctrl-t to inspect the full command output. In Claude, expand the tool output block in the UI.",
        "",
        "Last things:",
        *recent_lines,
        "",
        "How to use this load:",
        "- In Codex, press ctrl-t to inspect the full command output if the full pack is collapsed.",
        "- In Claude, expand the tool output block to inspect the full pack.",
        "- Assistant: summarize this workstream briefly, mention the latest relevant activity, and ask how the user wants to proceed.",
        *guidance_lines_text,
        "- Assistant: do not paste the full ctx pack back unless the user explicitly asks for it.",
        "",
        "<ctx-pack>",
        pack_text,
        "</ctx-pack>",
    ]
    return "\n".join(lines)


def _external_owner(source: str, external_session_id: str) -> Optional[Dict[str, object]]:
    db = _db_path()
    if not db.exists():
        return None
    with _connect_db() as conn:
        row = None
        if _table_exists(conn, "session_source_link"):
            row = conn.execute(
                """
                SELECT l.session_id, l.workstream_id, w.slug, w.title
                FROM session_source_link l
                JOIN workstream w ON w.id = l.workstream_id
                WHERE l.source = ? AND l.external_session_id = ?
                """,
                (source, external_session_id),
            ).fetchone()
        if row is None and _table_exists(conn, "workstream_source_link"):
            row = conn.execute(
                """
                SELECT NULL AS session_id, l.workstream_id, w.slug, w.title
                FROM workstream_source_link l
                JOIN workstream w ON w.id = l.workstream_id
                WHERE l.source = ? AND l.external_session_id = ?
                """,
                (source, external_session_id),
            ).fetchone()
    if not row:
        return None
    return {
        "session_id": int(row["session_id"]) if row["session_id"] is not None else None,
        "id": int(row["workstream_id"]),
        "slug": row["slug"],
        "title": row["title"],
    }


def _upsert_session_source_link(
    session_id: int,
    workstream_id: int,
    source: str,
    external_session_id: str,
    transcript_path: Path,
    transcript_mtime: float,
    message_count: int,
) -> None:
    with _connect_db() as conn:
        if not _table_exists(conn, "session_source_link"):
            return
        conn.execute(
            """
            INSERT INTO session_source_link(
                session_id, workstream_id, source, external_session_id, transcript_path,
                transcript_mtime, message_count, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(session_id, source) DO UPDATE SET
                external_session_id = excluded.external_session_id,
                workstream_id = excluded.workstream_id,
                transcript_path = excluded.transcript_path,
                transcript_mtime = excluded.transcript_mtime,
                message_count = excluded.message_count,
                updated_at = datetime('now')
            """,
            (
                session_id,
                workstream_id,
                source,
                external_session_id,
                str(transcript_path),
                transcript_mtime,
                message_count,
            ),
        )
        conn.commit()


# -------- Transcript ingestion helpers --------

def _expanduser(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def _latest_jsonl_under(root: Path, name_hint: Optional[str] = None, source: Optional[str] = None) -> Optional[Path]:
    latest: Tuple[float, Optional[Path]] = (0.0, None)
    if not root.exists():
        return None
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not (f.endswith(".jsonl") or f.endswith(".json")):
                continue
            p = Path(dirpath) / f
            if source == "claude":
                if "subagents" in p.parts:
                    continue
                if f.endswith(".meta.json"):
                    continue
            if name_hint and name_hint not in f:
                # prefer name-hinted files
                pass
            try:
                m = p.stat().st_mtime
                if m >= latest[0]:
                    latest = (m, p)
            except Exception:
                continue
    return latest[1]


def _extract_text_blocks(value) -> List[str]:
    parts: List[str] = []
    if value is None:
        return parts
    if isinstance(value, str):
        text = value.strip()
        if text:
            parts.append(text)
        return parts
    if isinstance(value, list):
        for item in value:
            parts.extend(_extract_text_blocks(item))
        return parts
    if isinstance(value, dict):
        text_type = str(value.get("type") or "").strip().lower()
        if text_type in {"image", "input_image"}:
            return parts
        for key in ("text", "content", "message", "output", "input", "arguments"):
            if key in value:
                parts.extend(_extract_text_blocks(value.get(key)))
        return parts
    return parts


def _join_text_blocks(value) -> Optional[str]:
    parts = [p for p in _extract_text_blocks(value) if p]
    if not parts:
        return None
    text = "\n".join(parts).strip()
    return text or None


def _messages_from_record(obj: dict) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else None
    if payload:
        ptype = str(payload.get("type") or "").strip().lower()
        if ptype == "message":
            role = str(payload.get("role") or obj.get("role") or obj.get("sender") or "system").strip().lower() or "system"
            text = _join_text_blocks(payload.get("content"))
            if text:
                out.append({"role": role, "content": text})
            return out
        if ptype in {"function_call", "custom_tool_call"}:
            name = str(payload.get("name") or ptype).strip()
            body = _join_text_blocks(payload.get("arguments") if ptype == "function_call" else payload.get("input"))
            text = f"[{name}]"
            if body:
                text += "\n" + body
            out.append({"role": "tool_call", "content": text})
            return out
        if ptype in {"function_call_output", "custom_tool_call_output"}:
            body = _join_text_blocks(payload.get("output"))
            if body:
                out.append({"role": "tool", "content": body})
            return out
        if ptype in {"user_message", "agent_message"}:
            # These usually duplicate response_item/message records, so use them
            # only when no direct message payload is present elsewhere.
            text = _join_text_blocks(payload.get("message"))
            role = "assistant" if ptype == "agent_message" else "user"
            if text:
                out.append({"role": role, "content": text})
            return out

    role = obj.get("role") or obj.get("sender")
    text = obj.get("content") or obj.get("text")
    if text is None and isinstance(obj.get("message"), dict):
        role = role or obj["message"].get("role")
        text = obj["message"].get("text") or obj["message"].get("content")
    text = _join_text_blocks(text)
    if text:
        out.append({"role": str(role or "system"), "content": text})
    return out


def _read_jsonl_messages(path: Path) -> List[Dict[str, str]]:
    msgs: List[Dict[str, str]] = []
    try:
        raw = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and isinstance(data.get("messages"), list):
                    for m in data["messages"]:
                        role = (m.get("role") or m.get("sender") or "system") if isinstance(m, dict) else "system"
                        content = ""
                        if isinstance(m, dict):
                            content = m.get("content") or m.get("text") or ""
                            if isinstance(content, list):
                                content = "\n".join([c for c in content if isinstance(c, str)])
                        if content:
                            msgs.append({"role": role, "content": content})
                    return msgs
                if isinstance(data, list):
                    # Treat as JSONL-like array
                    for obj in data:
                        if not isinstance(obj, dict):
                            continue
                        msgs.extend(_messages_from_record(obj))
                    return msgs
            except Exception:
                # fall through to line-based parsing
                pass
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            msgs.extend(_messages_from_record(obj))
    except Exception:
        pass
    deduped: List[Dict[str, str]] = []
    last_key: Optional[Tuple[str, str]] = None
    for msg in msgs:
        role = str(msg.get("role") or "system").strip().lower() or "system"
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        key = (role, content)
        if key == last_key:
            continue
        last_key = key
        deduped.append({"role": role, "content": content})
    return deduped


def ingest_messages(messages: List[Dict[str, str]], source_label: Optional[str], session_id: Optional[int] = None) -> None:
    if not messages:
        return
    payload = json.dumps({"messages": messages})
    run_ctx([
        "ingest", "--file", "-", "--format", "json",
        *( ["--session-id", str(session_id)] if session_id is not None else [] ),
        *( ["--source", source_label] if source_label else [] ),
    ], input_data=payload)


UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _iter_transcript_files(root: Path, source: str):
    if not root.exists():
        return
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not (f.endswith(".jsonl") or f.endswith(".json")):
                continue
            p = Path(dirpath) / f
            if source == "claude":
                if "subagents" in p.parts:
                    continue
                if f.endswith(".meta.json"):
                    continue
            yield p


def _extract_uuid_like(text: str) -> Optional[str]:
    m = UUID_RE.search(text)
    return m.group(0) if m else None


def _extract_codex_session_id(path: Path) -> Optional[str]:
    try:
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in ("id", "sessionId", "session_id"):
                    if data.get(key):
                        return str(data[key])
        with path.open("r", encoding="utf-8") as fh:
            for _ in range(8):
                line = fh.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    for key in ("id", "sessionId", "session_id"):
                        if obj.get(key):
                            return str(obj[key])
    except Exception:
        pass
    return _extract_uuid_like(path.name)


def _extract_claude_session_id(path: Path) -> Optional[str]:
    try:
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if data.get("sessionId"):
                    return str(data["sessionId"])
                if isinstance(data.get("message"), dict) and data["message"].get("sessionId"):
                    return str(data["message"]["sessionId"])
        with path.open("r", encoding="utf-8") as fh:
            for _ in range(40):
                line = fh.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    if obj.get("sessionId"):
                        return str(obj["sessionId"])
                    if isinstance(obj.get("message"), dict) and obj["message"].get("sessionId"):
                        return str(obj["message"]["sessionId"])
    except Exception:
        pass
    stem_id = _extract_uuid_like(path.stem)
    if stem_id:
        return stem_id
    return _extract_uuid_like(str(path.parent))


def _extract_external_session_id(source: str, path: Path) -> Optional[str]:
    if source == "codex":
        return _extract_codex_session_id(path)
    if source == "claude":
        return _extract_claude_session_id(path)
    return None


def _load_transcript_candidate(source: str, path: Path) -> Optional[Dict[str, object]]:
    if not path.exists():
        return None
    external_session_id = _extract_external_session_id(source, path)
    if not external_session_id:
        return None
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0.0
    return {
        "source": source,
        "path": path,
        "external_session_id": external_session_id,
        "mtime": mtime,
        "messages": _read_jsonl_messages(path),
    }


def _transcript_root(source: str) -> Path:
    if source == "codex":
        return _expanduser(os.getenv("CODEX_HOME", "~/.codex")) / "sessions"
    if source == "claude":
        return _expanduser(os.getenv("CLAUDE_HOME", "~/.claude")) / "projects"
    raise ValueError(f"Unsupported source: {source}")


def _latest_transcript_for_source(source: str) -> Optional[Dict[str, object]]:
    p = _latest_jsonl_under(_transcript_root(source), source=source)
    if not p:
        return None
    return _load_transcript_candidate(source, p)


def _find_transcript_by_external_id(source: str, external_session_id: str) -> Optional[Dict[str, object]]:
    root = _transcript_root(source)
    for path in _iter_transcript_files(root, source):
        candidate = _load_transcript_candidate(source, path)
        if candidate and candidate["external_session_id"] == external_session_id:
            return candidate
    return None


def find_latest_codex_transcript() -> Optional[Path]:
    return _latest_jsonl_under(_transcript_root("codex"), source="codex")


def find_latest_claude_transcript() -> Optional[Path]:
    return _latest_jsonl_under(_transcript_root("claude"), source="claude")


def _normalize_source(source: Optional[str]) -> Optional[str]:
    if not source:
        return None
    s = str(source).strip().lower()
    return s if s in {"codex", "claude"} else None


def _find_session_for_external(workstream_id: int, source: str, external_session_id: str) -> Optional[int]:
    _backfill_session_links_for_workstream(workstream_id)
    db = _db_path()
    if not db.exists():
        return None
    with _connect_db() as conn:
        if not _table_exists(conn, "session_source_link"):
            return None
        row = conn.execute(
            """
            SELECT session_id
            FROM session_source_link
            WHERE workstream_id = ? AND source = ? AND external_session_id = ?
            ORDER BY session_id DESC
            LIMIT 1
            """,
            (workstream_id, source, external_session_id),
        ).fetchone()
    return int(row["session_id"]) if row else None


def _ingest_candidate_for_session(
    workstream: Dict[str, object],
    session_id: int,
    candidate: Dict[str, object],
    *,
    force_bind: bool = False,
) -> bool:
    source = str(candidate["source"])
    external_session_id = str(candidate["external_session_id"])
    owner = _external_owner(source, external_session_id)
    if owner and owner.get("session_id") is not None and int(owner["session_id"]) != int(session_id) and not force_bind:
        print(
            (
                f"Skipping {source} transcript {external_session_id}: "
                f"already linked to session S{owner['session_id']} in workstream {owner['slug']}"
            ),
            file=sys.stderr,
        )
        return False

    link = _session_source_link(int(session_id), source)
    previous_count = int(link["message_count"]) if link else 0
    messages = list(candidate["messages"])
    if previous_count > len(messages):
        previous_count = 0
    delta = messages[previous_count:]
    if delta:
        ingest_messages(delta, source_label=source, session_id=session_id)
    _upsert_session_source_link(
        int(session_id),
        int(workstream["id"]),
        source,
        external_session_id,
        Path(str(candidate["path"])),
        float(candidate["mtime"]),
        len(messages),
    )
    return bool(delta)


def _pull_source_for_session(
    workstream: Dict[str, object],
    session_id: int,
    source: str,
) -> bool:
    source = _normalize_source(source)
    if not source:
        return False
    link = _session_source_link(int(session_id), source)
    candidate = None
    if link:
        linked_path = Path(link["transcript_path"]) if link["transcript_path"] else None
        if linked_path and linked_path.exists():
            candidate = _load_transcript_candidate(source, linked_path)
            if candidate and candidate["external_session_id"] != link["external_session_id"]:
                candidate = None
        if candidate is None:
            candidate = _find_transcript_by_external_id(source, str(link["external_session_id"]))
        if candidate is None:
            print(
                f"No transcript found for linked {source} session {link['external_session_id']}",
                file=sys.stderr,
            )
            return False
        return _ingest_candidate_for_session(workstream, session_id, candidate)

    candidate = _latest_transcript_for_source(source)
    if candidate is None:
        return False
    return _ingest_candidate_for_session(workstream, session_id, candidate)


def _choose_initial_candidate(preferred_source: Optional[str]) -> Optional[Dict[str, object]]:
    preferred = _normalize_source(preferred_source)
    if preferred:
        candidate = _latest_transcript_for_source(preferred)
        if candidate:
            return candidate
    candidates = []
    for source in ("codex", "claude"):
        candidate = _latest_transcript_for_source(source)
        if candidate:
            candidates.append(candidate)
    if not candidates:
        return None
    candidates.sort(key=lambda c: float(c["mtime"]), reverse=True)
    return candidates[0]


def auto_pull(
    workstream: Dict[str, object],
    session_id: int,
    preferred_source: Optional[str] = None,
    initial_candidate: Optional[Dict[str, object]] = None,
) -> Tuple[bool, Optional[str]]:
    _backfill_session_links_for_workstream(int(workstream["id"]))
    links = _session_source_links_for_session(int(session_id))
    if links:
        pulled_sources: List[str] = []
        any_updates = False
        ordered_sources = [str(row["source"]) for row in links]
        preferred = _normalize_source(preferred_source)
        if preferred and preferred in ordered_sources:
            ordered_sources = [preferred] + [s for s in ordered_sources if s != preferred]
        for source in ordered_sources:
            ok = _pull_source_for_session(workstream, session_id, source)
            any_updates = any_updates or ok
            pulled_sources.append(source)
        return any_updates, ",".join(pulled_sources)

    candidate = initial_candidate or _choose_initial_candidate(preferred_source)
    if candidate is None:
        return False, None
    owner = _external_owner(str(candidate["source"]), str(candidate["external_session_id"]))
    if owner and owner.get("session_id") is not None and int(owner["session_id"]) != int(session_id):
        return False, str(candidate["source"])
    ok = _ingest_candidate_for_session(workstream, session_id, candidate)
    return ok, str(candidate["source"])


def ingest_latest_from_codex(workstream: Dict[str, object], session_id: int) -> bool:
    return _pull_source_for_session(workstream, session_id, "codex")


def ingest_latest_from_claude(workstream: Dict[str, object], session_id: int) -> bool:
    return _pull_source_for_session(workstream, session_id, "claude")


def _select_resume_session(
    workstream: Dict[str, object],
    *,
    preferred_source: Optional[str],
    agent: Optional[str],
) -> Tuple[int, str, Optional[Dict[str, object]]]:
    workstream_id = int(workstream["id"])
    _backfill_session_links_for_workstream(workstream_id)
    candidate = _choose_initial_candidate(preferred_source)
    if candidate is not None:
        source = str(candidate["source"])
        external_session_id = str(candidate["external_session_id"])
        owner_session_id = _find_session_for_external(workstream_id, source, external_session_id)
        if owner_session_id is not None:
            return owner_session_id, f"resumed session matched to current {source} transcript", None
        owner = _external_owner(source, external_session_id)
        if owner and int(owner["id"]) != workstream_id:
            detached_sid = _latest_detached_session_id(workstream_id)
            if detached_sid is not None:
                return detached_sid, f"resumed detached session; current {source} transcript belongs to {owner['slug']}", None
            sid = _create_session_for_workstream(
                workstream,
                agent=agent,
                title="Detached resume session",
            )
            return sid, f"resumed detached session; current {source} transcript belongs to {owner['slug']}", None
        sid = _create_session_for_workstream(
            workstream,
            agent=agent,
            title=f"{source.capitalize()} session",
        )
        return sid, f"resumed new session for current {source} transcript", candidate

    sessions = _session_rows_for_workstream(workstream_id)
    if len(sessions) == 1:
        return int(sessions[0]["id"]), "resumed only existing session", None
    detached_sid = _latest_detached_session_id(workstream_id)
    if detached_sid is not None:
        return detached_sid, "resumed detached session", None
    sid = _create_session_for_workstream(workstream, agent=agent, title="Detached resume session")
    return sid, "resumed new detached session", None


def _env_truthy(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return str(v).strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        return default


def _should_auto_pull(flag_auto: bool, flag_no_auto: bool) -> bool:
    # Default to on; allow opt-out via flag or env
    default_on = _env_truthy("CTX_AUTOPULL_DEFAULT", True)
    if flag_no_auto:
        return False
    if flag_auto:
        return True
    return default_on


def list_workstreams(*, this_repo: bool = False):
    args = ["workstream-list"]
    if this_repo:
        args.append("--this-repo")
    return run_ctx(args).rstrip()


def search_context(query: str, limit: int = 8, *, this_repo: bool = False):
    args = ["search", query, "--limit", str(limit)]
    if this_repo:
        args.append("--this-repo")
    return run_ctx(args).rstrip()


def main():
    p = argparse.ArgumentParser(description="Slash-like /ctx helper")
    sub = p.add_subparsers(dest="cmd")

    p_new = sub.add_parser("new", help="/ctx --new <name>")
    p_new.add_argument("name")
    p_new.add_argument("--agent", default=os.getenv("CTX_AGENT_DEFAULT", "other"))
    p_new.add_argument("--focus")
    p_new.add_argument("--format", default="markdown", choices=["text", "markdown"])
    p_new.add_argument("--brief", action="store_true")
    p_new.add_argument("--compress", action="store_true", help="Use a compressed pack instead of the full load")
    p_new.add_argument("--no-compress", action="store_true", help="Do not compress the load output")

    p_list = sub.add_parser("list", help="/ctx list")
    p_list.add_argument("--this-repo", action="store_true", help="Show only workstreams linked to the current repo")
    p_search = sub.add_parser("search", help="/ctx search <query>")
    p_search.add_argument("query", nargs="+")
    p_search.add_argument("--limit", type=int, default=8)
    p_search.add_argument("--this-repo", action="store_true", help="Search only workstreams linked to the current repo")

    p_go = sub.add_parser("go", help="Resume an existing workstream")
    p_go.add_argument("name")
    p_go.add_argument("--focus")
    p_go.add_argument("--format", default="markdown", choices=["text", "markdown"])
    p_go.add_argument("--brief", action="store_true")
    p_go.add_argument("--source", help="Preferred source to bind/pull when unlinked (claude or codex)")
    p_go.add_argument("--auto-pull", action="store_true", help="Import newest Codex/Claude transcript before emitting pack (default on; see CTX_AUTOPULL_DEFAULT)")
    p_go.add_argument("--no-auto-pull", action="store_true", help="Disable auto-pull for this invocation")
    p_go.add_argument("--allow-other-repo", action="store_true", help="Allow resuming a workstream that belongs to a different repo")
    p_go.add_argument("--compress", action="store_true", help="Use a compressed pack instead of the full load")
    p_go.add_argument("--no-compress", action="store_true", help="Do not compress the load output")

    # Friendly aliases tailored to "-start" and "-resume" chat triggers
    p_start = sub.add_parser("start", help="Ensure workstream, create session, optionally ingest clipboard, and emit pack")
    p_start.add_argument("name", help="Workstream name or slug")
    p_start.add_argument("--agent", default=os.getenv("CTX_AGENT_DEFAULT", "other"))
    p_start.add_argument("--focus")
    p_start.add_argument("--format", default="markdown", choices=["text", "markdown"])
    p_start.add_argument("--brief", action="store_true")
    p_start.add_argument("--from-clipboard", action="store_true", help="Ingest current clipboard into the new session")
    p_start.add_argument("--copy-frontmost", action="store_true", help="macOS: send Cmd+A/C to frontmost app before ingesting clipboard")
    p_start.add_argument(
        "--pull",
        action="store_true",
        help="Alias for --copy-frontmost --from-clipboard; capture the current visible chat into the new session",
    )
    p_start.add_argument("--source", default=os.getenv("CTX_SOURCE_DEFAULT"), help="Optional source label for ingest (e.g., claude, codex)")
    p_start.add_argument("--pull-codex", action="store_true", help="Import latest Codex transcript into the session")
    p_start.add_argument("--pull-claude", action="store_true", help="Import latest Claude Code transcript into the session")
    p_start.add_argument("--auto-pull", action="store_true", help="Import the newest transcript between Codex and Claude (default on; see CTX_AUTOPULL_DEFAULT)")
    p_start.add_argument("--no-auto-pull", action="store_true", help="Disable auto-pull for this invocation")
    p_start.add_argument("--compress", action="store_true", help="Use a compressed pack instead of the full load")
    p_start.add_argument("--no-compress", action="store_true", help="Do not compress the load output")

    p_resume2 = sub.add_parser("resume", help="Resume an existing workstream")
    p_resume2.add_argument("name", help="Workstream name or slug")
    p_resume2.add_argument("--focus")
    p_resume2.add_argument("--format", default="markdown", choices=["text", "markdown"])
    p_resume2.add_argument("--brief", action="store_true")
    p_resume2.add_argument("--source", help="Preferred source to bind/pull when unlinked (claude or codex)")
    p_resume2.add_argument("--pull-codex", action="store_true", help="Import latest Codex transcript into the latest session before emitting pack")
    p_resume2.add_argument("--pull-claude", action="store_true", help="Import latest Claude Code transcript into the latest session before emitting pack")
    p_resume2.add_argument("--auto-pull", action="store_true", help="Import the newest transcript between Codex and Claude before emitting pack (default on; see CTX_AUTOPULL_DEFAULT)")
    p_resume2.add_argument("--no-auto-pull", action="store_true", help="Disable auto-pull for this invocation")
    p_resume2.add_argument("--allow-other-repo", action="store_true", help="Allow resuming a workstream that belongs to a different repo")
    p_resume2.add_argument("--compress", action="store_true", help="Use a compressed pack instead of the full load")
    p_resume2.add_argument("--no-compress", action="store_true", help="Do not compress the load output")

    p_branch = sub.add_parser("branch", help="Create a new workstream seeded from an existing workstream's current context")
    p_branch.add_argument("source_name", help="Existing source workstream slug or title")
    p_branch.add_argument("target_name", help="New target workstream slug or title")
    p_branch.add_argument("--agent", default=os.getenv("CTX_AGENT_DEFAULT", "other"))
    p_branch.add_argument("--focus")
    p_branch.add_argument("--format", default="markdown", choices=["text", "markdown"])
    p_branch.add_argument("--brief", action="store_true")
    p_branch.add_argument("--allow-other-repo", action="store_true", help="Allow branching from a workstream that belongs to a different repo")
    p_branch.add_argument("--compress", action="store_true", help="Use a compressed pack instead of the full load")
    p_branch.add_argument("--no-compress", action="store_true", help="Do not compress the load output")

    p_delete = sub.add_parser("delete", help="Delete a session by id, or delete the latest session in a workstream")
    p_delete.add_argument("name", nargs="?", help="Workstream slug or title; deletes the latest session in that workstream")
    p_delete.add_argument("--session-id", type=int, help="Delete this specific session id")

    # Hidden expert command: pull transcripts explicitly
    p_pull = sub.add_parser("pull", help="Pull transcript(s) from Codex/Claude and ingest into the latest session")
    p_pull.add_argument("--codex", action="store_true")
    p_pull.add_argument("--claude", action="store_true")
    p_pull.add_argument("--auto", action="store_true")
    p_pull.add_argument("--source", help="Preferred source for --auto (claude or codex)")

    p_web = sub.add_parser("web", help="Serve the local ctx browser frontend")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=4310)
    p_web.add_argument("--open", action="store_true")

    # Optional: set current workstream easily
    p_set = sub.add_parser("set", help="Set current workstream by slug or name (ensures if missing)")
    p_set.add_argument("name")

    p_rename = sub.add_parser("rename", help="Rename the current or a specific workstream")
    p_rename.add_argument("new_name", help="New workstream name")
    p_rename.add_argument("--from", dest="ref", help="Existing workstream slug or title (defaults to current)")

    # Frictionless capture helpers
    p_note = sub.add_parser("note", help="Capture a note (arg or stdin)")
    p_note.add_argument("text", nargs="?", help="Note text; if omitted, read stdin")

    p_dec = sub.add_parser("decision", help="Capture a decision")
    p_dec.add_argument("text", nargs=1)

    p_todo = sub.add_parser("todo", help="Capture a todo")
    p_todo.add_argument("text", nargs=1)

    p_link = sub.add_parser("link", help="Capture a link or reference")
    p_link.add_argument("url")

    p_snap = sub.add_parser("snap", help="Snapshot a file into attachments and record it")
    p_snap.add_argument("path")

    p_run = sub.add_parser("run", help="Run a shell command and log its output")
    p_run.add_argument("cmd_str", help="Command to run (quote it if it has pipes/etc.)")

    p_git = sub.add_parser("git", help="Capture git context (branch, last commit, status)")

    # Ingest helpers
    p_ingf = sub.add_parser("ingest-file", help="Ingest a transcript or text file")
    p_ingf.add_argument("path")
    p_ingf.add_argument("--format", default="auto", choices=["auto","text","markdown","json"])
    p_ingf.add_argument("--source")
    p_ingc = sub.add_parser("ingest-clipboard", help="Ingest text from clipboard")
    p_ingc.add_argument("--format", default="auto", choices=["auto","text","markdown","json"])
    p_ingc.add_argument("--source")

    args = p.parse_args()

    if args.cmd == "new":
        compress = _should_compress(getattr(args, "compress", False), getattr(args, "no_compress", False))
        ws = ensure_workstream(args.name, set_current=True, unique_if_exists=True)
        sid = _create_session_for_workstream(ws, agent=args.agent)
        action_label = "started new workstream and first session"
        if ws.get("renamed"):
            action_label = f"started new workstream with auto-renamed name (requested '{args.name}')"
        sys.stdout.write(
            _render_loaded_output(
                ws,
                session_id=sid,
                action_label=action_label,
                focus=args.focus,
                fmt=args.format,
                brief=args.brief,
                compress=compress,
            )
        )
    elif args.cmd == "list":
        sys.stdout.write(list_workstreams(this_repo=getattr(args, "this_repo", False)) + "\n")
    elif args.cmd == "search":
        sys.stdout.write(
            search_context(
                " ".join(args.query),
                limit=args.limit,
                this_repo=getattr(args, "this_repo", False),
            ) + "\n"
        )
    elif args.cmd == "go":
        compress = _should_compress(getattr(args, "compress", False), getattr(args, "no_compress", False))
        ws = lookup_workstream(args.name)
        if not ws:
            sys.stdout.write(f"No workstream matching '{args.name}' exists.\n")
            return 0
        _assert_repo_guard(
            ws,
            allow_other_repo=getattr(args, "allow_other_repo", False),
            override_command=f"ctx resume {ws['slug']}",
        )
        run_ctx(["workstream-set-current", "--slug", str(ws["slug"])])
        ws = current_workstream() or ws
        sid, action_label, initial_candidate = _select_resume_session(
            ws,
            preferred_source=args.source,
            agent=_normalize_source(args.source) or os.getenv("CTX_AGENT_DEFAULT"),
        )
        if _should_auto_pull(getattr(args, "auto_pull", False), getattr(args, "no_auto_pull", False)):
            auto_pull(ws, sid, preferred_source=args.source, initial_candidate=initial_candidate)
        sys.stdout.write(
            _render_loaded_output(
                ws,
                session_id=sid,
                action_label=action_label,
                focus=args.focus,
                fmt=args.format,
                brief=args.brief,
                compress=compress,
            )
        )
    elif args.cmd == "set":
        ws = ensure_workstream(args.name, set_current=True)
        sys.stdout.write(f"Current workstream: {ws['slug']} (id {ws['id']})\n")
    elif args.cmd == "rename":
        ref = args.ref
        if not ref:
            ws = current_workstream()
            if not ws:
                print("No current workstream set; provide --from or use start/resume first.", file=sys.stderr)
                return 2
            ref = str(ws["slug"])
        result = rename_workstream(ref, args.new_name)
        sys.stdout.write(
            f"Renamed workstream {result['old_slug']} -> {result['slug']}"
            + (f" (requested '{args.new_name}')" if result.get("renamed") else "")
            + "\n"
        )
    elif args.cmd == "pull":
        ws = current_workstream()
        if not ws:
            print("No current workstream set; run 'ctx set <name>' or use start/resume first.", file=sys.stderr)
            return 2
        sid, _action_label, initial_candidate = _select_resume_session(
            ws,
            preferred_source=args.source,
            agent=_normalize_source(args.source) or os.getenv("CTX_AGENT_DEFAULT"),
        )
        if args.auto or (not args.codex and not args.claude):
            ok, who = auto_pull(ws, sid, preferred_source=args.source, initial_candidate=initial_candidate)
            sys.stdout.write((who or "none") + ("\n" if ok else "\n"))
        else:
            if args.codex:
                ingest_latest_from_codex(ws, sid)
            if args.claude:
                ingest_latest_from_claude(ws, sid)
    elif args.cmd == "web":
        web_args = ["web", "--host", args.host, "--port", str(args.port)]
        if args.open:
            web_args.append("--open")
        return run_ctx_passthrough(web_args)
    elif args.cmd == "start":
        compress = _should_compress(getattr(args, "compress", False), getattr(args, "no_compress", False))
        # Start a new workstream and create its first session. If the name
        # already exists, ctx creates a suffixed variant like "name (1)".
        ws = ensure_workstream(args.name, set_current=True, unique_if_exists=True)
        sid = _create_session_for_workstream(ws, agent=args.agent)
        if args.pull:
            args.copy_frontmost = True
            args.from_clipboard = True
        # Pull stored agent transcript(s) first so an explicit --pull of the
        # current chat becomes the freshest context in the new session.
        if _should_auto_pull(getattr(args, "auto_pull", False), getattr(args, "no_auto_pull", False)):
            auto_pull(ws, sid, preferred_source=(args.source or args.agent))
        else:
            if args.pull_codex:
                ingest_latest_from_codex(ws, sid)
            if args.pull_claude:
                ingest_latest_from_claude(ws, sid)
        # Optional: capture clipboard (optionally copying from frontmost first)
        if args.copy_frontmost:
            # Best-effort: requires Accessibility permissions
            try:
                subprocess.check_call(
                    ["osascript", "-e", 'tell application "System Events" to keystroke "a" using {command down}'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.check_call(
                    ["osascript", "-e", 'tell application "System Events" to keystroke "c" using {command down}'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                # Non-fatal; proceed with whatever is already on the clipboard.
                pass
        if args.from_clipboard:
            try:
                clip = subprocess.check_output(["pbpaste"]).decode()
                # Ingest clipboard into the freshly created session.
                run_ctx([
                    "ingest",
                    "--file", "-",
                    "--session-id", str(sid),
                    "--format", ("markdown" if args.format == "markdown" else "auto"),
                    *( ["--source", args.source] if args.source else [] ),
                ], input_data=clip)
            except Exception:
                # Ignore clipboard failures silently to keep UX smooth
                pass
        action_label = "started new workstream and first session"
        if ws.get("renamed"):
            action_label = f"started new workstream with auto-renamed name (requested '{args.name}')"
        sys.stdout.write(
            _render_loaded_output(
                ws,
                session_id=sid,
                action_label=action_label,
                focus=args.focus,
                fmt=args.format,
                brief=args.brief,
                compress=compress,
            )
        )
    elif args.cmd == "resume":
        compress = _should_compress(getattr(args, "compress", False), getattr(args, "no_compress", False))
        ws = lookup_workstream(args.name)
        if not ws:
            sys.stdout.write(f"No workstream matching '{args.name}' exists.\n")
            return 0
        _assert_repo_guard(
            ws,
            allow_other_repo=getattr(args, "allow_other_repo", False),
            override_command=f"ctx resume {ws['slug']}",
        )
        run_ctx(["workstream-set-current", "--slug", str(ws["slug"])])
        ws = current_workstream() or ws
        sid, action_label, initial_candidate = _select_resume_session(
            ws,
            preferred_source=args.source,
            agent=_normalize_source(args.source) or os.getenv("CTX_AGENT_DEFAULT"),
        )
        # Optionally pull before emitting
        if _should_auto_pull(getattr(args, "auto_pull", False), getattr(args, "no_auto_pull", False)):
            auto_pull(ws, sid, preferred_source=args.source, initial_candidate=initial_candidate)
        else:
            if args.pull_codex:
                ingest_latest_from_codex(ws, sid)
            if args.pull_claude:
                ingest_latest_from_claude(ws, sid)
        sys.stdout.write(
            _render_loaded_output(
                ws,
                session_id=sid,
                action_label=action_label,
                focus=args.focus,
                fmt=args.format,
                brief=args.brief,
                compress=compress,
            )
        )
    elif args.cmd == "branch":
        compress = _should_compress(getattr(args, "compress", False), getattr(args, "no_compress", False))
        source_ws = lookup_workstream(args.source_name)
        if not source_ws:
            print(f"Source workstream '{args.source_name}' not found", file=sys.stderr)
            return 1
        _assert_repo_guard(
            source_ws,
            allow_other_repo=getattr(args, "allow_other_repo", False),
            override_command=f"ctx branch {args.source_name} {args.target_name}",
        )
        existing_target = lookup_workstream(args.target_name)
        if existing_target:
            print(
                f"Target workstream '{args.target_name}' already exists; choose a new branch name",
                file=sys.stderr,
            )
            return 1
        target_ws = ensure_workstream(args.target_name, set_current=True)
        sid = _clone_workstream_snapshot(
            source_ws,
            target_ws,
            default_agent=args.agent,
        )
        sys.stdout.write(
            _render_loaded_output(
                target_ws,
                session_id=sid,
                action_label=f"branched from {source_ws['slug']}",
                focus=args.focus,
                fmt=args.format,
                brief=args.brief,
                compress=compress,
            )
        )
    elif args.cmd == "delete":
        if args.session_id is not None:
            sys.stdout.write(run_ctx(["session-delete", str(args.session_id)]))
        else:
            target = args.name or os.getenv("CTX_AGENT_WORKSTREAM")
            if not target:
                print("Provide a workstream name/slug or --session-id", file=sys.stderr)
                return 2
            ws = lookup_workstream(target)
            if not ws:
                print(f"Workstream '{target}' not found", file=sys.stderr)
                return 1
            sid = run_ctx(["session-latest", "--workstream-slug", str(ws["slug"])]).strip()
            sys.stdout.write(run_ctx(["session-delete", sid]))
    elif args.cmd == "note":
        if args.text is None and sys.stdin.isatty():
            print("Provide text or pipe stdin", file=sys.stderr)
            return 2
        if args.text is not None:
            sys.stdout.write(run_ctx(["add-latest", "--type", "note", "--text", args.text]))
        else:
            data = sys.stdin.read()
            sys.stdout.write(run_ctx(["add-latest", "--type", "note", "--text", "-"], input_data=data))
    elif args.cmd == "decision":
        sys.stdout.write(run_ctx(["add-latest", "--type", "decision", "--text", args.text[0]]))
    elif args.cmd == "todo":
        sys.stdout.write(run_ctx(["add-latest", "--type", "todo", "--text", args.text[0]]))
    elif args.cmd == "link":
        sys.stdout.write(run_ctx(["add-latest", "--type", "link", "--text", args.url]))
    elif args.cmd == "snap":
        p = Path(args.path)
        if not p.exists() or not p.is_file():
            print(f"File not found: {p}", file=sys.stderr)
            return 2
        sys.stdout.write(
            run_ctx([
                "add-latest",
                "--type",
                "file",
                "--from-file",
                str(p),
                "--snapshot",
                str(p),
            ])
        )
    elif args.cmd == "run":
        command_str = args.cmd_str.strip()
        # Use bash if available, else sh
        sh = shutil.which("bash") or shutil.which("sh")
        proc = subprocess.run([sh, "-lc", command_str], capture_output=True, text=True)
        output = proc.stdout + (proc.stderr if proc.stderr else "")
        content = f"$ {command_str}\n{output}"
        sys.stdout.write(run_ctx(["add-latest", "--type", "cmd", "--text", content]))
    elif args.cmd == "git":
        def _run(cmd):
            try:
                return subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
            except subprocess.CalledProcessError as e:
                return e.output.decode().strip()
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "(no branch)"
        last = _run(["git", "log", "-1", "--oneline"]) or "(no commits)"
        status = _run(["git", "status", "-s"]) or "(clean)"
        content = f"Git context\nBranch: {branch}\nLast: {last}\nStatus:\n{status}\n"
        sys.stdout.write(run_ctx(["add-latest", "--type", "note", "--text", content]))
    elif args.cmd == "ingest-file":
        p = Path(args.path)
        if not p.exists():
            print(f"File not found: {p}", file=sys.stderr)
            return 2
        sys.stdout.write(
            run_ctx([
                "ingest",
                "--file",
                str(p),
                "--format",
                args.format,
                *( ["--source", args.source] if args.source else [] ),
            ])
        )
    elif args.cmd == "ingest-clipboard":
        # macOS pbpaste fallback; otherwise require piping
        try:
            clip = subprocess.check_output(["pbpaste"]).decode()
        except Exception:
            print("Clipboard not available; paste content and pipe to 'ctx note' or 'python -m contextfun ingest --file -'", file=sys.stderr)
            return 2
        sys.stdout.write(
            run_ctx([
                "ingest",
                "--file",
                "-",
                "--format",
                args.format,
                *( ["--source", args.source] if args.source else [] ),
            ], input_data=clip)
        )
    elif args.cmd is None:
        ws = current_workstream()
        if not ws:
            sys.stdout.write("No current workstream set.\n")
            return 0
        sys.stdout.write(f"Current workstream: {ws['slug']} (id {ws['id']})\n")
    else:
        p.print_help()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
