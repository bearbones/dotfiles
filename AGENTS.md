# Global Agent Policy & Dotfiles Guide

This file is linked to `~/.claude/CLAUDE.md`, `~/.claude/AGENTS.md`, `~/.codex/AGENTS.md`, and `~/.gemini/config/AGENTS.md` (`GEMINI.md`) by [`install.sh`](install.sh) so that its policies apply across all repositories on this machine, in addition to serving as the guide for the `dotfiles` repository itself.

---

## Global Policy: Performance & Data-Oriented Design (Best Practices)

Across all projects—and especially in simulation, graphics, solver, and systems code where performance is a primary concern—adhere strictly to these architectural and implementation rules:

### 1. Topology-Driven Data Flow, Never "Derive-on-Read"
- **Schedule computations by data-dependency topology, not on-demand getters:** When a quantity (e.g., cell mixture aggregate, effective heat capacity, partial volume, inertia, or geometric aperture) depends on state planes $A$ and $B$, compute and materialize that derived plane **once** at the exact point in the pipeline where $A$ or $B$ mutates, and pass the flat plane to all downstream consumers.
- **Ban hidden per-element reductions in accessors:** Never write innocent-looking helper functions (e.g., `cell_volume(state, i)`, `cell_capacity(state, i)`) that secretly loop over species/slots, re-validate material properties, or run compensated summations on every read. Downstream kernels should read flat precomputed arrays in $O(1)$.
- **Separate mutable trial state from frozen interval state:** In iterative solvers (Newton, line search, adaptive substepping), never bundle invariant planes into the trial struct that gets copied or swapped on every iteration. Only the quantities that actually vary inside the loop belong in the iteration's ping-pong buffers.

### 2. Zero Hot-Path Heap Allocations (Pre-Allocated Arenas & Buffer Swaps)
- **Reserve all memory upfront:** Every simulation tick, solver step, and transport pass must run with **zero heap allocations** once the domain shape is initialized.
- **No local `std::vector` temporaries in kernels:** Do not allocate full-grid `std::vector` scratch buffers, nested `std::vector<std::vector<...>>` accumulators, `std::map`/`std::set` trees, or `std::vector<bool>` bitvectors inside step functions or inner loops. Store scratch planes in a persistent workspace/arena owned by the system and swap buffers via pointer/handle exchange.
- **No `.insert()` / `.erase()` padding shifts:** Never pad boundary/ghost rows by copying full-grid vectors and calling `.insert(begin(), ...)` / `.erase(begin(), ...)`. Allocate grids with ghost capacity upfront and index into the interior view (`std::span`).
- **Use fixed compile-time capacities for bounded cardinalities:** Where a domain has a small bounded slot count (e.g., species per cell, stencil neighbors, contact points), use flat contiguous arrays or `std::array<T, kMax>` rather than pointer-chasing `std::vector`s of planes.

### 3. `noexcept` Hot Paths & Assertions Instead of Per-Cell Exceptions
- **Never run "unit tests in prod" inside hot loops:** Per-cell, per-face, and per-iteration kernels must be `noexcept`. Never place `throw` statements, `try`/`catch` blocks, string formatting (`std::ostringstream`), or constitutive property validation inside inner loops.
- **Validate once at system boundaries:** Validate authored material tables, configuration parameters, and external buffer shapes **once** at load, initialization, or system-import boundaries—never repeatedly per cell on every substep or solver probe.
- **Use debug assertions for internal invariants:** Express preconditions and representation invariants inside kernels with debug assertions (`assert(...)`), leaving release/production loops branch-free so the compiler can auto-vectorize (SIMD) and GPU shaders can execute without divergence.

### 4. SIMD- & GPU-Friendly Arithmetic and Layout
- **Structure-of-Arrays (SoA) & flat contiguous planes:** Lay out data for contiguous unit-stride streaming and coalesced GPU memory access. Avoid `std::optional<double>` or polymorphic dispatch inside per-cell records; resolve defaults at binding time.
- **Precompute reciprocals of invariant divisors:** Store `inv_density = 1.0 / density`, `inv_mass`, etc. when parameters are bound or prepared rather than issuing floating-point divisions inside inner loops.
- **Avoid branching compensated summation on tiny local reductions:** Reserve Neumaier/compensated summation for global/grid-wide conservation ledgers where $N \gg 1$. For summing 2–4 nonnegative slot values within a single cell, use flat fixed-order arithmetic that vectorizes cleanly across lanes.

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
