# Global Agent Policy & Dotfiles Guide

This file is linked to `~/.claude/CLAUDE.md` and `~/.claude/AGENTS.md` by [`install.sh`](install.sh) so that its policies apply across all repositories on this machine, in addition to serving as the guide for the `dotfiles` repository itself.

---

## Global Policy: No Ephemeral Work Artifacts in Version Control

Temporary development artifacts must stay temporary or go into **GitHub Issues**, never into version control (`main` or feature branches):

1. **Never check momentary development notes or plans into VCS**:
   - Do **not** commit work-package or sprint plans (`docs/plans/**`, `docs/tasks/**`, `docs/handoffs/**`, `tasks/**`, `roadmap/**`).
   - Do **not** commit point-in-time design proposals or implementation notes (`docs/design-*.md`, `docs/*-proposal.md`, `dev/NOTES-*.md`, `milestone-notes.md`).
   - Do **not** commit one-off reviews, audits, investigation logs, or bug diagnoses (`docs/*-review.md`, `docs/investigations/**`, `docs/diagnoses/**`, `docs/superpowers/**`).
   - Do **not** commit roadmap/TODO/issue scratch files (`ROADMAP.md`, `CHARTER.md`, `docs/issues/**`, `docs/*-todos.md`).
2. **Use GitHub Issues for Plans, Proposals, and Follow-Up Work**:
   - Track feature designs, multi-step implementation plans, bug investigations, and follow-up tasks in GitHub Issues (`gh issue create`, `gh issue edit`, `gh issue comment`).
   - Once a feature or fix lands, any durable architectural invariant or user-facing behavior belongs in permanent reference documentation (`README.md`, `AGENTS.md`, or topical reference docs under `docs/`), and the transient plan/investigation stays in the closed Issue/PR history.
3. **Keep `docs/` Strictly for Durable Reference Documentation**:
   - Every file under `docs/` on `main` must describe the system **as it currently exists** for users or contributors (e.g., CLI/API contracts, check reference pages, extension guides, architecture reference).
4. **Use Untracked Scratch Space for Session Artifacts**:
   - Keep temporary scripts, benchmark outputs, reproducers, and working notes in gitignored scratch directories (`scratch/`, `/tmp/`) and clean them up when done.
5. **Pre-Commit Enforcement**:
   - `git/hooks/checks/04-ephemeral-docs.sh` blocks staging new or modified files matching known ephemeral artifact patterns (`SKIP=ephemeral-docs git commit` overrides when genuinely needed).

---

## `dotfiles` Repository Layout

- `install.sh` — Idempotent symlink installer (`./install.sh [--force] [--shell]`). Links git config/hooks, tmux, vim/nvim, WezTerm, Starship, clangd, and global agent instructions (`~/.claude/CLAUDE.md`, `~/.claude/AGENTS.md`).
- `git/` — `gitconfig` (default author: `Alex Mason <alex.mason.wire@gmail.com>`, used across personal desktop and Pop!_OS laptop; machine-local overrides go in `~/.gitconfig.local`) and global hooks (`~/.git-hooks`):
  - `pre-commit` dispatches `git/hooks/checks/[0-9]*.sh` (`01-conflict-markers.sh`, `02-debug-leftovers.sh`, `03-ruff.sh`, `04-ephemeral-docs.sh`).
  - `pre-push` guards against accidental large diffs (`LARGE_DIFF_OK=1` to override).
- `shell/` — `zshrc`, `common.sh`, `aliases.sh`, `colors.sh`, `starship.toml`.
- `nvim/` & `vim/` — Neovim (`init.lua`) and Vim (`vimrc`) configuration.
- `tmux/` & `wezterm/` — Multiplexer and terminal configuration.
- `wsl/` — WSL2 Ubuntu bootstrap (`wsl/bootstrap.sh`) and Windows keepalive setup.
- `claude/skills/` — Personal and workflow skills.
