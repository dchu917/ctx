#!/usr/bin/env python3
import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
import typing
import shutil


ROOT = Path(__file__).resolve().parents[2]
CTX_CMD = ROOT / "scripts" / "ctx_cmd.py"

def _ctx_invocation() -> list:
    # Prefer the installed ctx shim when available.
    exe = shutil.which("ctx")
    if exe:
        return [exe]
    return ["python3", str(CTX_CMD)]


def _db_path() -> Path:
    # Prefer global if provided; otherwise project-local default
    env_db = os.getenv("CONTEXTFUN_DB")
    if env_db:
        return Path(os.path.expanduser(env_db)).resolve()
    return (Path.cwd() / ".contextfun" / "context.db").resolve()


def _connect() -> sqlite3.Connection:
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_workstream(name: typing.Optional[str]) -> dict:
    # If name is provided, ensure+set-current; else prefer current, else latest by id
    # Agent-level default: CTX_AGENT_WORKSTREAM
    if not name:
        name = os.getenv("CTX_AGENT_WORKSTREAM") or None
    if name:
        subprocess.check_output(_ctx_invocation() + ["set", name])
        # Fetch ensured row via list slugs query for robustness
        with _connect() as conn:
            row = conn.execute("SELECT * FROM workstream WHERE slug = ? OR title = ? ORDER BY id DESC LIMIT 1", (name, name)).fetchone()
            if not row:
                raise SystemExit("Failed to ensure workstream")
            return {"id": int(row["id"]), "slug": row["slug"], "title": row["title"]}
    # Try current.json
    cur_file = Path.cwd() / ".contextfun" / "current.json"
    if cur_file.exists():
        try:
            import json

            cur = json.loads(cur_file.read_text(encoding="utf-8"))
            return {"id": int(cur["id"]), "slug": cur["slug"], "title": cur.get("title", cur["slug"])}
        except Exception:
            pass
    # Fallback: latest workstream by id
    with _connect() as conn:
        row = conn.execute("SELECT * FROM workstream ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            raise SystemExit("No workstreams found. Provide a name, e.g., --name my-stream")
        return {"id": int(row["id"]), "slug": row["slug"], "title": row["title"]}


def _auto_pull():
    # Let the ctx shim decide source (Codex/Claude) via --auto
    try:
        subprocess.check_call(_ctx_invocation() + ["pull", "--auto"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # silent
    except subprocess.CalledProcessError:
        # Non-fatal; continue
        pass


def _pack(slug: str, fmt: str = "markdown") -> str:
    out = subprocess.check_output(_ctx_invocation() + ["resume", slug, "--format", fmt])
    return out.decode()


def _last_entry_preview(workstream_id: int, max_len: int = 200) -> typing.Optional[typing.Tuple[str, str]]:
    sql = (
        "SELECT e.type, e.content, e.created_at FROM entry e "
        "JOIN session s ON s.id = e.session_id "
        "WHERE s.workstream_id = ? ORDER BY e.id DESC LIMIT 1"
    )
    with _connect() as conn:
        row = conn.execute(sql, (workstream_id,)).fetchone()
        if not row:
            return None
        typ = row["type"] or "note"
        content = (row["content"] or "").strip().replace("\n", " ")
        if len(content) > max_len:
            content = content[: max_len - 3] + "..."
        return (typ, content)


def _copy(text: str) -> bool:
    try:
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(input=text.encode())
        return p.returncode == 0
    except Exception:
        return False


def _paste_frontmost():
    try:
        subprocess.check_call(["osascript", "-e", 'tell application "System Events" to keystroke "v" using {command down}'])
        return True
    except Exception:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ctx skill: resume workstream, auto-pull, paste pack, and print a status line")
    ap.add_argument("--name", help="Workstream slug or title (optional; defaults to current or latest)")
    ap.add_argument("--format", default="markdown", choices=["text", "markdown"], help="Pack format")
    ap.add_argument("--no-copy", action="store_true", help="Do not copy pack to clipboard")
    ap.add_argument("--paste", action="store_true", help="macOS: paste into frontmost app after copying")
    ap.add_argument("--no-pack", action="store_true", help="Skip generating the pack; just ingest and report")
    args = ap.parse_args(argv)

    ws = _ensure_workstream(args.name)
    _auto_pull()

    pack_text = ""
    if not args.no_pack:
        pack_text = _pack(ws["slug"], fmt=args.format)
        if not args.no_copy:
            _copy(pack_text)
            if args.paste:
                _paste_frontmost()

    last = _last_entry_preview(ws["id"]) or ("n/a", "No entries yet")
    typ, preview = last
    status = f"Context for workstream [{ws['slug']}] ingested. Last: {typ} — {preview}"
    sys.stdout.write(status + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
