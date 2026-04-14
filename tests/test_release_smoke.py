import importlib.util
import contextlib
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
        self.env = os.environ.copy()
        self.env["CONTEXTFUN_DB"] = str(self.db_path)
        self.env["CTX_AUTOPULL_DEFAULT"] = "0"
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

    def test_resume_missing_is_clean(self):
        proc = self.run_ctx("resume", "missing-stream")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "No workstream matching 'missing-stream' exists.")
        self.assertEqual(proc.stderr.strip(), "")

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


if __name__ == "__main__":
    unittest.main()
