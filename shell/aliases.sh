# Personal shell aliases - portable across machines

# Homebrew (macOS)
if [[ -x /opt/homebrew/bin/brew ]]; then
    alias brew=/opt/homebrew/bin/brew
fi

# Claude
if [[ -x /opt/homebrew/bin/claude ]]; then
    alias claude=/opt/homebrew/bin/claude
fi

# Coder CLI
if [[ -x /opt/homebrew/bin/coder ]]; then
    alias coder=/opt/homebrew/bin/coder
fi

# Serve the current directory (data visualizations, etc.) over HTTP.
alias serve='python3 -m http.server'

# Keep the machine awake between unattended local task runs.
alias redeye="$HOME/dotfiles/scripts/prevent-sleep"

# work [session] — local tmux workspace with standard windows for a day's work.
# Attaches if the session already exists. Windows:
#   claude-1/2  two agent sessions
#   dash        PR dashboard (prd) on top, a repo worker shell below — watch the
#               queue while acting on it (checkout branches, gh, etc.)
#   serve       an idle shell for `serve` (dataviz over HTTP)
#   scratch     a general shell
#   devspace    pre-seeded with `ds` (list) — one keystroke to attach a devspace
work() {
    local s="${1:-work}"
    if tmux has-session -t "$s" 2>/dev/null; then
        tmux attach -t "$s"; return
    fi
    local repo="${GAME_ENGINE_REPO_PATH:-$HOME/git/roblox/game-engine}"

    tmux new-session -d -s "$s" -n claude-1
    tmux new-window  -t "$s" -n claude-2

    # dash: dashboard pane (top 70%) over a worker shell rooted in the repo.
    # -l 30% sizes the NEW (bottom) pane, leaving the dashboard the top 70%.
    # Work-only: skipped on personal machines, which have no `prd`.
    if type prd >/dev/null 2>&1; then
        tmux new-window   -t "$s" -n dash
        tmux split-window -t "$s:dash" -v -l 30% -c "$repo"
        tmux send-keys    -t "$s:dash.0" 'prd' Enter   # render the dashboard on entry
        tmux select-pane  -t "$s:dash.0"
    fi

    tmux new-window  -t "$s" -n serve
    tmux new-window  -t "$s" -n scratch

    # devspace: `ds` with no args lists devspaces; type `ds <name>` to attach one.
    if type ds >/dev/null 2>&1; then
        tmux new-window  -t "$s" -n devspace
        tmux send-keys   -t "$s:devspace" 'ds' Enter
    fi

    tmux select-window -t "$s:claude-1"
    tmux attach -t "$s"
}
alias mux=work

# desk [session] — from the laptop, attach (or create) the `work` tmux session
# on the Windows desktop's WSL distro over Tailscale SSH. Re-run to reconnect.
desk() {
    ssh -t "${DESKTOP_HOST:-desktop}" "zsh -lic 'work ${1:-work}'"
}
