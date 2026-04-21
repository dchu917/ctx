import importlib.util
import argparse
import contextlib
import io
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
import shutil
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CTX_CMD = ROOT / "scripts" / "ctx_cmd.py"
INSTALL_SH = ROOT / "scripts" / "install.sh"
INSTALL_SKILLS_SH = ROOT / "scripts" / "install_skills.sh"
UNINSTALL_SH = ROOT / "scripts" / "uninstall.sh"
UNINSTALL_SKILLS_SH = ROOT / "scripts" / "uninstall_skills.sh"
AGENT_SETUP_LOCAL_SH = ROOT / "scripts" / "agent_setup_local_ctx.sh"
SKILL_INSTALL_SH = ROOT / "skills" / "ctx" / "scripts" / "install_ctx.sh"
SKILL_WRAPPER_SH = ROOT / "skills" / "ctx" / "scripts" / "ctx.sh"
CLI_PY = ROOT / "contextfun" / "cli.py"
WEB_PY = ROOT / "contextfun" / "web.py"
DOCS_INDEX = ROOT / "docs" / "README.md"


def _load_ctx_cmd_module():
    spec = importlib.util.spec_from_file_location("ctx_cmd_module", CTX_CMD)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CtxReleaseSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "context.db"
        self.codex_home = Path(self.tmpdir.name) / "codex-home"
        self.claude_home = Path(self.tmpdir.name) / "claude-home"
        (self.codex_home / "sessions").mkdir(parents=True, exist_ok=True)
        (self.claude_home / "projects").mkdir(parents=True, exist_ok=True)
        self.env = os.environ.copy()
        self.env["ctx_DB"] = str(self.db_path)
        self.env["CTX_AUTOPULL_DEFAULT"] = "0"
        self.env["CODEX_HOME"] = str(self.codex_home)
        self.env["CLAUDE_HOME"] = str(self.claude_home)
        self.env["PYTHONPATH"] = str(ROOT)

    def tearDown(self):
        self.tmpdir.cleanup()

    def write_executable(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def make_release_archive(self) -> Path:
        archive_path = Path(self.tmpdir.name) / "ctx-release.tar.gz"
        if archive_path.exists():
            return archive_path

        staging_root = Path(self.tmpdir.name) / "archive-src" / "ctx-fixture"
        (staging_root / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / "contextfun", staging_root / "contextfun")
        shutil.copytree(ROOT / "skills", staging_root / "skills")
        shutil.copy2(ROOT / "scripts" / "ctx_cmd.py", staging_root / "scripts" / "ctx_cmd.py")
        shutil.copy2(ROOT / "scripts" / "install_skills.sh", staging_root / "scripts" / "install_skills.sh")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(staging_root, arcname="ctx-fixture")
        return archive_path

    def write_curl_stub(self, path: Path, archive_path: Path) -> None:
        self.write_executable(
            path,
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"cat {shlex.quote(str(archive_path))}\n",
        )

    def run_ctx(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CTX_CMD), *args],
            cwd=str(ROOT),
            env=self.env,
            capture_output=True,
            text=True,
        )

    def run_ctx_in(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CTX_CMD), *args],
            cwd=str(cwd),
            env=self.env,
            capture_output=True,
            text=True,
        )

    def write_codex_transcript(
        self,
        external_session_id: str = "11111111-1111-1111-1111-111111111111",
        *,
        cwd: str | Path | None = None,
        message: str = "Smoke transcript user message",
        mtime: float | None = None,
    ) -> Path:
        path = self.codex_home / "sessions" / f"{external_session_id}.jsonl"
        header = (
            {"type": "session_meta", "payload": {"id": external_session_id, "cwd": str(cwd)}}
            if cwd is not None
            else {"id": external_session_id}
        )
        path.write_text(
            "\n".join(
                [
                    json.dumps(header),
                    json.dumps({"role": "user", "content": message}),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def write_claude_transcript(
        self,
        external_session_id: str = "22222222-2222-2222-2222-222222222222",
        *,
        cwd: str | Path | None = None,
        message: str = "Claude transcript line",
        mtime: float | None = None,
    ) -> Path:
        project_dir = self.claude_home / "projects" / "demo-project"
        project_dir.mkdir(parents=True, exist_ok=True)
        path = project_dir / f"{external_session_id}.jsonl"
        payload = {"sessionId": external_session_id, "role": "user", "content": message}
        if cwd is not None:
            payload["cwd"] = str(cwd)
        path.write_text("\n".join([json.dumps(payload), ""]), encoding="utf-8")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_start_skips_auto_pull_by_default_even_when_global_default_is_on(self):
        self.write_codex_transcript()
        env = self.env.copy()
        env["CTX_AUTOPULL_DEFAULT"] = "1"

        proc = subprocess.run(
            [sys.executable, str(CTX_CMD), "start", "start-no-auto"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            row = conn.execute("SELECT COUNT(*) FROM entry").fetchone()

        self.assertEqual(int(row[0]), 0)

    def test_start_auto_pull_can_be_enabled_explicitly(self):
        self.write_codex_transcript()

        proc = self.run_ctx("start", "start-with-auto", "--auto-pull")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            row = conn.execute(
                "SELECT content FROM entry ORDER BY id DESC LIMIT 1"
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertIn("Smoke transcript user message", row[0])

    def test_choose_initial_candidate_prefers_current_workspace_over_newer_other_repo(self):
        ctx_cmd = _load_ctx_cmd_module()
        repo_a = Path(self.tmpdir.name) / "repo-a"
        repo_b = Path(self.tmpdir.name) / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        self.write_codex_transcript(
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            cwd=repo_b,
            message="Repo B transcript",
            mtime=100,
        )
        self.write_codex_transcript(
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            cwd=repo_a,
            message="Repo A transcript",
            mtime=200,
        )

        with mock.patch.dict(os.environ, self.env, clear=False), mock.patch.object(
            ctx_cmd, "_invocation_workspace", return_value=str(repo_b)
        ):
            candidate = ctx_cmd._choose_initial_candidate("codex")

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate["external_session_id"], "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.assertIn("Repo B transcript", candidate["messages"][-1]["content"])

    def test_choose_initial_candidate_prefers_substantive_codex_over_newer_ctx_noise_claude(self):
        ctx_cmd = _load_ctx_cmd_module()
        repo = Path(self.tmpdir.name) / "repo"
        repo.mkdir()
        self.write_codex_transcript(
            "cccccccc-cccc-cccc-cccc-cccccccccccc",
            cwd=repo,
            message="Write tests for @filename",
            mtime=100,
        )
        self.write_claude_transcript(
            "dddddddd-dddd-dddd-dddd-dddddddddddd",
            cwd=repo,
            message="/ctx resume test",
            mtime=200,
        )

        with mock.patch.dict(os.environ, self.env, clear=False), mock.patch.object(
            ctx_cmd, "_invocation_workspace", return_value=str(repo)
        ):
            candidate = ctx_cmd._choose_initial_candidate(None)

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate["source"], "codex")
        self.assertEqual(candidate["external_session_id"], "cccccccc-cccc-cccc-cccc-cccccccccccc")

    def test_load_transcript_candidate_filters_non_conversational_noise(self):
        ctx_cmd = _load_ctx_cmd_module()
        repo = Path(self.tmpdir.name) / "repo"
        repo.mkdir()
        external_session_id = "56565656-5656-5656-5656-565656565656"
        path = self.codex_home / "sessions" / f"{external_session_id}.jsonl"
        path.write_text(
            "\n".join(
                [
                    json.dumps({"type": "session_meta", "payload": {"id": external_session_id, "cwd": str(repo)}}),
                    json.dumps({"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "developer instructions"}]}}),
                    json.dumps({"role": "user", "content": "ctx resume test"}),
                    json.dumps({"role": "user", "content": "Write tests for @filename"}),
                    json.dumps({"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "arguments": "{\"cmd\":\"pwd\"}"}}),
                    json.dumps({"type": "response_item", "payload": {"type": "function_call_output", "output": "Chunk ID: demo"}}),
                    json.dumps({"role": "assistant", "content": "I’m writing the tests now."}),
                    "",
                ]
            ),
            encoding="utf-8",
        )

        candidate = ctx_cmd._load_transcript_candidate("codex", path)

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(
            candidate["messages"],
            [
                {"role": "user", "content": "Write tests for @filename"},
                {"role": "assistant", "content": "I’m writing the tests now."},
            ],
        )

    def test_resume_pull_codex_prefers_current_workspace_transcript(self):
        repo_a = Path(self.tmpdir.name) / "repo-a"
        repo_b = Path(self.tmpdir.name) / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        self.write_codex_transcript(
            "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            cwd=repo_b,
            message="Repo B transcript",
            mtime=100,
        )
        self.write_codex_transcript(
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
            cwd=repo_a,
            message="Repo A transcript",
            mtime=200,
        )

        started = self.run_ctx_in(repo_b, "start", "workspace-demo", "--no-auto-pull")
        self.assertEqual(started.returncode, 0, started.stderr)

        resumed = self.run_ctx_in(repo_b, "resume", "workspace-demo", "--pull-codex", "--no-auto-pull")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            row = conn.execute("SELECT content FROM entry ORDER BY id DESC LIMIT 1").fetchone()

        self.assertIsNotNone(row)
        self.assertIn("Repo B transcript", row[0])
        self.assertNotIn("Repo A transcript", row[0])

    def test_resume_pull_codex_prefers_codex_for_session_selection_even_if_claude_is_newer(self):
        repo = Path(self.tmpdir.name) / "repo"
        repo.mkdir()
        self.write_codex_transcript(
            "12121212-1212-1212-1212-121212121212",
            cwd=repo,
            message="Codex transcript body",
            mtime=100,
        )
        self.write_claude_transcript(
            "34343434-3434-3434-3434-343434343434",
            cwd=repo,
            message="Claude transcript body",
            mtime=200,
        )

        started = self.run_ctx_in(repo, "start", "source-bias-demo", "--no-auto-pull")
        self.assertEqual(started.returncode, 0, started.stderr)

        resumed = self.run_ctx_in(repo, "resume", "source-bias-demo", "--pull-codex", "--no-auto-pull", "--no-compress")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.row_factory = sqlite3.Row
            ws = conn.execute(
                "SELECT id FROM workstream WHERE slug = ? ORDER BY id DESC LIMIT 1",
                ("source-bias-demo",),
            ).fetchone()
            latest_session = conn.execute(
                "SELECT id, title FROM session WHERE workstream_id = ? ORDER BY id DESC LIMIT 1",
                (int(ws["id"]),),
            ).fetchone()
            links = conn.execute(
                "SELECT source, external_session_id FROM session_source_link WHERE session_id = ? ORDER BY id",
                (int(latest_session["id"]),),
            ).fetchall()
            entry = conn.execute(
                "SELECT content FROM entry WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                (int(latest_session["id"]),),
            ).fetchone()

        self.assertEqual(latest_session["title"], "Codex session")
        self.assertEqual([(row["source"], row["external_session_id"]) for row in links], [("codex", "12121212-1212-1212-1212-121212121212")])
        self.assertIn("Codex transcript body", entry["content"])

    def test_start_pull_uses_current_codex_thread_snapshot_when_available(self):
        repo = Path(self.tmpdir.name) / "repo"
        repo.mkdir()
        external_session_id = "78787878-7878-7878-7878-787878787878"
        self.write_codex_transcript(
            external_session_id,
            cwd=repo,
            message="Write tests for @filename",
            mtime=100,
        )

        env = self.env.copy()
        env["CODEX_THREAD_ID"] = external_session_id
        proc = subprocess.run(
            [sys.executable, str(CTX_CMD), "start", "pull-demo", "--pull", "--no-auto-pull"],
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Pull capture: current codex transcript was ingested.", proc.stdout)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.row_factory = sqlite3.Row
            ws = conn.execute(
                "SELECT id FROM workstream WHERE slug = ? ORDER BY id DESC LIMIT 1",
                ("pull-demo",),
            ).fetchone()
            latest_session = conn.execute(
                "SELECT id, title FROM session WHERE workstream_id = ? ORDER BY id DESC LIMIT 1",
                (int(ws["id"]),),
            ).fetchone()
            links = conn.execute(
                "SELECT source, external_session_id FROM session_source_link WHERE session_id = ? ORDER BY id",
                (int(latest_session["id"]),),
            ).fetchall()
            entry = conn.execute(
                "SELECT content FROM entry WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                (int(latest_session["id"]),),
            ).fetchone()

        self.assertEqual(latest_session["title"], "Codex session")
        self.assertEqual(list(links), [])
        self.assertIn("Write tests for @filename", entry["content"])

    def test_start_pull_falls_back_to_latest_repo_transcript_when_current_thread_is_other_repo(self):
        repo_a = Path(self.tmpdir.name) / "repo-a"
        repo_b = Path(self.tmpdir.name) / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        current_external_session_id = "89898989-8989-8989-8989-898989898989"
        latest_external_session_id = "90909090-9090-9090-9090-909090909090"
        self.write_codex_transcript(
            current_external_session_id,
            cwd=repo_a,
            message="Current other-repo transcript",
            mtime=200,
        )
        self.write_codex_transcript(
            latest_external_session_id,
            cwd=repo_b,
            message="Repo B latest transcript",
            mtime=100,
        )

        env = self.env.copy()
        env["CODEX_THREAD_ID"] = current_external_session_id
        proc = subprocess.run(
            [sys.executable, str(CTX_CMD), "start", "pull-fallback-demo", "--pull", "--no-auto-pull"],
            cwd=str(repo_b),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Pull capture: latest codex transcript for this repo was ingested.", proc.stdout)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.row_factory = sqlite3.Row
            ws = conn.execute(
                "SELECT id FROM workstream WHERE slug = ? ORDER BY id DESC LIMIT 1",
                ("pull-fallback-demo",),
            ).fetchone()
            latest_session = conn.execute(
                "SELECT id, title FROM session WHERE workstream_id = ? ORDER BY id DESC LIMIT 1",
                (int(ws["id"]),),
            ).fetchone()
            entry = conn.execute(
                "SELECT content FROM entry WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                (int(latest_session["id"]),),
            ).fetchone()

        self.assertEqual(latest_session["title"], "Codex session")
        self.assertIn("Repo B latest transcript", entry["content"])
        self.assertNotIn("Current other-repo transcript", entry["content"])

    def test_resume_missing_is_clean(self):
        proc = self.run_ctx("resume", "missing-stream")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "No workstream matching 'missing-stream' exists.")
        self.assertEqual(proc.stderr.strip(), "")

    def test_rename_updates_search_index_for_renamed_workstream(self):
        self.assertEqual(self.run_ctx("start", "rename-source", "--no-auto-pull").returncode, 0)
        self.assertEqual(self.run_ctx("note", "Searchable rename note.").returncode, 0)

        renamed = self.run_ctx("rename", "rename-target")
        self.assertEqual(renamed.returncode, 0, renamed.stderr)
        self.assertIn("rename-source -> rename-target", renamed.stdout)

        search = self.run_ctx("search", "Searchable rename note.")
        self.assertEqual(search.returncode, 0, search.stderr)
        self.assertIn("rename-target", search.stdout)
        self.assertNotIn("rename-source /", search.stdout)
        self.assertNotIn("- rename-source —", search.stdout)

        old_resume = self.run_ctx("resume", "rename-source", "--no-compress")
        self.assertEqual(old_resume.returncode, 0)
        self.assertEqual(old_resume.stdout.strip(), "No workstream matching 'rename-source' exists.")

        new_resume = self.run_ctx("resume", "rename-target", "--no-compress")
        self.assertEqual(new_resume.returncode, 0, new_resume.stderr)
        self.assertIn("## ctx loaded: `rename-target`", new_resume.stdout)
        self.assertIn("Action: resumed only existing session", new_resume.stdout)

    def test_resume_repo_guard_requires_allow_other_repo(self):
        with tempfile.TemporaryDirectory() as repo_a_tmp, tempfile.TemporaryDirectory() as repo_b_tmp:
            repo_a = Path(repo_a_tmp)
            repo_b = Path(repo_b_tmp)
            self.assertEqual(self.run_ctx_in(repo_a, "start", "guard-demo", "--no-auto-pull").returncode, 0)

            blocked = self.run_ctx_in(repo_b, "resume", "guard-demo", "--no-compress")
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("belongs to another repo", blocked.stderr)
            self.assertIn("ctx resume guard-demo --allow-other-repo", blocked.stderr)

            allowed = self.run_ctx_in(repo_b, "resume", "guard-demo", "--allow-other-repo", "--no-compress")
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertIn("## ctx loaded: `guard-demo`", allowed.stdout)
            self.assertIn("Action: resumed only existing session", allowed.stdout)
            self.assertIn("current repo is", allowed.stdout)

    def test_branch_repo_guard_requires_allow_other_repo(self):
        with tempfile.TemporaryDirectory() as repo_a_tmp, tempfile.TemporaryDirectory() as repo_b_tmp:
            repo_a = Path(repo_a_tmp)
            repo_b = Path(repo_b_tmp)
            self.assertEqual(self.run_ctx_in(repo_a, "start", "guard-source", "--no-auto-pull").returncode, 0)
            self.assertEqual(self.run_ctx_in(repo_a, "note", "Carry this note into the allowed branch.").returncode, 0)

            blocked = self.run_ctx_in(repo_b, "branch", "guard-source", "guard-branch", "--no-compress")
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("belongs to another repo", blocked.stderr)
            self.assertIn("ctx branch guard-source guard-branch --allow-other-repo", blocked.stderr)

            allowed = self.run_ctx_in(
                repo_b, "branch", "guard-source", "guard-branch", "--allow-other-repo", "--no-compress"
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertIn("## ctx loaded: `guard-branch`", allowed.stdout)
            self.assertIn("Carry this note into the allowed branch.", allowed.stdout)

    def test_delete_repo_guard_requires_allow_other_repo(self):
        with tempfile.TemporaryDirectory() as repo_a_tmp, tempfile.TemporaryDirectory() as repo_b_tmp:
            repo_a = Path(repo_a_tmp)
            repo_b = Path(repo_b_tmp)
            self.assertEqual(self.run_ctx_in(repo_a, "start", "guard-delete", "--no-auto-pull").returncode, 0)

            blocked = self.run_ctx_in(repo_b, "delete", "guard-delete")
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("belongs to another repo", blocked.stderr)
            self.assertIn("ctx delete guard-delete --allow-other-repo", blocked.stderr)

            allowed = self.run_ctx_in(repo_b, "delete", "guard-delete", "--allow-other-repo")
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertIn("Deleted session 1: New session #guard-delete", allowed.stdout)

    def test_delete_workstream_name_removes_latest_session_only(self):
        self.assertEqual(self.run_ctx("start", "delete-demo", "--no-auto-pull").returncode, 0)
        self.write_codex_transcript()

        resumed = self.run_ctx("resume", "delete-demo", "--no-auto-pull", "--no-compress")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIn("Action: resumed new session for current codex transcript", resumed.stdout)

        deleted = self.run_ctx("delete", "delete-demo")
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        self.assertIn("Deleted session 2: Codex session #delete-demo", deleted.stdout)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, title FROM session WHERE workstream_id = (SELECT id FROM workstream WHERE slug = 'delete-demo') ORDER BY id"
            ).fetchall()

        self.assertEqual([(int(row["id"]), row["title"]) for row in rows], [(1, "New session")])

    def test_clear_this_repo_requires_yes_and_preserves_other_repo(self):
        with tempfile.TemporaryDirectory() as repo_a_tmp, tempfile.TemporaryDirectory() as repo_b_tmp:
            repo_a = Path(repo_a_tmp)
            repo_b = Path(repo_b_tmp)
            self.assertEqual(self.run_ctx_in(repo_a, "start", "clear-a", "--no-auto-pull").returncode, 0)
            self.assertEqual(self.run_ctx_in(repo_b, "start", "clear-b", "--no-auto-pull").returncode, 0)

            preview = self.run_ctx_in(repo_a, "clear", "--this-repo")
            self.assertEqual(preview.returncode, 2)
            self.assertIn("Refusing to delete without --yes.", preview.stdout)
            self.assertIn("clear-a", preview.stdout)
            self.assertNotIn("clear-b", preview.stdout)

            cleared = self.run_ctx_in(repo_a, "clear", "--this-repo", "--yes")
            self.assertEqual(cleared.returncode, 0, cleared.stderr)
            self.assertIn("Cleared 1 workstreams from this repo", cleared.stdout)

            with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
                rows = conn.execute("SELECT slug FROM workstream ORDER BY slug").fetchall()

            self.assertEqual([row[0] for row in rows], ["clear-b"])

    def test_clear_all_removes_linked_sessions_attachments_and_current_pointer(self):
        repo = Path(self.tmpdir.name) / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.run_ctx_in(repo, "start", "clear-all-demo", "--no-auto-pull").returncode, 0)
        self.assertEqual(self.run_ctx_in(repo, "note", "Cleanup note for clear-all verification.").returncode, 0)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.row_factory = sqlite3.Row
            session_id = int(
                conn.execute(
                    "SELECT id FROM session WHERE workstream_id = (SELECT id FROM workstream WHERE slug = 'clear-all-demo')"
                ).fetchone()["id"]
            )

        attachments_dir = self.db_path.parent / "attachments" / str(session_id)
        attachments_dir.mkdir(parents=True, exist_ok=True)
        (attachments_dir / "marker.txt").write_text("cleanup me", encoding="utf-8")
        current_file = self.db_path.parent / "current.json"
        self.assertTrue(current_file.exists())

        cleared = self.run_ctx_in(repo, "clear", "--all", "--yes")
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        self.assertIn("Cleared 1 workstreams from all repos", cleared.stdout)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            workstream_count = conn.execute("SELECT COUNT(*) FROM workstream").fetchone()[0]
            session_count = conn.execute("SELECT COUNT(*) FROM session").fetchone()[0]
            entry_count = conn.execute("SELECT COUNT(*) FROM entry").fetchone()[0]

        self.assertEqual(workstream_count, 0)
        self.assertEqual(session_count, 0)
        self.assertEqual(entry_count, 0)
        self.assertFalse(attachments_dir.exists())
        self.assertFalse(current_file.exists())

    def test_list_this_repo_ignores_workspace_hints_embedded_in_entries(self):
        env = {**self.env, "PYTHONPATH": str(ROOT)}
        init_proc = subprocess.run(
            [sys.executable, "-m", "contextfun", "--db", str(self.db_path), "init"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(init_proc.returncode, 0, init_proc.stderr)

        create_workstream = subprocess.run(
            [sys.executable, "-m", "contextfun", "--db", str(self.db_path), "workstream-new", "spoofed", "spoofed"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(create_workstream.returncode, 0, create_workstream.stderr)

        create_session = subprocess.run(
            [sys.executable, "-m", "contextfun", "--db", str(self.db_path), "session-new", "spoof-session", "--workstream-slug", "spoofed"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(create_session.returncode, 0, create_session.stderr)
        session_id = create_session.stdout.strip()

        injected = subprocess.run(
            [
                sys.executable,
                "-m",
                "contextfun",
                "--db",
                str(self.db_path),
                "add",
                session_id,
                "--text",
                f"<cwd>{ROOT}</cwd>",
            ],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(injected.returncode, 0, injected.stderr)

        listed = self.run_ctx("list", "--this-repo")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertNotIn("spoofed", listed.stdout)

    def test_branch_clones_saved_snapshot(self):
        self.assertEqual(self.run_ctx("start", "branch-source", "--no-compress").returncode, 0)
        self.assertEqual(self.run_ctx("note", "Alpha source note for branching fidelity.").returncode, 0)
        self.assertEqual(self.run_ctx("decision", "Keep branches detached from transcript bindings.").returncode, 0)
        self.assertEqual(self.run_ctx("todo", "Verify branch loads mirror source context size.").returncode, 0)
        self.assertEqual(self.run_ctx("branch", "branch-source", "branch-copy", "--no-compress").returncode, 0)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.row_factory = sqlite3.Row
            source_id = int(conn.execute("SELECT id FROM workstream WHERE slug = 'branch-source'").fetchone()["id"])
            target_id = int(conn.execute("SELECT id FROM workstream WHERE slug = 'branch-copy'").fetchone()["id"])
            source_entry_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM entry e
                    JOIN session s ON s.id = e.session_id
                    WHERE s.workstream_id = ?
                    """,
                    (source_id,),
                ).fetchone()["n"]
            )
            target_entry_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM entry e
                    JOIN session s ON s.id = e.session_id
                    WHERE s.workstream_id = ?
                    """,
                    (target_id,),
                ).fetchone()["n"]
            )
            target_links = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM session_source_link WHERE workstream_id = ?",
                    (target_id,),
                ).fetchone()["n"]
            )

        self.assertEqual(target_entry_count, source_entry_count)
        self.assertEqual(target_links, 0)

        resumed = self.run_ctx("resume", "branch-copy", "--no-compress", "--format", "markdown")
        self.assertEqual(resumed.returncode, 0)
        self.assertIn("Alpha source note for branching fidelity.", resumed.stdout)
        self.assertIn("Keep branches detached from transcript bindings.", resumed.stdout)

    def test_wrapper_noninteractive_commands_cover_capture_and_alias_paths(self):
        repo = Path(self.tmpdir.name) / "wrapper-repo"
        repo.mkdir(parents=True, exist_ok=True)
        snap_file = repo / "snap.txt"
        snap_file.write_text("Snapshot body for wrapper coverage.\n", encoding="utf-8")
        ingest_file = repo / "ingest.txt"
        ingest_file.write_text("Ingested body for wrapper coverage.\n", encoding="utf-8")

        created = self.run_ctx_in(repo, "new", "wrapper-demo", "--no-compress")
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertIn("## ctx loaded: `wrapper-demo`", created.stdout)

        current = self.run_ctx_in(repo)
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertIn("Current workstream: wrapper-demo", current.stdout)

        listed = self.run_ctx_in(repo, "list", "--this-repo")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("wrapper-demo", listed.stdout)

        searched = self.run_ctx_in(repo, "search", "wrapper-demo", "--this-repo")
        self.assertEqual(searched.returncode, 0, searched.stderr)
        self.assertIn("wrapper-demo", searched.stdout)

        resumed = self.run_ctx_in(repo, "go", "wrapper-demo", "--no-auto-pull", "--no-compress")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIn("## ctx loaded: `wrapper-demo`", resumed.stdout)

        renamed = self.run_ctx_in(repo, "rename", "wrapper-demo-renamed")
        self.assertEqual(renamed.returncode, 0, renamed.stderr)
        self.assertIn("wrapper-demo -> wrapper-demo-renamed", renamed.stdout)

        current_after_rename = self.run_ctx_in(repo)
        self.assertEqual(current_after_rename.returncode, 0, current_after_rename.stderr)
        self.assertIn("Current workstream: wrapper-demo-renamed", current_after_rename.stdout)

        set_proc = self.run_ctx_in(repo, "set", "wrapper-demo-renamed")
        self.assertEqual(set_proc.returncode, 0, set_proc.stderr)
        self.assertIn("Current workstream: wrapper-demo-renamed", set_proc.stdout)

        self.assertEqual(self.run_ctx_in(repo, "note", "Coverage note body.").returncode, 0)
        self.assertEqual(self.run_ctx_in(repo, "decision", "Coverage decision body.").returncode, 0)
        self.assertEqual(self.run_ctx_in(repo, "todo", "Coverage todo body.").returncode, 0)
        self.assertEqual(self.run_ctx_in(repo, "link", "https://example.com/coverage").returncode, 0)
        self.assertEqual(self.run_ctx_in(repo, "snap", str(snap_file)).returncode, 0)
        self.assertEqual(self.run_ctx_in(repo, "run", "printf wrapper-run-output").returncode, 0)
        self.assertEqual(self.run_ctx_in(repo, "git").returncode, 0)
        self.assertEqual(
            self.run_ctx_in(
                repo,
                "ingest-file",
                str(ingest_file),
                "--format",
                "text",
                "--source",
                "codex",
            ).returncode,
            0,
        )

        pulled = self.run_ctx_in(repo, "pull", "--auto")
        self.assertEqual(pulled.returncode, 0, pulled.stderr)
        self.assertEqual(pulled.stdout.strip(), "none")

        resumed_again = self.run_ctx_in(repo, "resume", "wrapper-demo-renamed", "--no-auto-pull", "--no-compress")
        self.assertEqual(resumed_again.returncode, 0, resumed_again.stderr)
        self.assertIn("## ctx loaded: `wrapper-demo-renamed`", resumed_again.stdout)
        self.assertIn("Coverage note body.", resumed_again.stdout)

        searched_after_entries = self.run_ctx_in(repo, "search", "Coverage note body", "--this-repo")
        self.assertEqual(searched_after_entries.returncode, 0, searched_after_entries.stderr)
        self.assertIn("wrapper-demo-renamed", searched_after_entries.stdout)

        self.assertEqual(self.run_ctx_in(repo, "start", "delete-by-id", "--no-auto-pull").returncode, 0)
        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.row_factory = sqlite3.Row
            delete_session_id = int(
                conn.execute(
                    "SELECT id FROM session WHERE workstream_id = (SELECT id FROM workstream WHERE slug = 'delete-by-id')"
                ).fetchone()["id"]
            )

        deleted = self.run_ctx_in(repo, "delete", "--session-id", str(delete_session_id))
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        self.assertIn(f"Deleted session {delete_session_id}", deleted.stdout)

        with contextlib.closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT e.type, e.content
                FROM entry e
                JOIN session s ON s.id = e.session_id
                JOIN workstream w ON w.id = s.workstream_id
                WHERE w.slug = 'wrapper-demo-renamed'
                ORDER BY e.id
                """
            ).fetchall()

        entries = [(row["type"], row["content"] or "") for row in rows]
        entry_types = {entry_type for entry_type, _content in entries}
        self.assertTrue({"note", "decision", "todo", "link", "file", "cmd"}.issubset(entry_types))
        self.assertTrue(any("Coverage note body." in content for _entry_type, content in entries))
        self.assertTrue(any("$ printf wrapper-run-output" in content for _entry_type, content in entries))
        self.assertTrue(any("Git context" in content for _entry_type, content in entries))
        self.assertTrue(any("Ingested body for wrapper coverage." in content for _entry_type, content in entries))

    def test_wrapper_curate_paths_dispatch_to_the_terminal_ui(self):
        ctx_cmd = _load_ctx_cmd_module()
        fake_workstream = {"id": 1, "slug": "demo", "title": "demo"}

        with mock.patch.object(ctx_cmd, "_resolve_curation_workstream", return_value=fake_workstream) as resolve, mock.patch.object(
            ctx_cmd, "_launch_curation_ui", return_value=7
        ) as launch:
            with mock.patch.object(sys, "argv", [str(CTX_CMD), "curate", "demo"]):
                self.assertEqual(ctx_cmd.main(), 7)
            resolve.assert_called_with("demo")
            launch.assert_called_with(fake_workstream)

            resolve.reset_mock()
            launch.reset_mock()
            with mock.patch.object(sys, "argv", [str(CTX_CMD), "delete", "--interactive", "demo"]):
                self.assertEqual(ctx_cmd.main(), 7)
            resolve.assert_called_with("demo")
            launch.assert_called_with(fake_workstream)

    def test_wrapper_web_and_ingest_clipboard_dispatch_cleanly(self):
        ctx_cmd = _load_ctx_cmd_module()

        with mock.patch.object(ctx_cmd, "run_ctx_passthrough", return_value=0) as passthrough:
            with mock.patch.object(sys, "argv", [str(CTX_CMD), "web", "--host", "0.0.0.0", "--port", "9999", "--open"]):
                self.assertEqual(ctx_cmd.main(), 0)
            passthrough.assert_called_with(["web", "--host", "0.0.0.0", "--port", "9999", "--open"])

        with mock.patch.object(ctx_cmd.subprocess, "check_output", return_value=b"clipboard body"), mock.patch.object(
            ctx_cmd, "run_ctx", return_value="ingested\n"
        ) as run_ctx_call, mock.patch.object(sys, "argv", [str(CTX_CMD), "ingest-clipboard", "--format", "text", "--source", "claude"]), mock.patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            self.assertIsNone(ctx_cmd.main())

        run_ctx_call.assert_called_with(
            ["ingest", "--file", "-", "--format", "text", "--source", "claude"],
            input_data="clipboard body",
        )

    def test_web_helpers_enforce_loopback_token_and_json(self):
        from contextfun import web as ctx_web

        self.assertTrue(ctx_web._is_loopback_host("127.0.0.1"))
        self.assertTrue(ctx_web._is_loopback_host("localhost"))
        self.assertTrue(ctx_web._is_loopback_host("::1"))
        self.assertFalse(ctx_web._is_loopback_host("0.0.0.0"))

        rendered = ctx_web._render_index_html("token-demo").decode("utf-8")
        self.assertIn('meta name="ctx-web-token" content="token-demo"', rendered)
        self.assertNotIn(ctx_web.INDEX_TOKEN_PLACEHOLDER, rendered)

        self.assertEqual(
            ctx_web._validate_api_request({}, expected_token="secret"),
            (403, "missing or invalid API token"),
        )
        self.assertEqual(
            ctx_web._validate_api_request(
                {"X-ctx-web-token": "secret", "Content-Type": "text/plain"},
                expected_token="secret",
                require_json=True,
            ),
            (415, "Content-Type must be application/json"),
        )
        self.assertIsNone(
            ctx_web._validate_api_request(
                {"X-ctx-web-token": "secret", "Content-Type": "application/json; charset=utf-8"},
                expected_token="secret",
                require_json=True,
            )
        )

        with self.assertRaises(SystemExit):
            ctx_web.run_server(self.db_path, host="0.0.0.0", port=4310)

    def test_install_script_is_release_pinned_and_installs_skills(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn('DEFAULT_REF="v0.1.1"', text)
        self.assertIn('archive/refs/tags/', text)
        self.assertIn('rsync -a "$SRC_DIR/skills/" "$SKILLS_DIR/"', text)
        self.assertIn('install_skills.sh', text)
        self.assertIn('CTX_INSTALL_SKILLS', text)
        self.assertIn('install -m 0755 "$SRC_DIR/scripts/ctx_cmd.py" "$BIN_DIR/ctx.py"', text)
        self.assertIn('exec python3 "$BIN_DIR/ctx.py" "$@"', text)
        self.assertNotIn("Compatibility aliases also work:", text)

    def test_skill_bootstrap_installer_is_release_pinned_and_installs_skills(self):
        text = SKILL_INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn('DEFAULT_REF="v0.1.1"', text)
        self.assertIn('archive/refs/tags/', text)
        self.assertIn('install_skills.sh', text)
        self.assertIn('CTX_INSTALL_SKILLS', text)
        self.assertIn('install -m 0755 "$SRC_DIR/scripts/ctx_cmd.py" "$BIN_DIR/ctx.py"', text)
        self.assertIn('exec python3 "$BIN_DIR/ctx.py" "$@"', text)

    def test_local_agent_setup_script_is_release_pinned(self):
        text = AGENT_SETUP_LOCAL_SH.read_text(encoding="utf-8")
        self.assertIn('DEFAULT_REF="v0.1.1"', text)
        self.assertIn('archive/refs/tags/', text)
        self.assertIn("Downloading ctx into ./ctx", text)

    def test_quickstart_ctx_env_and_repo_shim_do_not_execute_embedded_repo_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            marker_dir = tmp_path / "home"
            marker_dir.mkdir()
            repo_root = tmp_path / "repo$(touch PWNED)"
            shutil.copytree(
                ROOT,
                repo_root,
                ignore=shutil.ignore_patterns(".git", ".contextfun", "ctx", "__pycache__", "*.pyc"),
            )

            env = self.env.copy()
            env["HOME"] = str(marker_dir)
            env["CODEX_SKILLS_DIR"] = str(tmp_path / "codex-skills")
            env["CLAUDE_SKILLS_DIR"] = str(tmp_path / "claude-skills")
            env["PYTHONPATH"] = str(repo_root)
            proc = subprocess.run(
                ["bash", str(repo_root / "scripts" / "quickstart.sh")],
                cwd=str(repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            marker = marker_dir / "PWNED"
            alias_proc = subprocess.run(
                ["bash", "--noprofile", "--rcfile", str(repo_root / "ctx.env"), "-ic", "ctx-local list >/dev/null"],
                cwd=str(marker_dir),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(alias_proc.returncode, 0, alias_proc.stderr)
            self.assertFalse(marker.exists())

            shim_proc = subprocess.run(
                [str(marker_dir / ".contextfun" / "bin" / "ctx"), "list"],
                cwd=str(marker_dir),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(shim_proc.returncode, 0, shim_proc.stderr)
            self.assertFalse(marker.exists())

    def test_setup_sh_runs_quickstart_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            home.mkdir()
            repo_root = tmp_path / "repo$(touch PWNED)"
            shutil.copytree(
                ROOT,
                repo_root,
                ignore=shutil.ignore_patterns(".git", ".contextfun", "ctx", "__pycache__", "*.pyc"),
            )

            env = self.env.copy()
            env["HOME"] = str(home)
            env["CODEX_SKILLS_DIR"] = str(tmp_path / "codex-skills")
            env["CLAUDE_SKILLS_DIR"] = str(tmp_path / "claude-skills")
            env["PYTHONPATH"] = str(repo_root)
            proc = subprocess.run(
                ["bash", str(repo_root / "setup.sh")],
                cwd=str(repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            marker = home / "PWNED"
            ctx_env = repo_root / "ctx.env"
            self.assertTrue(ctx_env.exists())
            alias_proc = subprocess.run(
                ["bash", "--noprofile", "--rcfile", str(ctx_env), "-ic", "ctx-local list >/dev/null"],
                cwd=str(home),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(alias_proc.returncode, 0, alias_proc.stderr)
            self.assertFalse(marker.exists())

    def test_install_script_wrapper_and_rc_lines_do_not_execute_embedded_home_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            safe_cwd = tmp_path / "safe"
            safe_cwd.mkdir()
            marker = safe_cwd / "PWNED"
            home = tmp_path / "home$(touch PWNED)"
            home.mkdir()
            archive_path = self.make_release_archive()
            stub_dir = tmp_path / "stub-bin"
            stub_dir.mkdir()
            self.write_curl_stub(stub_dir / "curl", archive_path)

            env = self.env.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
            env["CODEX_SKILLS_DIR"] = str(tmp_path / "codex-skills")
            env["CLAUDE_SKILLS_DIR"] = str(tmp_path / "claude-skills")
            proc = subprocess.run(
                ["bash", str(INSTALL_SH)],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            rc_proc = subprocess.run(
                ["bash", "-lc", 'source "$1" >/dev/null', "bash", str(home / ".bashrc")],
                cwd=str(safe_cwd),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rc_proc.returncode, 0, rc_proc.stderr)
            self.assertFalse(marker.exists())

            shim_proc = subprocess.run(
                [str(home / ".contextfun" / "bin" / "ctx"), "list"],
                cwd=str(safe_cwd),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(shim_proc.returncode, 0, shim_proc.stderr)
            self.assertFalse(marker.exists())

    def test_skill_bootstrap_installer_wrapper_and_rc_lines_do_not_execute_embedded_home_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            safe_cwd = tmp_path / "safe"
            safe_cwd.mkdir()
            marker = safe_cwd / "PWNED"
            home = tmp_path / "home$(touch PWNED)"
            home.mkdir()
            archive_path = self.make_release_archive()
            stub_dir = tmp_path / "stub-bin"
            stub_dir.mkdir()
            self.write_curl_stub(stub_dir / "curl", archive_path)

            env = self.env.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
            env["CODEX_SKILLS_DIR"] = str(tmp_path / "codex-skills")
            env["CLAUDE_SKILLS_DIR"] = str(tmp_path / "claude-skills")
            proc = subprocess.run(
                ["bash", str(SKILL_INSTALL_SH)],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            rc_proc = subprocess.run(
                ["bash", "-lc", 'source "$1" >/dev/null', "bash", str(home / ".bashrc")],
                cwd=str(safe_cwd),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rc_proc.returncode, 0, rc_proc.stderr)
            self.assertFalse(marker.exists())

            shim_proc = subprocess.run(
                [str(home / ".contextfun" / "bin" / "ctx"), "list"],
                cwd=str(safe_cwd),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(shim_proc.returncode, 0, shim_proc.stderr)
            self.assertFalse(marker.exists())
            self.assertTrue((home / ".contextfun" / "skills" / "codex" / "ctx-start" / "SKILL.md").exists())
            self.assertTrue((home / ".contextfun" / "skills" / "claude" / "ctx" / "SKILL.md").exists())

    def test_agent_setup_local_wrapper_does_not_execute_embedded_prefix_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            safe_cwd = tmp_path / "safe"
            safe_cwd.mkdir()
            marker = safe_cwd / "PWNED"
            workdir = tmp_path / "work$(touch PWNED)"
            workdir.mkdir()
            archive_path = self.make_release_archive()
            stub_dir = tmp_path / "stub-bin"
            stub_dir.mkdir()
            self.write_curl_stub(stub_dir / "curl", archive_path)

            env = self.env.copy()
            env["HOME"] = str(tmp_path / "home")
            env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
            proc = subprocess.run(
                ["bash", str(AGENT_SETUP_LOCAL_SH)],
                cwd=str(workdir),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            shim_proc = subprocess.run(
                [str(workdir / "ctx" / "bin" / "ctx"), "list"],
                cwd=str(safe_cwd),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(shim_proc.returncode, 0, shim_proc.stderr)
            self.assertFalse(marker.exists())

    def test_cli_uses_stable_user_home_and_future_annotations(self):
        cli_text = CLI_PY.read_text(encoding="utf-8")
        web_text = WEB_PY.read_text(encoding="utf-8")
        ctx_text = CTX_CMD.read_text(encoding="utf-8")
        self.assertIn("from __future__ import annotations", cli_text)
        self.assertIn("from __future__ import annotations", web_text)
        self.assertIn("from __future__ import annotations", ctx_text)
        self.assertIn('CTX_HOME', cli_text)
        self.assertIn('ctx_DB', cli_text)
        self.assertIn('ctx_DB', web_text)
        self.assertIn('ctx_DB', ctx_text)
        self.assertIn('~/.contextfun', cli_text)
        self.assertIn('cmd = [sys.executable, "-m", "contextfun"]', ctx_text)

    def test_install_skills_supports_alternate_skills_root(self):
        with tempfile.TemporaryDirectory() as codex_dir, tempfile.TemporaryDirectory() as claude_dir:
            proc = subprocess.run(
                [
                    "bash",
                    str(INSTALL_SKILLS_SH),
                    "--skills-root",
                    str(ROOT / "skills"),
                    "--codex-dir",
                    codex_dir,
                    "--claude-dir",
                    claude_dir,
                ],
                cwd=str(ROOT),
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((Path(codex_dir) / "ctx-start" / "SKILL.md").exists())
            self.assertTrue((Path(claude_dir) / "ctx" / "SKILL.md").exists())

    def test_uninstall_skills_removes_matching_links_only(self):
        with tempfile.TemporaryDirectory() as skills_tmp, tempfile.TemporaryDirectory() as codex_tmp, tempfile.TemporaryDirectory() as claude_tmp:
            skills_root = Path(skills_tmp)
            codex_dir = Path(codex_tmp)
            claude_dir = Path(claude_tmp)
            codex_skill = skills_root / "codex" / "ctx-start"
            claude_skill = skills_root / "claude" / "ctx"
            codex_skill.mkdir(parents=True, exist_ok=True)
            claude_skill.mkdir(parents=True, exist_ok=True)
            (codex_skill / "SKILL.md").write_text("codex", encoding="utf-8")
            (claude_skill / "SKILL.md").write_text("claude", encoding="utf-8")

            (codex_dir / "ctx-start").symlink_to(codex_skill)
            (claude_dir / "ctx").symlink_to(claude_skill)

            other_root = skills_root / "other"
            other_root.mkdir(parents=True, exist_ok=True)
            (other_root / "SKILL.md").write_text("other", encoding="utf-8")
            (codex_dir / "keep-me").symlink_to(other_root)

            proc = subprocess.run(
                [
                    "bash",
                    str(UNINSTALL_SKILLS_SH),
                    "--skills-root",
                    str(skills_root),
                    "--codex-dir",
                    str(codex_dir),
                    "--claude-dir",
                    str(claude_dir),
                ],
                cwd=str(ROOT),
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse((codex_dir / "ctx-start").exists())
            self.assertFalse((claude_dir / "ctx").exists())
            self.assertTrue((codex_dir / "keep-me").exists())

    def test_uninstall_script_removes_global_install_and_rc_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            codex_dir = tmp_path / "codex-skills"
            claude_dir = tmp_path / "claude-skills"
            prefix = home / ".contextfun"
            (prefix / "bin").mkdir(parents=True, exist_ok=True)
            (prefix / "lib" / "contextfun").mkdir(parents=True, exist_ok=True)
            (prefix / "skills" / "codex" / "ctx-start").mkdir(parents=True, exist_ok=True)
            (prefix / "skills" / "claude" / "ctx").mkdir(parents=True, exist_ok=True)
            (prefix / "skills" / "codex" / "ctx-start" / "SKILL.md").write_text("codex", encoding="utf-8")
            (prefix / "skills" / "claude" / "ctx" / "SKILL.md").write_text("claude", encoding="utf-8")
            codex_dir.mkdir(parents=True, exist_ok=True)
            claude_dir.mkdir(parents=True, exist_ok=True)
            (codex_dir / "ctx-start").symlink_to(prefix / "skills" / "codex" / "ctx-start")
            (claude_dir / "ctx").symlink_to(prefix / "skills" / "claude" / "ctx")
            (home / ".zshrc").write_text(
                "\n".join(
                    [
                        'export ctx_DB="' + str(prefix / "context.db") + '"',
                        'export CONTEXTFUN_DB="' + str(prefix / "context.db") + '"',
                        'export PATH="' + str(prefix / "bin") + ':$PATH"',
                        "export KEEP_ME=1",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            env = self.env.copy()
            env["HOME"] = str(home)
            env["CODEX_SKILLS_DIR"] = str(codex_dir)
            env["CLAUDE_SKILLS_DIR"] = str(claude_dir)
            proc = subprocess.run(
                ["bash", str(UNINSTALL_SH), "--global"],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse(prefix.exists())
            self.assertFalse((codex_dir / "ctx-start").exists())
            self.assertFalse((claude_dir / "ctx").exists())
            zshrc_text = (home / ".zshrc").read_text(encoding="utf-8")
            self.assertIn("export KEEP_ME=1", zshrc_text)
            self.assertNotIn("ctx_DB", zshrc_text)
            self.assertNotIn("CONTEXTFUN_DB", zshrc_text)
            self.assertNotIn(str(prefix / "bin"), zshrc_text)

    def test_uninstall_script_removes_repo_local_setup_from_custom_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_root = tmp_path / "repo"
            home = tmp_path / "home"
            codex_dir = tmp_path / "codex-skills"
            claude_dir = tmp_path / "claude-skills"
            (repo_root / ".contextfun").mkdir(parents=True, exist_ok=True)
            (repo_root / ".contextfun" / "context.db").write_text("", encoding="utf-8")
            (repo_root / "ctx.env").write_text("CTX", encoding="utf-8")
            (repo_root / "skills" / "codex" / "ctx-start").mkdir(parents=True, exist_ok=True)
            (repo_root / "skills" / "claude" / "ctx").mkdir(parents=True, exist_ok=True)
            (repo_root / "skills" / "codex" / "ctx-start" / "SKILL.md").write_text("codex", encoding="utf-8")
            (repo_root / "skills" / "claude" / "ctx" / "SKILL.md").write_text("claude", encoding="utf-8")
            (home / ".contextfun" / "bin").mkdir(parents=True, exist_ok=True)
            self.write_executable(
                home / ".contextfun" / "bin" / "ctx",
                f"""#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="{repo_root}"
exec python3 "$ROOT_DIR/scripts/ctx_cmd.py" "$@"
""",
            )
            codex_dir.mkdir(parents=True, exist_ok=True)
            claude_dir.mkdir(parents=True, exist_ok=True)
            (codex_dir / "ctx-start").symlink_to(repo_root / "skills" / "codex" / "ctx-start")
            (claude_dir / "ctx").symlink_to(repo_root / "skills" / "claude" / "ctx")

            env = self.env.copy()
            env["HOME"] = str(home)
            env["CODEX_SKILLS_DIR"] = str(codex_dir)
            env["CLAUDE_SKILLS_DIR"] = str(claude_dir)
            proc = subprocess.run(
                ["bash", str(UNINSTALL_SH), "--root", str(repo_root)],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse((repo_root / ".contextfun").exists())
            self.assertFalse((repo_root / "ctx.env").exists())
            self.assertFalse((home / ".contextfun" / "bin" / "ctx").exists())
            self.assertFalse((codex_dir / "ctx-start").exists())
            self.assertFalse((claude_dir / "ctx").exists())

    def test_uninstall_script_removes_agent_local_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_root = tmp_path / "repo"
            (repo_root / "ctx" / "bin").mkdir(parents=True, exist_ok=True)
            (repo_root / "ctx" / "bin" / "ctx").write_text("stub", encoding="utf-8")

            proc = subprocess.run(
                ["bash", str(UNINSTALL_SH), "--agent-local", "--root", str(repo_root)],
                cwd=str(ROOT),
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse((repo_root / "ctx").exists())

    def test_skills_sh_skill_exists(self):
        skill_file = ROOT / "skills" / "ctx" / "SKILL.md"
        self.assertTrue(skill_file.exists())
        text = skill_file.read_text(encoding="utf-8")
        self.assertIn("name: ctx", text)
        self.assertIn("ctx install", text)
        self.assertIn("single `ctx` entrypoint", text)

    def test_claude_skill_direct_entrypoints_exist(self):
        expected = [
            ROOT / "skills" / "claude" / "branch" / "scripts" / "branch.sh",
            ROOT / "skills" / "claude" / "ctx" / "scripts" / "ctx.sh",
            ROOT / "skills" / "claude" / "ctx-delete" / "scripts" / "ctx_delete.sh",
            ROOT / "skills" / "claude" / "ctx-list" / "scripts" / "ctx_cli_skill.sh",
            ROOT / "skills" / "claude" / "ctx-resume" / "scripts" / "ctx_resume.sh",
            ROOT / "skills" / "claude" / "ctx-start" / "scripts" / "ctx_start.sh",
        ]
        for path in expected:
            self.assertTrue(path.exists(), f"missing Claude entrypoint: {path}")

    def test_docs_guides_exist_and_are_linked_from_readme(self):
        docs = [
            "install.md",
            "usage.md",
            "architecture.md",
            "integrations.md",
            "repo-layout.md",
            "maintenance.md",
            "README.md",
        ]
        readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
        index_text = DOCS_INDEX.read_text(encoding="utf-8")
        for name in docs:
            path = ROOT / "docs" / name
            self.assertTrue(path.exists(), f"missing docs guide: {path}")
            self.assertIn(f"docs/{name}", readme_text)
            if name != "README.md":
                self.assertIn(name, index_text)

    def test_directory_indexes_and_shared_skill_helper_exist(self):
        repo_layout_text = (ROOT / "docs" / "repo-layout.md").read_text(encoding="utf-8")
        index_text = DOCS_INDEX.read_text(encoding="utf-8")
        expected = [
            ROOT / "scripts" / "README.md",
            ROOT / "skills" / "README.md",
            ROOT / "tools" / "README.md",
            ROOT / "skills" / "shared" / "ctx_dispatch.sh",
        ]
        for path in expected:
            self.assertTrue(path.exists(), f"missing repo index/helper: {path}")
        self.assertIn("../scripts/README.md", index_text)
        self.assertIn("../skills/README.md", index_text)
        self.assertIn("../tools/README.md", index_text)
        self.assertIn("../scripts/README.md", repo_layout_text)
        self.assertIn("../skills/README.md", repo_layout_text)
        self.assertIn("../tools/README.md", repo_layout_text)

    def test_skill_wrapper_cleanup_is_centralized(self):
        wrappers = [
            ROOT / "skills" / "claude" / "branch" / "scripts" / "skills" / "branch.sh",
            ROOT / "skills" / "claude" / "ctx-delete" / "scripts" / "skills" / "ctx_delete.sh",
            ROOT / "skills" / "claude" / "ctx-list" / "scripts" / "skills" / "ctx_cli_skill.sh",
            ROOT / "skills" / "claude" / "ctx-resume" / "scripts" / "skills" / "ctx_resume.sh",
            ROOT / "skills" / "claude" / "ctx-start" / "scripts" / "skills" / "ctx_start.sh",
            ROOT / "skills" / "claude" / "ctx" / "scripts" / "skills" / "ctx.sh",
            ROOT / "skills" / "codex" / "ctx-branch" / "scripts" / "skills" / "ctx_branch.sh",
            ROOT / "skills" / "codex" / "ctx-delete" / "scripts" / "skills" / "ctx_delete.sh",
            ROOT / "skills" / "codex" / "ctx-list" / "scripts" / "skills" / "ctx_cli_skill.sh",
            ROOT / "skills" / "codex" / "ctx-resume" / "scripts" / "skills" / "ctx_resume.sh",
            ROOT / "skills" / "codex" / "ctx-start" / "scripts" / "skills" / "ctx_start.sh",
        ]
        removed = [
            ROOT / "skills" / "claude" / "ctx-list" / "ctx-list",
            ROOT / "skills" / "claude" / "ctx-resume" / "ctx-resume",
            ROOT / "skills" / "claude" / "ctx-start" / "ctx-start",
            ROOT / "skills" / "codex" / "ctx-list" / "ctx-list",
            ROOT / "skills" / "codex" / "ctx-resume" / "ctx-resume",
            ROOT / "skills" / "codex" / "ctx-start" / "ctx-start",
        ]
        for path in wrappers:
            text = path.read_text(encoding="utf-8")
            self.assertIn("shared/ctx_dispatch.sh", text)
            self.assertIn("ctx_skill_exec", text)
        for path in removed:
            self.assertFalse(path.exists() or path.is_symlink(), f"unexpected leftover skill link: {path}")

    def test_skills_sh_wrapper_bootstraps_when_ctx_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            home.mkdir()
            wrapper = tmp_path / "ctx.sh"
            installer = tmp_path / "install_ctx.sh"
            self.write_executable(wrapper, SKILL_WRAPPER_SH.read_text(encoding="utf-8"))
            self.write_executable(
                installer,
                """#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$HOME/.contextfun/bin"
cat > "$HOME/.contextfun/bin/ctx" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'CTX_STUB:%s\\n' "$*"
EOF
chmod +x "$HOME/.contextfun/bin/ctx"
""",
            )
            env = self.env.copy()
            env["HOME"] = str(home)
            env["PATH"] = "/usr/bin:/bin"
            proc = subprocess.run(
                ["bash", str(wrapper), "list", "--this-repo"],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("CTX_STUB:list --this-repo", proc.stdout)
            self.assertIn("Bootstrapping the bundled installer first", proc.stderr)

    def test_skills_sh_wrapper_install_command_bootstraps_without_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            home.mkdir()
            wrapper = tmp_path / "ctx.sh"
            installer = tmp_path / "install_ctx.sh"
            self.write_executable(wrapper, SKILL_WRAPPER_SH.read_text(encoding="utf-8"))
            self.write_executable(
                installer,
                """#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$HOME"
printf 'installed\\n' > "$HOME/install-ran.txt"
""",
            )
            env = self.env.copy()
            env["HOME"] = str(home)
            env["PATH"] = "/usr/bin:/bin"
            proc = subprocess.run(
                ["bash", str(wrapper), "install"],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, "")
            self.assertEqual(proc.stderr, "")
            self.assertEqual((home / "install-ran.txt").read_text(encoding="utf-8").strip(), "installed")

    def test_system_python39_can_import_cli_module(self):
        py39 = Path("/usr/bin/python3")
        if not py39.exists():
            self.skipTest("system python3 not available")
        proc = subprocess.run(
            [str(py39), "-c", "import importlib.util, pathlib; p=pathlib.Path('contextfun/cli.py'); spec=importlib.util.spec_from_file_location('ctx_cli', p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.DEFAULT_HOME)"],
            cwd=str(ROOT),
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(".contextfun", proc.stdout)

    def test_ctx_cmd_prefers_local_repo_db_when_present(self):
        ctx_cmd = _load_ctx_cmd_module()
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp)
            local_db = repo_dir / ".contextfun" / "context.db"
            local_db.parent.mkdir(parents=True, exist_ok=True)
            local_db.write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                ctx_cmd, "_command_cwd", return_value=str(repo_dir)
            ):
                resolved = ctx_cmd._db_path()
        self.assertEqual(resolved, local_db.resolve())

    def test_ctx_cmd_pythonpath_includes_repo_root(self):
        ctx_cmd = _load_ctx_cmd_module()
        env = {}
        ctx_cmd._augment_pythonpath(env)
        pythonpath = env.get("PYTHONPATH", "")
        self.assertIn(str(ROOT), pythonpath)

    def test_run_ctx_propagates_resolved_db_path_to_subprocess_env(self):
        ctx_cmd = _load_ctx_cmd_module()
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp)
            local_db = repo_dir / ".contextfun" / "context.db"
            local_db.parent.mkdir(parents=True, exist_ok=True)
            local_db.write_text("", encoding="utf-8")
            captured = {}

            def fake_check_output(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["cwd"] = kwargs.get("cwd")
                captured["env"] = kwargs.get("env", {})
                return b"ok\n"

            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                ctx_cmd, "_command_cwd", return_value=str(repo_dir)
            ), mock.patch.object(ctx_cmd.subprocess, "check_output", side_effect=fake_check_output):
                result = ctx_cmd.run_ctx(["list"])

        self.assertEqual(result, "ok\n")
        self.assertEqual(captured["cwd"], str(repo_dir))
        self.assertEqual(captured["env"].get("ctx_DB"), str(local_db.resolve()))
        self.assertNotIn("CONTEXTFUN_DB", captured["env"])
        self.assertIn(str(local_db.resolve()), captured["cmd"])

    def test_ctx_cmd_accepts_legacy_contextfun_db_env(self):
        ctx_cmd = _load_ctx_cmd_module()
        legacy_db = Path(self.tmpdir.name) / "legacy.db"
        with mock.patch.dict(
            os.environ,
            {"CONTEXTFUN_DB": str(legacy_db)},
            clear=True,
        ), mock.patch.object(ctx_cmd, "_current_or_parent_db", return_value=None):
            resolved = ctx_cmd._db_path()
        self.assertEqual(resolved, legacy_db.resolve())

    def test_ctx_cmd_ignores_stale_repo_local_env_db_for_other_repo(self):
        ctx_cmd = _load_ctx_cmd_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_a = tmp_path / "repo-a"
            repo_b = tmp_path / "repo-b"
            repo_a.mkdir(parents=True, exist_ok=True)
            repo_b.mkdir(parents=True, exist_ok=True)
            stale_db = (repo_a / ".contextfun" / "context.db").resolve()
            home_db = (tmp_path / "home" / ".contextfun" / "context.db").resolve()
            stale_db.parent.mkdir(parents=True, exist_ok=True)
            stale_db.write_text("", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"ctx_DB": str(stale_db)},
                clear=True,
            ), mock.patch.object(
                ctx_cmd, "_command_cwd", return_value=str(repo_b)
            ), mock.patch.object(
                ctx_cmd, "_default_home_db_path", return_value=home_db
            ):
                resolved = ctx_cmd._db_path()
        self.assertEqual(resolved, home_db)

    def test_ctx_cmd_prefers_current_repo_local_db_over_stale_env_db(self):
        ctx_cmd = _load_ctx_cmd_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_a = tmp_path / "repo-a"
            repo_b = tmp_path / "repo-b"
            repo_a.mkdir(parents=True, exist_ok=True)
            repo_b.mkdir(parents=True, exist_ok=True)
            stale_db = (repo_a / ".contextfun" / "context.db").resolve()
            local_db = (repo_b / ".contextfun" / "context.db").resolve()
            stale_db.parent.mkdir(parents=True, exist_ok=True)
            stale_db.write_text("", encoding="utf-8")
            local_db.parent.mkdir(parents=True, exist_ok=True)
            local_db.write_text("", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"ctx_DB": str(stale_db)},
                clear=True,
            ), mock.patch.object(
                ctx_cmd, "_command_cwd", return_value=str(repo_b)
            ):
                resolved = ctx_cmd._db_path()
        self.assertEqual(resolved, local_db)

    def test_run_ctx_retries_readonly_home_db_on_repo_local_db(self):
        ctx_cmd = _load_ctx_cmd_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_dir = tmp_path / "repo"
            repo_dir.mkdir(parents=True, exist_ok=True)
            home_db = (tmp_path / "home" / ".contextfun" / "context.db").resolve()
            local_db = (repo_dir / ".contextfun" / "context.db").resolve()
            calls = []

            def fake_check_output(cmd, **kwargs):
                calls.append(Path(cmd[cmd.index("--db") + 1]).resolve())
                if len(calls) == 1:
                    raise subprocess.CalledProcessError(
                        1,
                        cmd,
                        output=b"sqlite3.OperationalError: attempt to write a readonly database\n",
                    )
                return b"ok\n"

            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                ctx_cmd, "_command_cwd", return_value=str(repo_dir)
            ), mock.patch.object(
                ctx_cmd, "_default_home_db_path", return_value=home_db
            ), mock.patch.object(
                ctx_cmd.subprocess, "check_output", side_effect=fake_check_output
            ):
                result = ctx_cmd.run_ctx(["list"])
                resolved = ctx_cmd._db_path()
                local_parent_exists = local_db.parent.exists()

        self.assertEqual(result, "ok\n")
        self.assertEqual(calls, [home_db, local_db])
        self.assertEqual(resolved, local_db)
        self.assertTrue(local_parent_exists)

    def test_run_ctx_uses_repo_local_db_after_home_db_parent_error(self):
        ctx_cmd = _load_ctx_cmd_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_dir = tmp_path / "repo"
            repo_dir.mkdir(parents=True, exist_ok=True)
            home_db = (tmp_path / "home" / ".contextfun" / "context.db").resolve()
            local_db = (repo_dir / ".contextfun" / "context.db").resolve()

            def fake_run_once(db_path, args_list, input_data=None):
                if Path(db_path).resolve() == home_db:
                    raise PermissionError("operation not permitted")
                return "ok\n"

            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                ctx_cmd, "_command_cwd", return_value=str(repo_dir)
            ), mock.patch.object(
                ctx_cmd, "_default_home_db_path", return_value=home_db
            ), mock.patch.object(
                ctx_cmd, "_run_ctx_once", side_effect=fake_run_once
            ):
                result = ctx_cmd.run_ctx(["list"])
                resolved = ctx_cmd._db_path()
                local_parent_exists = local_db.parent.exists()

        self.assertEqual(result, "ok\n")
        self.assertEqual(resolved, local_db)
        self.assertTrue(local_parent_exists)

    def test_core_cli_uses_ctx_db_env_without_explicit_db(self):
        env = {**self.env, "PYTHONPATH": str(ROOT)}
        init_proc = subprocess.run(
            [sys.executable, "-m", "contextfun", "init"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
        self.assertTrue(self.db_path.exists())
        ensure_proc = subprocess.run(
            [sys.executable, "-m", "contextfun", "workstream-ensure", "env-demo", "--json"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(ensure_proc.returncode, 0, ensure_proc.stderr)
        payload = json.loads(ensure_proc.stdout)
        self.assertEqual(payload["slug"], "env-demo")

    def test_workstream_ensure_rolls_back_if_set_current_fails(self):
        from contextfun import cli as ctx_cli

        args = argparse.Namespace(
            db=str(self.db_path),
            name="demo-pull",
            slug=None,
            workspace=None,
            set_current=True,
            unique_if_exists=False,
            json=False,
        )
        with mock.patch.object(ctx_cli, "_set_current_workstream", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                ctx_cli.cmd_workstream_ensure(args)
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute("SELECT id FROM workstream WHERE slug = ?", ("demo-pull",)).fetchone()
        self.assertIsNone(row)

    def test_installed_ctx_cmd_imports_from_prefix_lib_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp)
            bin_dir = prefix / "bin"
            lib_dir = prefix / "lib"
            db_path = prefix / "context.db"
            bin_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CTX_CMD, bin_dir / "ctx.py")
            shutil.copytree(ROOT / "contextfun", lib_dir / "contextfun")

            init_proc = subprocess.run(
                [sys.executable, "-m", "contextfun", "--db", str(db_path), "init"],
                cwd=str(ROOT),
                env={**self.env, "PYTHONPATH": str(lib_dir)},
                capture_output=True,
                text=True,
            )
            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)

            proc = subprocess.run(
                [sys.executable, str(bin_dir / "ctx.py"), "list"],
                cwd=str(prefix),
                env={**self.env, "ctx_DB": str(db_path)},
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_pull_feedback_does_not_fallback_to_existing_clipboard_when_frontmost_copy_fails(self):
        ctx_cmd = _load_ctx_cmd_module()
        with mock.patch.object(ctx_cmd.subprocess, "check_output") as check_output, mock.patch.object(
            ctx_cmd, "run_ctx"
        ) as run_ctx_call:
            note = ctx_cmd._ingest_clipboard_into_session(
                1,
                fmt="markdown",
                source="codex",
                attempted_frontmost=True,
                frontmost_copied=False,
            )
        check_output.assert_not_called()
        run_ctx_call.assert_not_called()
        self.assertEqual(note, "Pull capture: frontmost copy failed, so no visible chat was ingested.")

    def test_curation_entries_exposes_saved_entries(self):
        self.assertEqual(self.run_ctx("start", "curate-demo", "--no-auto-pull").returncode, 0)
        self.assertEqual(self.run_ctx("note", "Keep this memory available for curation.").returncode, 0)
        ctx_cmd = _load_ctx_cmd_module()
        with mock.patch.dict(os.environ, self.env, clear=False):
            ws = ctx_cmd.lookup_workstream("curate-demo")
            self.assertIsNotNone(ws)
            entries = ctx_cmd._curation_entries(int(ws["id"]))
        self.assertTrue(entries)
        self.assertIn("Keep this memory available for curation.", entries[0]["content"])

    def test_list_hides_ephemeral_temp_workspaces_by_default(self):
        self.assertEqual(self.run_ctx("start", "root-demo", "--no-auto-pull").returncode, 0)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_ctx_in(Path(tmp), "start", "temp-demo", "--no-auto-pull").returncode, 0)
        listed = self.run_ctx("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("root-demo", listed.stdout)
        self.assertNotIn("temp-demo", listed.stdout)

    def test_web_hides_ephemeral_temp_workspaces_by_default(self):
        self.assertEqual(self.run_ctx("start", "root-web-demo", "--no-auto-pull").returncode, 0)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_ctx_in(Path(tmp), "start", "temp-web-demo", "--no-auto-pull").returncode, 0)
        env = os.environ.copy()
        env["ctx_DB"] = str(self.db_path)
        env["PYTHONPATH"] = str(ROOT)
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from contextfun.web import CtxWebApp; "
                    f"app=CtxWebApp(r'{self.db_path}'); "
                    "print([item['slug'] for item in app.workstreams(scope='all')])"
                ),
            ],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("root-web-demo", proc.stdout)
        self.assertNotIn("temp-web-demo", proc.stdout)


if __name__ == "__main__":
    unittest.main()
