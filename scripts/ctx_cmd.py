#!/usr/bin/env python3
import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
import shutil
import json
from typing import List, Dict, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
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


def ensure_workstream(name, set_current=False):
    args = ["workstream-ensure", name]
    if set_current:
        args.append("--set-current")
    args.append("--json")
    out = run_ctx(args)
    import json

    return json.loads(out)


def create_session(agent=None):
    title = "New session"
    args = ["session-new", title]
    if agent:
        args += ["--agent", agent]
    return run_ctx(args).strip()


def pack(slug, focus=None, fmt="markdown", brief=False):
    args = ["resume", "--workstream-slug", slug, "--format", fmt]
    if focus:
        args += ["--focus", focus]
    if brief:
        args.append("--brief")
    return run_ctx(args)


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


# -------- Transcript ingestion helpers --------

def _expanduser(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def _latest_jsonl_under(root: Path, name_hint: Optional[str] = None) -> Optional[Path]:
    latest: Tuple[float, Optional[Path]] = (0.0, None)
    if not root.exists():
        return None
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not (f.endswith(".jsonl") or f.endswith(".json")):
                continue
            if name_hint and name_hint not in f:
                # prefer name-hinted files
                pass
            p = Path(dirpath) / f
            try:
                m = p.stat().st_mtime
                if m >= latest[0]:
                    latest = (m, p)
            except Exception:
                continue
    return latest[1]


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
                        role = obj.get("role") or obj.get("sender")
                        text = obj.get("content") or obj.get("text")
                        if isinstance(text, list):
                            text = "\n".join([c for c in text if isinstance(c, str)])
                        if text:
                            msgs.append({"role": role or "system", "content": text})
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
            role = None
            text = None
            # Common shapes
            if isinstance(obj, dict):
                role = obj.get("role") or obj.get("sender")
                text = obj.get("content") or obj.get("text")
                # Event-shaped
                t = obj.get("type") or obj.get("event")
                if not role and isinstance(t, str):
                    tl = t.lower()
                    if "assistant" in tl:
                        role = "assistant"
                    elif "user" in tl:
                        role = "user"
                # Blocks-shaped content
                if isinstance(text, list):
                    parts = []
                    for b in text:
                        if isinstance(b, str):
                            parts.append(b)
                        elif isinstance(b, dict):
                            val = b.get("text") or b.get("content")
                            if isinstance(val, str):
                                parts.append(val)
                    text = "\n".join([p for p in parts if p]) if parts else None
                if text is None and "message" in obj and isinstance(obj["message"], dict):
                    text = obj["message"].get("text") or obj["message"].get("content")
            if text:
                msgs.append({"role": role or "system", "content": text})
    except Exception:
        pass
    return msgs


def ingest_messages(messages: List[Dict[str, str]], source_label: Optional[str]) -> None:
    if not messages:
        return
    payload = json.dumps({"messages": messages})
    run_ctx([
        "ingest", "--file", "-", "--format", "json",
        *( ["--source", source_label] if source_label else [] ),
    ], input_data=payload)


def find_latest_codex_transcript() -> Optional[Path]:
    codex_home = _expanduser(os.getenv("CODEX_HOME", "~/.codex"))
    sessions = codex_home / "sessions"
    # Prefer files named transcript.jsonl if present; otherwise newest .jsonl
    p = _latest_jsonl_under(sessions)
    return p


def find_latest_claude_transcript() -> Optional[Path]:
    claude_home = _expanduser(os.getenv("CLAUDE_HOME", "~/.claude"))
    projects = claude_home / "projects"
    p = _latest_jsonl_under(projects)
    return p


def ingest_latest_from_codex(source_label: Optional[str] = None) -> bool:
    p = find_latest_codex_transcript()
    if not p:
        return False
    msgs = _read_jsonl_messages(p)
    ingest_messages(msgs, source_label or "codex")
    return True


def ingest_latest_from_claude(source_label: Optional[str] = None) -> bool:
    p = find_latest_claude_transcript()
    if not p:
        return False
    msgs = _read_jsonl_messages(p)
    ingest_messages(msgs, source_label or "claude")
    return True


def auto_pull() -> Tuple[bool, Optional[str]]:
    pc = find_latest_codex_transcript()
    pa = find_latest_claude_transcript()
    candidates: List[Tuple[float, str, Path]] = []
    if pc and pc.exists():
        candidates.append((pc.stat().st_mtime, "codex", pc))
    if pa and pa.exists():
        candidates.append((pa.stat().st_mtime, "claude", pa))
    if not candidates:
        return False, None
    candidates.sort(key=lambda t: t[0], reverse=True)
    who = candidates[0][1]
    if who == "codex":
        ok = ingest_latest_from_codex("codex")
    else:
        ok = ingest_latest_from_claude("claude")
    return ok, who


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


def list_workstreams():
    return run_ctx(["workstream-list"]).rstrip()


def main():
    p = argparse.ArgumentParser(description="Slash-like /ctx helper")
    sub = p.add_subparsers(dest="cmd")

    p_new = sub.add_parser("new", help="/ctx --new <name>")
    p_new.add_argument("name")
    p_new.add_argument("--agent", default=os.getenv("CTX_AGENT_DEFAULT", "other"))
    p_new.add_argument("--focus")
    p_new.add_argument("--format", default="markdown", choices=["text", "markdown"])
    p_new.add_argument("--brief", action="store_true")

    p_list = sub.add_parser("list", help="/ctx list")

    p_go = sub.add_parser("go", help="/ctx <name>")
    p_go.add_argument("name")
    p_go.add_argument("--focus")
    p_go.add_argument("--format", default="markdown", choices=["text", "markdown"])
    p_go.add_argument("--brief", action="store_true")
    p_go.add_argument("--auto-pull", action="store_true", help="Import newest Codex/Claude transcript before emitting pack (default on; see CTX_AUTOPULL_DEFAULT)")
    p_go.add_argument("--no-auto-pull", action="store_true", help="Disable auto-pull for this invocation")

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

    p_resume2 = sub.add_parser("resume", help="Ensure workstream and emit pack (alias of 'go')")
    p_resume2.add_argument("name", help="Workstream name or slug")
    p_resume2.add_argument("--focus")
    p_resume2.add_argument("--format", default="markdown", choices=["text", "markdown"])
    p_resume2.add_argument("--brief", action="store_true")
    p_resume2.add_argument("--pull-codex", action="store_true", help="Import latest Codex transcript into the latest session before emitting pack")
    p_resume2.add_argument("--pull-claude", action="store_true", help="Import latest Claude Code transcript into the latest session before emitting pack")
    p_resume2.add_argument("--auto-pull", action="store_true", help="Import the newest transcript between Codex and Claude before emitting pack (default on; see CTX_AUTOPULL_DEFAULT)")
    p_resume2.add_argument("--no-auto-pull", action="store_true", help="Disable auto-pull for this invocation")

    p_delete = sub.add_parser("delete", help="Delete a session by id, or delete the latest session in a workstream")
    p_delete.add_argument("name", nargs="?", help="Workstream slug or title; deletes the latest session in that workstream")
    p_delete.add_argument("--session-id", type=int, help="Delete this specific session id")

    # Hidden expert command: pull transcripts explicitly
    p_pull = sub.add_parser("pull", help="Pull transcript(s) from Codex/Claude and ingest into the latest session")
    p_pull.add_argument("--codex", action="store_true")
    p_pull.add_argument("--claude", action="store_true")
    p_pull.add_argument("--auto", action="store_true")
    p_pull.add_argument("--source")

    # Optional: set current workstream easily
    p_set = sub.add_parser("set", help="Set current workstream by slug or name (ensures if missing)")
    p_set.add_argument("name")

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
        ws = ensure_workstream(args.name, set_current=True)
        create_session(agent=args.agent)
        sys.stdout.write(pack(ws["slug"], focus=args.focus, fmt=args.format, brief=args.brief))
    elif args.cmd == "list":
        sys.stdout.write(list_workstreams() + "\n")
    elif args.cmd == "go":
        ws = ensure_workstream(args.name, set_current=True)
        if _should_auto_pull(getattr(args, "auto_pull", False), getattr(args, "no_auto_pull", False)):
            auto_pull()
        sys.stdout.write(pack(ws["slug"], focus=args.focus, fmt=args.format, brief=args.brief))
    elif args.cmd == "set":
        ws = ensure_workstream(args.name, set_current=True)
        sys.stdout.write(f"Current workstream: {ws['slug']} (id {ws['id']})\n")
    elif args.cmd == "pull":
        # Pull transcripts into the latest session of the current workstream
        sources: List[Tuple[str, Optional[str]]] = []
        if args.auto or (not args.codex and not args.claude):
            ok, who = auto_pull()
            sys.stdout.write((who or "none") + ("\n" if ok else "\n"))
        else:
            if args.codex:
                ingest_latest_from_codex(source_label=args.source)
            if args.claude:
                ingest_latest_from_claude(source_label=args.source)
    elif args.cmd == "start":
        # Ensure workstream and create a fresh session
        ws = ensure_workstream(args.name, set_current=True)
        create_session(agent=args.agent)
        if args.pull:
            args.copy_frontmost = True
            args.from_clipboard = True
        # Pull stored agent transcript(s) first so an explicit --pull of the
        # current chat becomes the freshest context in the new session.
        if _should_auto_pull(getattr(args, "auto_pull", False), getattr(args, "no_auto_pull", False)):
            auto_pull()
        else:
            if args.pull_codex:
                ingest_latest_from_codex(source_label=(args.source or "codex"))
            if args.pull_claude:
                ingest_latest_from_claude(source_label=(args.source or "claude"))
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
                # Ingest clipboard into latest session of current workstream
                run_ctx([
                    "ingest",
                    "--file", "-",
                    "--format", ("markdown" if args.format == "markdown" else "auto"),
                    *( ["--source", args.source] if args.source else [] ),
                ], input_data=clip)
            except Exception:
                # Ignore clipboard failures silently to keep UX smooth
                pass
        # Finally, emit a pack so it can be pasted into the chat
        sys.stdout.write(pack(ws["slug"], focus=args.focus, fmt=args.format, brief=args.brief))
    elif args.cmd == "resume":
        ws = ensure_workstream(args.name, set_current=True)
        # Optionally pull before emitting
        if _should_auto_pull(getattr(args, "auto_pull", False), getattr(args, "no_auto_pull", False)):
            auto_pull()
        else:
            if args.pull_codex:
                ingest_latest_from_codex(source_label="codex")
            if args.pull_claude:
                ingest_latest_from_claude(source_label="claude")
        sys.stdout.write(pack(ws["slug"], focus=args.focus, fmt=args.format, brief=args.brief))
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
    else:
        p.print_help()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
