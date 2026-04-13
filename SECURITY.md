# Security Notes

`ctx` is a local context and transcript management tool. It is not a sandbox and it does not reduce the underlying shell privileges of Claude Code, Codex, or any other agent runtime by itself.

## What `ctx` does help with

- Prevents accidental context drift by binding a workstream to exact Claude/Codex external session ids after first pull.
- Keeps branched workstreams independent so future transcript pulls do not bleed across branches.
- Stores data locally in SQLite and local attachment folders.

## What `ctx` does not do

- It does not restrict shell access.
- It does not stop an agent from reading or writing files the runtime already allows.
- It does not replace Codex/Claude approval mode or filesystem sandboxing.

## Recommended controls

- Keep agent approvals enabled for destructive or external actions.
- Use workspace-scoped sandboxes where available.
- Only grant macOS Accessibility permission if you need `--pull` or auto-paste helpers.
- Use a dedicated OS user, machine, or repo checkout for sensitive work.
- Review any transcript import source under `~/.claude/projects` and `~/.codex/sessions` as local sensitive data.

## High-trust operations in this repo

- `scripts/install.sh` and bootstrap one-liners execute downloaded shell code from GitHub.
- `--pull` uses AppleScript plus clipboard access on macOS.
- `ctx run ...` intentionally runs arbitrary shell commands and stores the output in context history.

## Reporting

If you find a security issue, avoid opening a public issue with exploit details. Contact the repo owner directly and include the exact command path, affected file, and impact.
