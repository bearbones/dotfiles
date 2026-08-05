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

-- ── Devspaces ─────────────────────────────────────────────────────────────
-- Coder writes `Host coder.<name>` aliases into ~/.ssh/config (with an absolute
-- ProxyCommand, so a plain `ssh` spawn works despite the minimal GUI PATH).
-- Read the primary host of each — skipping the `.dev`/`.main` agent aliases —
-- so both the launcher and the shortcut track whatever `ds` / `coder config-ssh`
-- last wrote, with nothing hardcoded.
local function devspace_hosts()
  local hosts, home = {}, os.getenv("HOME") or ""
  local f = io.open(home .. "/.ssh/config", "r")
  if not f then return hosts end
  for line in f:lines() do
    local h = line:match("^%s*[Hh]ost%s+(coder%.[^.%s]+)%s*$")
    if h then hosts[#hosts + 1] = h end
  end
  f:close()
  return hosts
end

-- Register each as an SSH domain. multiplexing="None" because devspaces don't
-- run a wezterm mux server — persistence comes from remote tmux, not wezterm.
-- This makes `wezterm connect coder.<name>` and the built-in launcher list them
-- (they drop you at the remote shell; run `work`/tmux there yourself).
config.ssh_domains = {}
for _, h in ipairs(devspace_hosts()) do
  table.insert(config.ssh_domains, { name = h, remote_address = h, multiplexing = "None" })
end

-- CMD+SHIFT+D → fuzzy-pick a devspace and open it in a NEW WINDOW attaching the
-- remote persistent tmux 'main' session — identical to the `ds` shell command,
-- so a dropped connection loses nothing (re-run to reconnect).
wezterm.on("open-devspace", function(window, pane)
  local choices = {}
  for _, h in ipairs(devspace_hosts()) do
    choices[#choices + 1] = { id = h, label = (h:gsub("^coder%.", "")) }
  end
  if #choices == 0 then
    window:toast_notification("wezterm",
      "No coder.* hosts in ~/.ssh/config — run `ds` or `coder config-ssh` first", nil, 4000)
    return
  end
  window:perform_action(wezterm.action.InputSelector({
    title = "Attach devspace",
    fuzzy = true,
    choices = choices,
    action = wezterm.action_callback(function(win, p, id)
      if id then
        win:perform_action(wezterm.action.SpawnCommandInNewWindow({
          args = { "/usr/bin/ssh", "-t", id, "tmux new-session -A -s main" },
        }), p)
      end
    end),
  }), pane)
end)

config.keys = config.keys or {}
table.insert(config.keys, {
  key = "d", mods = "CMD|SHIFT",
  action = wezterm.action.EmitEvent("open-devspace"),
})

return config
