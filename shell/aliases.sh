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

# work [session] — local tmux workspace with standard windows for a day's work.
# Attaches if the session already exists.
work() {
    local s="${1:-work}"
    if tmux has-session -t "$s" 2>/dev/null; then
        tmux attach -t "$s"; return
    fi
    tmux new-session -d -s "$s" -n claude-1
    tmux new-window  -t "$s" -n claude-2
    tmux new-window  -t "$s" -n scratch
    tmux new-window  -t "$s" -n serve
    tmux select-window -t "$s:claude-1"
    tmux attach -t "$s"
}
alias mux=work
