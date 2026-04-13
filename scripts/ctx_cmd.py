#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "lib"


def run_ctx(args_list):
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
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, cwd=str(ROOT), env=env)
        return out.decode()
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.output.decode())
        sys.exit(e.returncode)


def ensure_workstream(name: str, set_current: bool = False):
    args = ["workstream-ensure", name]
    if set_current:
        args.append("--set-current")
    args.append("--json")
    out = run_ctx(args)
    import json

    return json.loads(out)


def create_session(agent: str | None = None):
    title = "New session"
    args = ["session-new", title]
    if agent:
        args += ["--agent", agent]
    return run_ctx(args).strip()


def pack(slug: str, focus: str | None = None, fmt: str = "markdown", brief: bool = False):
    args = ["resume", "--workstream-slug", slug, "--format", fmt]
    if focus:
        args += ["--focus", focus]
    if brief:
        args.append("--brief")
    return run_ctx(args)


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

    args = p.parse_args()

    if args.cmd == "new":
        ws = ensure_workstream(args.name, set_current=True)
        create_session(agent=args.agent)
        sys.stdout.write(pack(ws["slug"], focus=args.focus, fmt=args.format, brief=args.brief))
    elif args.cmd == "list":
        sys.stdout.write(list_workstreams() + "\n")
    elif args.cmd == "go":
        ws = ensure_workstream(args.name, set_current=True)
        sys.stdout.write(pack(ws["slug"], focus=args.focus, fmt=args.format, brief=args.brief))
    else:
        p.print_help()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
