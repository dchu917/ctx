import importlib.util
import contextlib
import json
import os
import sqlite3
import subprocess
import sys
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

    def write_executable(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

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
                env={**self.env, "CONTEXTFUN_DB": str(db_path)},
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

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

    def test_curation_delete_confirmation_requires_double_d(self):
        ctx_cmd = _load_ctx_cmd_module()
        self.assertEqual(
            ctx_cmd._curation_delete_prompt(42),
            "Confirm delete entry 42: press d again to delete, any other key to cancel.",
        )
        self.assertTrue(ctx_cmd._curation_delete_confirmed(ord("d")))
        self.assertTrue(ctx_cmd._curation_delete_confirmed(ord("D")))
        self.assertFalse(ctx_cmd._curation_delete_confirmed(ord("y")))

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

    def test_delete_entry_ids_removes_saved_entries_from_ctx_memory(self):
        self.assertEqual(self.run_ctx("start", "inline-delete-demo", "--no-auto-pull").returncode, 0)
        self.assertEqual(self.run_ctx("note", "Delete this note from ctx memory.").returncode, 0)
        self.assertEqual(self.run_ctx("note", "Delete this follow-up note too.").returncode, 0)
        self.assertEqual(self.run_ctx("decision", "Keep this decision after inline delete.").returncode, 0)

        ctx_cmd = _load_ctx_cmd_module()
        with mock.patch.dict(os.environ, self.env, clear=False):
            ws = ctx_cmd.lookup_workstream("inline-delete-demo")
            self.assertIsNotNone(ws)
            entries = ctx_cmd._curation_entries(int(ws["id"]))

        delete_ids = [
            item["id"]
            for item in entries
            if item["content"] in {"Delete this note from ctx memory.", "Delete this follow-up note too."}
        ]
        keep_entry = next(item for item in entries if item["content"] == "Keep this decision after inline delete.")

        deleted = self.run_ctx("delete", "--entry-id", f"E{delete_ids[0]},{delete_ids[1]}")
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        self.assertIn(f"Deleted entry {delete_ids[0]}", deleted.stdout)
        self.assertIn(f"Deleted entry {delete_ids[1]}", deleted.stdout)

        resumed = self.run_ctx("resume", "inline-delete-demo", "--no-auto-pull", "--no-compress")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertNotIn("Delete this note from ctx memory.", resumed.stdout)
        self.assertNotIn("Delete this follow-up note too.", resumed.stdout)
        self.assertIn("Keep this decision after inline delete.", resumed.stdout)

        with mock.patch.dict(os.environ, self.env, clear=False):
            entries_after = ctx_cmd._curation_entries(int(ws["id"]))
        remaining_ids = {item["id"] for item in entries_after}
        self.assertNotIn(delete_ids[0], remaining_ids)
        self.assertNotIn(delete_ids[1], remaining_ids)
        self.assertIn(keep_entry["id"], remaining_ids)

    def test_resume_output_surfaces_inline_entry_delete_commands(self):
        self.assertEqual(self.run_ctx("start", "inline-delete-hint-demo", "--no-auto-pull").returncode, 0)
        self.assertEqual(self.run_ctx("note", "Prune this line from ctx memory if it becomes stale.").returncode, 0)

        ctx_cmd = _load_ctx_cmd_module()
        with mock.patch.dict(os.environ, self.env, clear=False):
            ws = ctx_cmd.lookup_workstream("inline-delete-hint-demo")
            self.assertIsNotNone(ws)
            entry = ctx_cmd._curation_entries(int(ws["id"]))[0]

        resumed = self.run_ctx("resume", "inline-delete-hint-demo", "--no-auto-pull", "--no-compress")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIn(f"E{entry['id']} S", resumed.stdout)
        self.assertIn(f"ctx delete --entry-id E{entry['id']}", resumed.stdout)
        self.assertIn("ctx curate inline-delete-hint-demo", resumed.stdout)
        self.assertIn("These actions change ctx memory only", resumed.stdout)

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
