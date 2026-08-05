-- WezTerm configuration.
--
-- Terminal + shell "chrome" is Catppuccin Mocha, deliberately DIFFERENT from
-- Neovim's Gruvbox: because nvim paints its own truecolor background, the
-- editor reads as gruvbox while everything around it (shell, prompt, tmux, ls)
-- reads as catppuccin — an at-a-glance "am I in the editor or the shell?" cue.
--
-- WezTerm is native truecolor (unlike Terminal.app's 256-color cap), so both
-- palettes render exactly. One file, checked into dotfiles, behaves identically
-- on macOS and Windows.

local wezterm = require("wezterm")
local config = wezterm.config_builder and wezterm.config_builder() or {}

-- Catppuccin Mocha ships built into WezTerm — no external color files needed.
config.color_scheme = "Catppuccin Mocha"

-- JetBrains Mono is bundled with WezTerm; fall back to Menlo if ever overridden.
config.font = wezterm.font_with_fallback({ "JetBrains Mono", "Menlo" })
config.font_size = 13.0

-- Chrome / ergonomics.
config.hide_tab_bar_if_only_one_tab = true
config.window_padding = { left = 6, right = 6, top = 6, bottom = 4 }
config.scrollback_lines = 50000
config.audible_bell = "Disabled"
config.default_cursor_style = "SteadyBar"
config.adjust_window_size_when_changing_font_size = false

-- macOS: right Option composes accents, left Option acts as Meta so tmux/zsh
-- Alt bindings (Alt-arrow pane nav, etc.) work.
config.send_composed_key_when_left_alt_is_pressed = false
config.send_composed_key_when_right_alt_is_pressed = true

return config
