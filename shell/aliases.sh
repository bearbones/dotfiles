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
