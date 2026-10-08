#!/bin/bash
# Bootstrap a fresh WSL2 Ubuntu 24.04 distro into a personal build/agent box.
# Idempotent — safe to re-run after editing. Usage, from inside WSL:
#
#   git clone https://github.com/bearbones/dotfiles ~/dotfiles
#   ~/dotfiles/wsl/bootstrap.sh
#
# What it does: apt packages (toolchains, Vulkan/GPU userspace, CLI tools),
# newer-than-apt tools into ~/.local/bin (nvim, starship, tree-sitter, uv),
# rustup, gh, Tailscale, Claude Code, /etc/wsl.conf, zsh as login shell, then
# runs install.sh to link the configs.

set -euo pipefail

DOTFILES="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HOME/.local/bin"
mkdir -p "$BIN" "$HOME/git"
export PATH="$BIN:$HOME/.cargo/bin:$PATH"

step() { echo; echo "==> $*"; }
have() { command -v "$1" >/dev/null 2>&1; }

if ! grep -qi microsoft /proc/version; then
    echo "bootstrap.sh: this is meant for WSL" >&2
    exit 1
fi

step "apt packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    build-essential cmake ninja-build pkg-config meson \
    clang clangd clang-format clang-tidy lld mold ccache gdb lldb \
    git git-lfs curl wget unzip zip xz-utils ca-certificates gnupg \
    zsh zsh-autosuggestions zsh-syntax-highlighting tmux \
    ripgrep fd-find fzf bat jq htop btop tree \
    python3 python3-venv python3-pip \
    vulkan-tools libvulkan-dev mesa-vulkan-drivers mesa-utils \
    glslang-tools spirv-tools \
    libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev \
    libwayland-dev libxkbcommon-dev libgl-dev libasound2-dev libudev-dev
# Debian renames these binaries; expose the usual names.
ln -sf "$(command -v fdfind)" "$BIN/fd"
ln -sf "$(command -v batcat)" "$BIN/bat"

step "/etc/wsl.conf"
sed "s/__USER__/$USER/" "$DOTFILES/wsl/wsl.conf" | sudo tee /etc/wsl.conf >/dev/null

step "Neovim (release tarball; apt's is too old for the config)"
if ! have nvim || ! nvim --version | head -1 | grep -qE 'v0\.(1[1-9]|[2-9][0-9])'; then
    curl -fsSL https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz \
        | sudo tar -xz -C /opt
    ln -sf /opt/nvim-linux-x86_64/bin/nvim "$BIN/nvim"
fi

step "tree-sitter CLI (nvim-treesitter parser builds)"
if ! have tree-sitter; then
    curl -fsSL https://github.com/tree-sitter/tree-sitter/releases/latest/download/tree-sitter-linux-x64.gz \
        | gunzip > "$BIN/tree-sitter"
    chmod +x "$BIN/tree-sitter"
fi

step "starship"
have starship || curl -fsSL https://starship.rs/install.sh | sh -s -- -y -b "$BIN" >/dev/null

step "uv"
have uv || curl -fsSL https://astral.sh/uv/install.sh | sh -s -- --no-modify-path

step "rustup"
if [[ ! -x "$HOME/.cargo/bin/rustup" ]]; then
    curl -fsSL https://sh.rustup.rs | sh -s -- -y --no-modify-path
fi

step "GitHub CLI"
if ! have gh; then
    sudo mkdir -p -m 755 /etc/apt/keyrings
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
    sudo apt-get update -qq && sudo apt-get install -y -qq gh
fi

step "Tailscale (remote access from the laptop; runs inside WSL)"
have tailscale || curl -fsSL https://tailscale.com/install.sh | sh

step "Claude Code"
have claude || [[ -x "$BIN/claude" ]] || curl -fsSL https://claude.ai/install.sh | bash

step "Machine-local git identity (~/.gitconfig.local)"
if [[ ! -e "$HOME/.gitconfig.local" ]]; then
    cat > "$HOME/.gitconfig.local" <<'EOF'
# Machine-local overrides, included last by ~/.gitconfig. Not in dotfiles.
[user]
    email = alex.mason.wire@gmail.com
[credential]
    helper =
    helper = !gh auth git-credential
EOF
fi

step "Linking configs"
"$DOTFILES/install.sh" --shell

step "Login shell -> zsh"
[[ "$(getent passwd "$USER" | cut -d: -f7)" == "$(command -v zsh)" ]] || sudo chsh -s "$(command -v zsh)" "$USER"

step "GPU check"
if [[ -e /dev/dxg ]]; then
    /usr/lib/wsl/lib/nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null \
        || echo "  /dev/dxg present but nvidia-smi failed — update the Windows NVIDIA driver"
    vulkaninfo --summary 2>/dev/null | grep -E 'deviceName|driverName' | sed 's/^/  /' || true
else
    echo "  No /dev/dxg — GPU passthrough unavailable (is this WSL2, not WSL1?)"
fi

cat <<'EOF'

Done. Remaining one-time steps (interactive):
  1. From PowerShell:  wsl --shutdown   (applies wsl.conf + systemd), then reopen
  2. gh auth login
  3. sudo tailscale up --ssh            (approve in browser)
  4. claude                             (log in)
EOF
