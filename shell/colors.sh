# Catppuccin colors for the shell "chrome" — everything outside Neovim (which
# keeps its own Gruvbox theme). Sourced by BOTH zsh and bash via common.sh, so
# keep the top POSIX; zsh-only bits are guarded below.
# WezTerm renders 24-bit color, so the truecolor codes below land exactly.

# `ls` colors. macOS BSD `ls` reads LSCOLORS; GNU ls / eza / coreutils read
# LS_COLORS. Set both so listings are colored whichever `ls` is in use.
export CLICOLOR=1

# BSD LSCOLORS (fg,bg pairs: dir, symlink, socket, pipe, exec, ...). Limited to
# the 16-color palette — which WezTerm renders as Catppuccin — so: blue dirs,
# cyan links, magenta sockets, brown pipes, green executables.
export LSCOLORS="exgxfxdxcxegedabagacad"

# GNU LS_COLORS in Catppuccin truecolor (38;2;R;G;B). Covers common types; the
# rest fall back to the terminal palette (also Catppuccin).
export LS_COLORS="di=38;2;137;180;250:ln=38;2;148;226;213:so=38;2;245;194;231:pi=38;2;249;226;175:ex=38;2;166;227;161:bd=38;2;250;179;135:cd=38;2;250;179;135:or=38;2;243;139;168:mi=38;2;243;139;168:*.tar=38;2;235;160;172:*.tgz=38;2;235;160;172:*.zip=38;2;235;160;172:*.gz=38;2;235;160;172:*.png=38;2;203;166;247:*.jpg=38;2;203;166;247:*.svg=38;2;203;166;247:*.mp4=38;2;203;166;247:*.md=38;2;249;226;175"

# zsh-only interactive niceties.
if [ -n "$ZSH_VERSION" ]; then
    # Autosuggestion ghost text: Catppuccin overlay0 — dim enough to read as a
    # suggestion, not as typed input. (Read before the plugin loads in zshrc.)
    export ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE="fg=#6c7086"
    # Color the completion menu with the same LS_COLORS mapping.
    zstyle ':completion:*' list-colors "${(s.:.)LS_COLORS}"
    zstyle ':completion:*:default' list-colors "${(s.:.)LS_COLORS}"
fi
