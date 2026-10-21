#!/bin/bash
# Standalone installer for the personal-configs subtree.
# Usage: ./install.sh [--force] [--shell]
#   --shell  also link ~/.zshrc (personal machines; work machines own their zshrc)

set -e

DOTFILES="$(cd "$(dirname "$0")" && pwd)"
FORCE=false
SHELL_RC=false

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        --shell) SHELL_RC=true ;;
    esac
done

echo "Installing personal dotfiles from $DOTFILES"

link_file() {
    local src="$1"
    local dst="$2"

    if [[ -e "$dst" ]] && [[ ! -L "$dst" ]]; then
        if [[ "$FORCE" == true ]]; then
            echo "  Backing up $dst -> $dst.bak"
            mv "$dst" "$dst.bak"
        else
            echo "  Skipping $dst (exists, use --force to override)"
            return
        fi
    fi

    if [[ -L "$dst" ]]; then
        rm "$dst"
    fi

    echo "  Linking $dst -> $src"
    ln -s "$src" "$dst"
}

echo ""
echo "==> Git config"
link_file "$DOTFILES/git/gitconfig" "$HOME/.gitconfig"

echo ""
echo "==> Tmux config"
link_file "$DOTFILES/tmux/tmux.conf" "$HOME/.tmux.conf"

echo ""
echo "==> Vim config"
mkdir -p "$HOME/.vim"
link_file "$DOTFILES/vim/vimrc" "$HOME/.vimrc"

echo ""
echo "==> Neovim config"
mkdir -p "$HOME/.config/nvim"
link_file "$DOTFILES/nvim/init.lua" "$HOME/.config/nvim/init.lua"

echo ""
echo "==> WezTerm config"
link_file "$DOTFILES/wezterm/wezterm.lua" "$HOME/.wezterm.lua"

echo ""
echo "==> Starship prompt"
mkdir -p "$HOME/.config"
link_file "$DOTFILES/shell/starship.toml" "$HOME/.config/starship.toml"

echo ""
echo "==> clangd config"
mkdir -p "$HOME/.config/clangd"
link_file "$DOTFILES/clangd/config.yaml" "$HOME/.config/clangd/config.yaml"

echo ""
echo "==> Git hooks"
mkdir -p "$HOME/.git-hooks"
for hook in "$DOTFILES/git/hooks/"*; do
    link_file "$hook" "$HOME/.git-hooks/$(basename "$hook")"
done

echo ""
echo "==> Global agent policy (Claude / Codex / Gemini / AGENTS)"
mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.gemini/config"
link_file "$DOTFILES/AGENTS.md" "$HOME/.claude/CLAUDE.md"
link_file "$DOTFILES/AGENTS.md" "$HOME/.claude/AGENTS.md"
link_file "$DOTFILES/AGENTS.md" "$HOME/.codex/AGENTS.md"
link_file "$DOTFILES/AGENTS.md" "$HOME/.gemini/config/AGENTS.md"
link_file "$DOTFILES/AGENTS.md" "$HOME/.gemini/config/GEMINI.md"

if [[ "$SHELL_RC" == true ]]; then
    echo ""
    echo "==> zshrc"
    link_file "$DOTFILES/shell/zshrc" "$HOME/.zshrc"
fi

echo ""
echo "Done! You may need to restart your shell or run: source ~/.zshrc"
