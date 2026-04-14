from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .cli import (
    _current_workspace_path,
    _delete_entry_attachments,
    _delete_search_docs_for_entry,
    _entry_load_behavior,
    _entry_role,
    _effective_workspace_for_workstream,
    _fts_query,
    _fts_tokens,
    _get_current_workstream,
    _looks_like_ctx_noise,
    _preview_text,
    _set_entry_load_behavior,
    _set_current_workstream,
    _table_exists,
    _load_control_counts,
    _repo_scope_match,
    _workspace_relation,
    _workstream_one_line_summary,
    connect,
    init_db,
)


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
ASSET_DIR = PACKAGE_DIR / "web_assets"


def _goal_text(row: sqlite3.Row) -> str:
    meta = {}
    if row["metadata"]:
        try:
            meta = json.loads(row["metadata"]) or {}
        except Exception:
            meta = {}
    return (
        str(meta.get("summary") or "").strip()
        or (row["description"] or "").strip()
        or (row["title"] or "").strip()
    )


def _workstream_latest_preview(conn: sqlite3.Connection, workstream_id: int) -> str:
    latest_session = conn.execute(
        "SELECT title FROM session WHERE workstream_id = ? ORDER BY id DESC LIMIT 1",
        (workstream_id,),
    ).fetchone()
    latest_entries = conn.execute(
        """
        SELECT e.content
        , e.extras
        FROM entry e
        JOIN session s ON s.id = e.session_id
        WHERE s.workstream_id = ?
        ORDER BY e.id DESC
        LIMIT 20
        """,
        (workstream_id,),
    ).fetchall()
    if latest_session and latest_session["title"] not in {"New session", "Auto-ingest session"}:
        latest = latest_session["title"]
    else:
        latest = ""
    for row in latest_entries:
        if _entry_load_behavior(row) == "exclude":
            continue
        if row["content"] and not _looks_like_ctx_noise(row["content"]):
            latest = _preview_text(row["content"], limit=120)
            break
    if not latest:
        for row in latest_entries:
            if _entry_load_behavior(row) == "exclude":
                continue
            if row["content"]:
                latest = _preview_text(row["content"], limit=120)
                break
    return latest or "No sessions yet"


def _split_ctx_output(text: str) -> dict:
    if "<ctx-pack>" not in text:
        return {"summary": text.strip(), "pack": "", "raw": text}
    before, after = text.split("<ctx-pack>", 1)
    pack, _sep, _rest = after.partition("</ctx-pack>")
    return {"summary": before.strip(), "pack": pack.strip(), "raw": text}


class CtxWebApp:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).resolve()
        self.launch_cwd = Path.cwd().resolve()
        os.environ["CONTEXTFUN_DB"] = str(self.db_path)
        init_db(self.db_path, quiet=True)

    def _ctx_invocation(self) -> list[str]:
        repo_script = REPO_ROOT / "scripts" / "ctx_cmd.py"
        if repo_script.exists():
            return [sys.executable, str(repo_script)]
        exe = shutil.which("ctx")
        if exe:
            return [exe]
        raise RuntimeError("ctx command not found; run ./setup.sh or install ctx first")

    def _ctx_env(self) -> dict:
        env = os.environ.copy()
        env["CONTEXTFUN_DB"] = str(self.db_path)
        return env

    def _run_ctx(self, args: list[str], input_text: str | None = None) -> dict:
        proc = subprocess.run(
            self._ctx_invocation() + args,
            cwd=str(self.launch_cwd),
            env=self._ctx_env(),
            input=input_text,
            capture_output=True,
            text=True,
        )
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def current(self) -> dict | None:
        cur = _get_current_workstream()
        if not cur:
            return None
        return {
            "id": int(cur["id"]),
            "slug": cur["slug"],
            "title": cur.get("title", cur["slug"]),
        }

    def _workstream_sources(self, conn: sqlite3.Connection, workstream_id: int) -> list[str]:
        sources: set[str] = set()
        if _table_exists(conn, "session_source_link"):
            for row in conn.execute(
                "SELECT DISTINCT source FROM session_source_link WHERE workstream_id = ?",
                (workstream_id,),
            ).fetchall():
                source = str(row["source"] or "").strip().lower()
                if source:
                    sources.add(source)
        if not sources:
            for row in conn.execute(
                "SELECT DISTINCT agent FROM session WHERE workstream_id = ?",
                (workstream_id,),
            ).fetchall():
                agent = str(row["agent"] or "").strip().lower()
                if agent in {"claude", "codex"}:
                    sources.add(agent)
        return sorted(sources)

    def workstreams(self, query: str | None = None, scope: str | None = None) -> list[dict]:
        sql = """
            SELECT
                w.*,
                COUNT(DISTINCT s.id) AS session_count,
                COUNT(e.id) AS entry_count,
                MAX(COALESCE(e.created_at, s.created_at, w.created_at)) AS last_activity_at
            FROM workstream w
            LEFT JOIN session s ON s.workstream_id = w.id
            LEFT JOIN entry e ON e.session_id = s.id
            WHERE 1 = 1
        """
        params: list[object] = []
        if query:
            sql += " AND (w.slug LIKE ? OR w.title LIKE ? OR w.description LIKE ?)"
            like = f"%{query}%"
            params.extend([like, like, like])
        sql += " GROUP BY w.id ORDER BY w.id DESC"
        current = self.current()
        current_id = int(current["id"]) if current else None
        current_workspace = _current_workspace_path()
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            items = []
            for row in rows:
                sources = self._workstream_sources(conn, int(row["id"]))
                effective_workspace = _effective_workspace_for_workstream(conn, row)
                repo_relation = _workspace_relation(current_workspace, effective_workspace)
                items.append(
                    {
                        "id": int(row["id"]),
                        "slug": row["slug"],
                        "title": row["title"],
                        "description": row["description"] or "",
                        "workspace": effective_workspace,
                        "workspace_explicit": row["workspace"] or "",
                        "repo_relation": repo_relation,
                        "repo_name": Path(effective_workspace).name if effective_workspace else "",
                        "created_at": row["created_at"],
                        "goal": _goal_text(row),
                        "latest": _workstream_latest_preview(conn, int(row["id"])),
                        "summary": _workstream_one_line_summary(conn, row),
                        "session_count": int(row["session_count"] or 0),
                        "entry_count": int(row["entry_count"] or 0),
                        "last_activity_at": row["last_activity_at"] or row["created_at"],
                        "sources": sources,
                        "current": current_id == int(row["id"]),
                    }
                )
        normalized_scope = str(scope or "all").strip().lower()
        items = [item for item in items if _repo_scope_match(current_workspace, item["workspace"], normalized_scope)]
        items.sort(key=lambda item: (0 if item["repo_relation"] == "current" else 1, -item["id"]))
        return items

    def workstream_detail(self, slug: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workstream WHERE slug = ?", (slug,)).fetchone()
            if not row:
                return None
            sessions = conn.execute(
                """
                SELECT
                    s.*,
                    COUNT(e.id) AS entry_count,
                    MAX(e.created_at) AS latest_entry_at
                FROM session s
                LEFT JOIN entry e ON e.session_id = s.id
                WHERE s.workstream_id = ?
                GROUP BY s.id
                ORDER BY s.id DESC
                LIMIT 20
                """,
                (row["id"],),
            ).fetchall()
            session_ids = [int(s["id"]) for s in sessions]
            session_links: dict[int, list[dict]] = {sid: [] for sid in session_ids}
            if session_ids and _table_exists(conn, "session_source_link"):
                marks = ",".join("?" for _ in session_ids)
                for link in conn.execute(
                    f"""
                    SELECT session_id, source, external_session_id, transcript_path, updated_at, message_count
                    FROM session_source_link
                    WHERE session_id IN ({marks})
                    ORDER BY updated_at DESC, id DESC
                    """,
                    session_ids,
                ).fetchall():
                    session_links[int(link["session_id"])].append(
                        {
                            "source": link["source"],
                            "external_session_id": link["external_session_id"],
                            "transcript_path": link["transcript_path"] or "",
                            "updated_at": link["updated_at"],
                            "message_count": int(link["message_count"] or 0),
                        }
                    )
            recent_entries = conn.execute(
                """
                SELECT
                    e.id,
                    e.session_id,
                    e.type,
                    e.content,
                    e.extras,
                    e.created_at,
                    s.title AS session_title
                FROM entry e
                JOIN session s ON s.id = e.session_id
                WHERE s.workstream_id = ?
                ORDER BY e.id DESC
                LIMIT 80
                """,
                (row["id"],),
            ).fetchall()
            meaningful = []
            for entry in recent_entries:
                if _entry_load_behavior(entry) == "exclude":
                    meaningful.append(entry)
                elif entry["content"] and not _looks_like_ctx_noise(entry["content"]):
                    meaningful.append(entry)
                if len(meaningful) >= 20:
                    break
            if not meaningful:
                meaningful = recent_entries[:20]
            current = self.current()
            current_workspace = _current_workspace_path()
            effective_workspace = _effective_workspace_for_workstream(conn, row)
            repo_relation = _workspace_relation(current_workspace, effective_workspace)
            pinned_count, excluded_count = _load_control_counts(conn, int(row["id"]))
            return {
                "workstream": {
                    "id": int(row["id"]),
                    "slug": row["slug"],
                    "title": row["title"],
                    "description": row["description"] or "",
                    "workspace": effective_workspace,
                    "workspace_explicit": row["workspace"] or "",
                    "repo_relation": repo_relation,
                    "repo_name": Path(effective_workspace).name if effective_workspace else "",
                    "current_workspace": current_workspace,
                    "created_at": row["created_at"],
                    "goal": _goal_text(row),
                    "summary": _workstream_one_line_summary(conn, row),
                    "current": bool(current and int(current["id"]) == int(row["id"])),
                    "pinned_count": pinned_count,
                    "excluded_count": excluded_count,
                },
                "sessions": [
                    {
                        "id": int(s["id"]),
                        "title": s["title"],
                        "agent": s["agent"] or "other",
                        "created_at": s["created_at"],
                        "entry_count": int(s["entry_count"] or 0),
                        "latest_entry_at": s["latest_entry_at"] or s["created_at"],
                        "links": session_links.get(int(s["id"]), []),
                    }
                    for s in sessions
                ],
                "recent_entries": [
                    {
                        "id": int(e["id"]),
                        "session_id": int(e["session_id"]),
                        "type": e["type"],
                        "role": _entry_role(e),
                        "load_behavior": _entry_load_behavior(e),
                        "preview": _preview_text(e["content"], limit=240),
                        "created_at": e["created_at"],
                        "session_title": e["session_title"],
                    }
                    for e in meaningful
                ],
            }

    def set_entry_load_behavior(self, entry_id: int, mode: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT e.id, e.session_id, s.workstream_id, w.slug AS workstream_slug
                FROM entry e
                JOIN session s ON s.id = e.session_id
                LEFT JOIN workstream w ON w.id = s.workstream_id
                WHERE e.id = ?
                """,
                (entry_id,),
            ).fetchone()
            if not row:
                return {"ok": False, "code": 404, "stdout": "", "stderr": f"Entry {entry_id} not found"}
            _set_entry_load_behavior(conn, entry_id, mode)
            conn.commit()
            slug = row["workstream_slug"] or ""
        return {
            "ok": True,
            "code": 0,
            "stdout": f"Entry {entry_id} load behavior set to {mode}",
            "stderr": "",
            "detail_slug": slug,
        }

    def delete_entry(self, entry_id: int) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT e.id, e.session_id, e.type, s.workstream_id, w.slug AS workstream_slug
                FROM entry e
                JOIN session s ON s.id = e.session_id
                LEFT JOIN workstream w ON w.id = s.workstream_id
                WHERE e.id = ?
                """,
                (entry_id,),
            ).fetchone()
            if not row:
                return {"ok": False, "code": 404, "stdout": "", "stderr": f"Entry {entry_id} not found"}
            _delete_search_docs_for_entry(conn, entry_id)
            conn.execute("DELETE FROM entry WHERE id = ?", (entry_id,))
            conn.commit()
            slug = row["workstream_slug"] or ""
            session_id = int(row["session_id"])
        _delete_entry_attachments(self.db_path, session_id, entry_id)
        return {
            "ok": True,
            "code": 0,
            "stdout": f"Deleted entry {entry_id}",
            "stderr": "",
            "detail_slug": slug,
        }

    def search(self, query: str, limit: int = 8, scope: str | None = None) -> dict:
        with self._connect() as conn:
            current_workspace = _current_workspace_path()
            tokens = _fts_tokens(query)
            fts_q = _fts_query(tokens, "AND")
            search_mode = "strict"
            rows = []
            if _table_exists(conn, "search_index") and fts_q:
                def fts_rows(match_q: str):
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
                        (match_q, max(limit * 4, 12)),
                    ).fetchall()

                rows = fts_rows(fts_q)
                if not rows and len(tokens) > 1:
                    loose_q = _fts_query(tokens, "OR")
                    if loose_q and loose_q != fts_q:
                        rows = fts_rows(loose_q)
                        if rows:
                            search_mode = "loose-or"
            normalized_scope = str(scope or "all").strip().lower()
            filtered_rows = []
            workspace_cache: dict[int, str] = {}
            for row in rows:
                wsid = int(row["workstream_id"]) if row["workstream_id"] else None
                if wsid is None:
                    continue
                if wsid not in workspace_cache:
                    ws_row = conn.execute("SELECT * FROM workstream WHERE id = ?", (wsid,)).fetchone()
                    workspace_cache[wsid] = _effective_workspace_for_workstream(conn, ws_row) if ws_row else ""
                if _repo_scope_match(current_workspace, workspace_cache[wsid], normalized_scope):
                    filtered_rows.append(row)
            rows = filtered_rows
            if not rows:
                like = f"%{query}%"
                rows = conn.execute(
                    """
                    SELECT
                        'entry' AS kind,
                        s.workstream_id AS workstream_id,
                        e.session_id AS session_id,
                        e.id AS entry_id,
                        w.slug AS workstream_slug,
                        w.title AS workstream_title,
                        s.title AS session_title,
                        e.created_at AS created_at,
                        e.content AS snippet,
                        999.0 AS score
                    FROM entry e
                    JOIN session s ON s.id = e.session_id
                    LEFT JOIN workstream w ON w.id = s.workstream_id
                    WHERE e.content LIKE ? OR s.title LIKE ? OR w.slug LIKE ? OR w.title LIKE ?
                    ORDER BY e.id DESC
                    LIMIT ?
                    """,
                    (like, like, like, like, max(limit * 4, 12)),
                ).fetchall()
                search_mode = "fallback-like"
                filtered_rows = []
                workspace_cache = {}
                for row in rows:
                    wsid = int(row["workstream_id"]) if row["workstream_id"] else None
                    if wsid is None:
                        continue
                    if wsid not in workspace_cache:
                        ws_row = conn.execute("SELECT * FROM workstream WHERE id = ?", (wsid,)).fetchone()
                        workspace_cache[wsid] = _effective_workspace_for_workstream(conn, ws_row) if ws_row else ""
                    if _repo_scope_match(current_workspace, workspace_cache[wsid], normalized_scope):
                        filtered_rows.append(row)
                rows = filtered_rows
            kind_priority = {"entry": 0, "session": 1, "workstream": 2}
            grouped: dict[str, dict] = {}
            for row in rows:
                wsid = str(row["workstream_id"] or "")
                info = grouped.setdefault(
                    wsid,
                    {
                        "slug": row["workstream_slug"] or "(unscoped)",
                        "title": row["workstream_title"] or "(no title)",
                        "score": float(row["score"]),
                        "hits": 0,
                        "snippet": row["snippet"] or "",
                        "kind": row["kind"],
                    },
                )
                info["hits"] += 1
                if float(row["score"]) < float(info["score"]):
                    info["score"] = float(row["score"])
                if row["snippet"] and (
                    not info["snippet"]
                    or kind_priority.get(str(row["kind"]), 99) < kind_priority.get(str(info["kind"]), 99)
                ):
                    info["snippet"] = row["snippet"]
                    info["kind"] = row["kind"]
            workstreams = []
            for wsid, info in sorted(grouped.items(), key=lambda item: (float(item[1]["score"]), -int(item[1]["hits"])))[:limit]:
                summary = ""
                if wsid:
                    ws_row = conn.execute("SELECT * FROM workstream WHERE id = ?", (int(wsid),)).fetchone()
                    if ws_row:
                        summary = _workstream_one_line_summary(conn, ws_row)
                workstreams.append(
                    {
                        "slug": info["slug"],
                        "title": info["title"],
                        "summary": summary,
                        "hits": int(info["hits"]),
                        "snippet": info["snippet"] or "",
                        "kind": info["kind"],
                    }
                )
            matches = []
            for row in sorted(rows, key=lambda item: (kind_priority.get(str(item["kind"]), 99), float(item["score"])))[:limit]:
                matches.append(
                    {
                        "kind": row["kind"],
                        "workstream_slug": row["workstream_slug"] or "",
                        "session_id": int(row["session_id"]) if row["session_id"] else None,
                        "entry_id": int(row["entry_id"]) if row["entry_id"] else None,
                        "created_at": row["created_at"],
                        "snippet": row["snippet"] or "",
                    }
                )
            return {
                "query": query,
                "mode": search_mode,
                "scope": normalized_scope or "all",
                "workstreams": workstreams,
                "matches": matches,
            }

    def set_current(self, slug: str) -> dict:
        with self._connect() as conn:
            data = _set_current_workstream(conn, slug=slug, wid=None)
            return {
                "id": int(data["id"]),
                "slug": data["slug"],
                "title": data["title"],
            }

    def start(self, name: str, agent: str, source: str | None, pasted_text: str | None) -> dict:
        args = ["start", name, "--agent", agent, "--format", "markdown"]
        if source:
            args += ["--source", source]
        result = self._run_ctx(args)
        current = self.current()
        active_slug = current["slug"] if current else name
        if result["ok"] and pasted_text and pasted_text.strip():
            detail = self.workstream_detail(active_slug)
            if detail:
                latest_session = detail["sessions"][0]["id"] if detail["sessions"] else None
                if latest_session:
                    ingest = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "contextfun",
                            "--db",
                            str(self.db_path),
                            "ingest",
                            "--session-id",
                            str(latest_session),
                            "--file",
                            "-",
                            "--format",
                            "markdown",
                            *(["--source", source] if source else []),
                        ],
                        env=self._ctx_env(),
                        input=pasted_text,
                        capture_output=True,
                        text=True,
                    )
                    if ingest.returncode == 0:
                        result = self._run_ctx(["resume", active_slug, "--format", "markdown", *(["--source", source] if source else [])])
        return result

    def resume(self, name: str, source: str | None) -> dict:
        args = ["resume", name, "--format", "markdown"]
        if source:
            args += ["--source", source]
        return self._run_ctx(args)

    def branch(self, source_name: str, target_name: str, agent: str) -> dict:
        return self._run_ctx(["branch", source_name, target_name, "--agent", agent, "--format", "markdown"])

    def delete(self, name: str | None, session_id: int | None) -> dict:
        if session_id is not None:
            return self._run_ctx(["delete", "--session-id", str(session_id)])
        if not name:
            return {"ok": False, "code": 2, "stdout": "", "stderr": "Provide a workstream name or session id"}
        return self._run_ctx(["delete", name])

    def rename(self, ref: str, new_name: str) -> dict:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "contextfun",
                "--db",
                str(self.db_path),
                "workstream-rename",
                ref,
                new_name,
                "--json",
            ],
            cwd=str(REPO_ROOT) if (REPO_ROOT / "scripts" / "ctx_cmd.py").exists() else None,
            env=self._ctx_env(),
            capture_output=True,
            text=True,
        )
        detail_slug = None
        stdout = proc.stdout
        if proc.returncode == 0:
            try:
                parsed = json.loads(proc.stdout or "{}")
                detail_slug = parsed.get("slug")
                stdout = f"Renamed workstream {parsed.get('old_slug')} -> {parsed.get('slug')}"
            except Exception:
                pass
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": stdout,
            "stderr": proc.stderr,
            "detail_slug": detail_slug,
        }


def _read_asset(name: str, content_type: str) -> tuple[bytes, str]:
    path = ASSET_DIR / name
    if not path.exists():
        raise FileNotFoundError(name)
    return path.read_bytes(), content_type


def build_handler(app: CtxWebApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def _send_json(self, payload: dict, status: int = 200) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:;")
            self.end_headers()
            self.wfile.write(data)

        def _send_asset(self, name: str, content_type: str) -> None:
            try:
                data, kind = _read_asset(name, content_type)
            except FileNotFoundError:
                self._send_json({"error": "asset not found"}, status=404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:;")
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            if path == "/" or path.startswith("/workstreams/"):
                self._send_asset("index.html", "text/html; charset=utf-8")
                return
            if path == "/app.js":
                self._send_asset("app.js", "application/javascript; charset=utf-8")
                return
            if path == "/styles.css":
                self._send_asset("styles.css", "text/css; charset=utf-8")
                return
            if path == "/api/status":
                current = app.current()
                self._send_json(
                    {
                        "db_path": str(app.db_path),
                        "current": current,
                        "workstream_count": len(app.workstreams()),
                    }
                )
                return
            if path == "/api/workstreams":
                query = (qs.get("query") or [""])[0].strip() or None
                scope = (qs.get("scope") or ["all"])[0].strip() or "all"
                self._send_json({"items": app.workstreams(query=query, scope=scope), "scope": scope})
                return
            if path.startswith("/api/workstreams/"):
                slug = unquote(path.removeprefix("/api/workstreams/"))
                detail = app.workstream_detail(slug)
                if not detail:
                    self._send_json({"error": "workstream not found"}, status=404)
                    return
                self._send_json(detail)
                return
            if path == "/api/search":
                query = (qs.get("q") or [""])[0].strip()
                limit_raw = (qs.get("limit") or ["8"])[0]
                try:
                    limit = max(1, min(20, int(limit_raw)))
                except Exception:
                    limit = 8
                if not query:
                    scope = (qs.get("scope") or ["all"])[0].strip() or "all"
                    self._send_json({"query": "", "mode": "empty", "scope": scope, "workstreams": [], "matches": []})
                    return
                scope = (qs.get("scope") or ["all"])[0].strip() or "all"
                self._send_json(app.search(query, limit=limit, scope=scope))
                return
            self._send_json({"error": "not found"}, status=404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            data = self._read_json_body()
            if parsed.path == "/api/current":
                slug = str(data.get("slug") or "").strip()
                if not slug:
                    self._send_json({"error": "slug is required"}, status=400)
                    return
                current = app.set_current(slug)
                self._send_json({"current": current})
                return
            if parsed.path == "/api/actions/start":
                name = str(data.get("name") or "").strip()
                if not name:
                    self._send_json({"error": "name is required"}, status=400)
                    return
                result = app.start(
                    name=name,
                    agent=str(data.get("agent") or "other"),
                    source=(str(data.get("source") or "").strip() or None),
                    pasted_text=str(data.get("pasted_text") or ""),
                )
            elif parsed.path == "/api/actions/resume":
                name = str(data.get("name") or "").strip()
                if not name:
                    self._send_json({"error": "name is required"}, status=400)
                    return
                result = app.resume(name=name, source=(str(data.get("source") or "").strip() or None))
            elif parsed.path == "/api/actions/branch":
                source_name = str(data.get("source_name") or "").strip()
                target_name = str(data.get("target_name") or "").strip()
                if not source_name or not target_name:
                    self._send_json({"error": "source_name and target_name are required"}, status=400)
                    return
                result = app.branch(source_name, target_name, str(data.get("agent") or "other"))
            elif parsed.path == "/api/actions/rename":
                ref = str(data.get("ref") or "").strip()
                new_name = str(data.get("new_name") or "").strip()
                if not ref or not new_name:
                    self._send_json({"error": "ref and new_name are required"}, status=400)
                    return
                result = app.rename(ref, new_name)
            elif parsed.path == "/api/actions/delete":
                session_id = data.get("session_id")
                result = app.delete(
                    name=(str(data.get("name") or "").strip() or None),
                    session_id=int(session_id) if session_id not in {None, ""} else None,
                )
            elif parsed.path == "/api/entries/load-behavior":
                entry_id = data.get("entry_id")
                mode = str(data.get("mode") or "").strip().lower()
                if entry_id in {None, ""} or mode not in {"default", "pin", "exclude"}:
                    self._send_json({"error": "entry_id and valid mode are required"}, status=400)
                    return
                result = app.set_entry_load_behavior(int(entry_id), mode)
            elif parsed.path == "/api/entries/delete":
                entry_id = data.get("entry_id")
                if entry_id in {None, ""}:
                    self._send_json({"error": "entry_id is required"}, status=400)
                    return
                result = app.delete_entry(int(entry_id))
            else:
                self._send_json({"error": "not found"}, status=404)
                return

            payload = {
                "ok": result["ok"],
                "code": result["code"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "parsed": _split_ctx_output(result["stdout"]) if result["stdout"] else {"summary": "", "pack": "", "raw": ""},
            }
            payload["current"] = app.current()
            detail_slug = ""
            if payload["current"]:
                detail_slug = str(payload["current"]["slug"])
            elif result.get("detail_slug"):
                detail_slug = str(result.get("detail_slug") or "").strip()
            elif data.get("target_name"):
                detail_slug = str(data.get("target_name") or "").strip()
            elif data.get("name"):
                detail_slug = str(data.get("name") or "").strip()
            if detail_slug:
                payload["detail"] = app.workstream_detail(detail_slug)
            status = 200 if result["ok"] else 400
            self._send_json(payload, status=status)

    return Handler


def run_server(db_path: Path, *, host: str = "127.0.0.1", port: int = 4310, open_browser_flag: bool = False) -> None:
    app = CtxWebApp(db_path)
    server = ThreadingHTTPServer((host, port), build_handler(app))
    url = f"http://{host}:{port}/"
    print(f"ctx web running at {url}")
    print(f"Using DB: {db_path}")
    if open_browser_flag:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Serve the ctx browser UI")
    parser.add_argument("--db", default=os.getenv("CONTEXTFUN_DB"), help="Path to SQLite DB")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=4310, help="Port to bind (default: 4310)")
    parser.add_argument("--open", action="store_true", help="Open the browser after starting")
    args = parser.parse_args(argv)
    db_path = Path(args.db).resolve() if args.db else (REPO_ROOT / ".contextfun" / "context.db")
    run_server(db_path, host=args.host, port=args.port, open_browser_flag=args.open)


if __name__ == "__main__":
    main()
