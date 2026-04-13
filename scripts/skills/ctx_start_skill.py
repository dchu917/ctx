#!/usr/bin/env python3
import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
import typing


ROOT = Path(__file__).resolve().parents[2]
CTX_CMD = ROOT / "scripts" / "ctx_cmd.py"

def _ctx_invocation() -> list:
    try:
        import shutil as _sh
        exe = _sh.which("ctx")
    except Exception:
        exe = None
    if exe:
        return [exe]
    return ["python3", str(CTX_CMD)]


def _db_path() -> Path:
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
    # If name provided, ensure and set current via ctx_cmd
    if not name:
        name = os.getenv("CTX_AGENT_WORKSTREAM") or None
    if name:
        subprocess.check_output(_ctx_invocation() + ["set", name])
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM workstream WHERE slug = ? OR title = ? ORDER BY id DESC LIMIT 1",
                (name, name),
            ).fetchone()
            if not row:
                raise SystemExit("Failed to ensure workstream")
            return {"id": int(row["id"]), "slug": row["slug"], "title": row["title"]}
    # Else prefer current.json if present, else latest by id
    cur_file = Path.cwd() / ".contextfun" / "current.json"
    if cur_file.exists():
        try:
            import json

            cur = json.loads(cur_file.read_text(encoding="utf-8"))
            return {"id": int(cur["id"]), "slug": cur["slug"], "title": cur.get("title", cur["slug"])}
        except Exception:
            pass
    with _connect() as conn:
        row = conn.execute("SELECT * FROM workstream ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            raise SystemExit("No workstreams found. Provide a name, e.g., --name my-stream")
        return {"id": int(row["id"]), "slug": row["slug"], "title": row["title"]}


def _create_session(agent: str, workstream_slug: typing.Optional[str] = None, workstream_id: typing.Optional[int] = None) -> int:
    db = str(_db_path())
    cmd = [
        "python3", "-m", "contextfun", "--db", db, "session-new", "New session", "--agent", agent,
    ]
    if workstream_slug:
        cmd += ["--workstream-slug", workstream_slug]
    elif workstream_id:
        cmd += ["--workstream-id", str(workstream_id)]
    out = subprocess.check_output(cmd)
    try:
        return int(out.decode().strip())
    except Exception:
        return -1


def _auto_pull():
    try:
        subprocess.check_call(_ctx_invocation() + ["pull", "--auto"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        pass


def _pack(slug: str, fmt: str = "markdown") -> str:
    out = subprocess.check_output(_ctx_invocation() + ["resume", slug, "--format", fmt])
    return out.decode()


def _ingest_from_frontmost(workstream_slug: str, fmt: str = "markdown", source: typing.Optional[str] = None) -> None:
    # macOS: select all + copy the chat content from frontmost app, then ingest into the latest session of the workstream
    try:
        subprocess.check_call(["osascript", "-e", 'tell application "System Events" to keystroke "a" using {command down}'])
        subprocess.check_call(["osascript", "-e", 'tell application "System Events" to keystroke "c" using {command down}'])
    except Exception:
        # Best-effort; continue with whatever is on clipboard
        pass
    try:
        clip = subprocess.check_output(["pbpaste"]).decode()
    except Exception:
        return
    args = [
        "python3", "-m", "contextfun", "ingest",
        "--workstream-slug", workstream_slug,
        "--file", "-",
        "--format", fmt,
    ]
    if source:
        args += ["--source", source]
    try:
        proc = subprocess.run(args, input=clip.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _ = proc.returncode  # ignore
    except Exception:
        pass


def _last_entry_preview(workstream_id: int, max_len: int = 200) -> typing.Optional[typing.Tuple[str, str]]:
    sql = (
        "SELECT e.type, e.content FROM entry e "
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


def _paste_frontmost() -> bool:
    try:
        subprocess.check_call(["osascript", "-e", 'tell application "System Events" to keystroke "v" using {command down}'])
        return True
    except Exception:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ctx skill: start new session, auto-pull, copy pack, and print a status line")
    ap.add_argument("--name", help="Workstream slug or title (optional; defaults to current or latest)")
    ap.add_argument("--agent", default=os.getenv("CTX_AGENT_DEFAULT", "other"))
    # Single format flag controls both ingest and pack output
    ap.add_argument("--no-pack", action="store_true", help="Skip generating the pack; just ingest and report")
    ap.add_argument("--no-copy", action="store_true", help="Do not copy pack to clipboard")
    ap.add_argument("--paste", action="store_true", help="macOS: paste into frontmost app after copying")
    ap.add_argument("--pull", action="store_true", help="macOS: copy the current chat (Cmd+A/C) and ingest into this new session before packing")
    ap.add_argument("--format", default="markdown", choices=["text", "markdown"], help="Ingest/pack format")
    ap.add_argument("--source", default=os.getenv("CTX_SOURCE_DEFAULT"), help="Source label for ingest (e.g., claude, codex)")
    args = ap.parse_args(argv)

    ws = _ensure_workstream(args.name)
    sid = _create_session(agent=args.agent, workstream_slug=ws.get("slug"), workstream_id=ws.get("id"))
    _auto_pull()
    if args.pull:
        _ingest_from_frontmost(workstream_slug=ws["slug"], fmt=args.format, source=args.source)

    pack_text = ""
    if not args.no_pack:
        pack_text = _pack(ws["slug"], fmt=args.format)
        if not args.no_copy:
            _copy(pack_text)
            if args.paste:
                _paste_frontmost()

    last = _last_entry_preview(ws["id"]) or ("n/a", "No entries yet")
    typ, preview = last
    s_part = f" S{sid}" if sid and sid > 0 else ""
    status = f"Context for workstream [{ws['slug']}] ingested.{s_part} created. Last: {typ} — {preview}"
    sys.stdout.write(status + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
