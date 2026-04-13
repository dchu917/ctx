Keyboard Maestro Macros
=======================

This folder contains ready-to-import macro definitions to trigger ContextFun skills from any app and paste a status line back into chat.

Import steps
- Open Keyboard Maestro → File → Import Macros… → select `ContextFun.kmmacros`.
- Grant your terminal/automation app Accessibility rights if prompted.
- Edit the shell command paths inside the macros to point to your clone (absolute path).

Macros included
- ctx resume: On typing `/ctx resume` (optionally followed by a name), runs `scripts/skills/ctx_resume_skill.py`, copies output to clipboard, and pastes.
- ctx start: On typing `/ctx start` (optionally followed by a name), runs `scripts/skills/ctx_start_skill.py`, copies output to clipboard, and pastes.

Notes
- You can change the triggers from typed string to hotkeys if preferred.
- If you’ve installed the global CLI (`scripts/quickstart.sh --global`), you can adapt macros to run the `ctx` shim or the skill paths in `~/.contextfun`.

