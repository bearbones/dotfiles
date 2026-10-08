# Shell setup shared by zsh and bash on personal machines. Keep it POSIX-ish;
# shell-specific bits live in zshrc. Sourced from ~/.zshrc (shell/zshrc).

DOTFILES="${DOTFILES:-$HOME/dotfiles}"

path_prepend() { case ":$PATH:" in *":$1:"*) ;; *) [ -d "$1" ] && PATH="$1:$PATH" ;; esac; }
path_append()  { case ":$PATH:" in *":$1:"*) ;; *) [ -d "$1" ] && PATH="$PATH:$1" ;; esac; }

path_prepend "$HOME/.cargo/bin"
path_prepend "$HOME/.local/bin"

# WSL: appendWindowsPath=false (see wsl/wsl.conf) keeps Windows binaries off
# PATH; add back only the ones worth having.
if [ -e /proc/sys/fs/binfmt_misc/WSLInterop ]; then
    export IS_WSL=1
    path_append "/mnt/c/Windows/System32"
    path_append "/mnt/c/Windows/System32/WindowsPowerShell/v1.0"
    path_append "/mnt/c/Program Files/Microsoft VS Code/bin"
    export BROWSER="explorer.exe"
fi
export PATH

export EDITOR=nvim
export VISUAL=nvim

# Build caches: ccache for C/C++, sized for a big disk.
export CCACHE_MAXSIZE=50G
export CMAKE_GENERATOR=Ninja

. "$DOTFILES/shell/colors.sh"
. "$DOTFILES/shell/aliases.sh"
