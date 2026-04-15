import importlib.util
import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CTX_CMD = ROOT / "scripts" / "ctx_cmd.py"
INSTALL_SH = ROOT / "scripts" / "install.sh"
INSTALL_SKILLS_SH = ROOT / "scripts" / "install_skills.sh"
AGENT_SETUP_LOCAL_SH = ROOT / "scripts" / "agent_setup_local_ctx.sh"
CLI_PY = ROOT / "contextfun" / "cli.py"
WEB_PY = ROOT / "contextfun" / "web.py"


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
        self.env["CONTEXTFUN_DB"] = str(self.db_path)
        self.env["CTX_AUTOPULL_DEFAULT"] = "0"
        self.env["CODEX_HOME"] = str(self.codex_home)
        self.env["CLAUDE_HOME"] = str(self.claude_home)
        self.env["PYTHONPATH"] = str(ROOT)

    def tearDown(self):
        self.tmpdir.cleanup()

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
    ) -> Path:
        path = self.codex_home / "sessions" / f"{external_session_id}.jsonl"
        path.write_text(
            "\n".join(
                [
                    json.dumps({"id": external_session_id}),
                    json.dumps({"role": "user", "content": "Smoke transcript user message"}),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path

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

    def test_install_script_is_release_pinned_and_installs_skills(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn('DEFAULT_REF="v0.1.0"', text)
        self.assertIn('archive/refs/tags/', text)
        self.assertIn('rsync -a "$SRC_DIR/skills/" "$SKILLS_DIR/"', text)
        self.assertIn('install_skills.sh', text)
        self.assertIn('CTX_INSTALL_SKILLS', text)
        self.assertIn('install -m 0755 "$SRC_DIR/scripts/ctx_cmd.py" "$BIN_DIR/ctx"', text)
        self.assertNotIn("Compatibility aliases also work:", text)

    def test_local_agent_setup_script_is_release_pinned(self):
        text = AGENT_SETUP_LOCAL_SH.read_text(encoding="utf-8")
        self.assertIn('DEFAULT_REF="v0.1.0"', text)
        self.assertIn('archive/refs/tags/', text)
        self.assertIn("Downloading ctx into ./ctx", text)

    def test_cli_uses_stable_user_home_and_future_annotations(self):
        cli_text = CLI_PY.read_text(encoding="utf-8")
        web_text = WEB_PY.read_text(encoding="utf-8")
        ctx_text = CTX_CMD.read_text(encoding="utf-8")
        self.assertIn("from __future__ import annotations", cli_text)
        self.assertIn("from __future__ import annotations", web_text)
        self.assertIn("from __future__ import annotations", ctx_text)
        self.assertIn('CTX_HOME', cli_text)
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

    def test_skills_sh_skill_exists(self):
        skill_file = ROOT / "skills" / "ctx" / "SKILL.md"
        self.assertTrue(skill_file.exists())
        text = skill_file.read_text(encoding="utf-8")
        self.assertIn("name: ctx", text)
        self.assertIn("single `ctx` entrypoint", text)

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

    def test_pull_feedback_mentions_clipboard_fallback(self):
        ctx_cmd = _load_ctx_cmd_module()
        with mock.patch.object(ctx_cmd.subprocess, "check_output", return_value=b"clipboard text"), mock.patch.object(
            ctx_cmd, "run_ctx", return_value=""
        ):
            note = ctx_cmd._ingest_clipboard_into_session(
                1,
                fmt="markdown",
                source="codex",
                attempted_frontmost=True,
                frontmost_copied=False,
            )
        self.assertEqual(note, "Pull capture: frontmost copy failed; existing clipboard text was ingested instead.")

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
        env["CONTEXTFUN_DB"] = str(self.db_path)
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
