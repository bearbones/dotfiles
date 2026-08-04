-- Neovim configuration for C++ (game-engine) work.
-- Mirrors ~/dotfiles/personal/vim/vimrc ergonomics, then layers on clangd LSP,
-- Telescope fuzzy finding, Treesitter highlighting, and the Gruvbox theme.
-- Bootstraps its own plugin manager (lazy.nvim) on first launch.

-- Leader must be set before plugins load (keymaps bind against it).
vim.g.mapleader = ","
vim.g.maplocalleader = ","

-- =========================================================================
-- Core options (parity with the vim config)
-- =========================================================================
local o = vim.opt
o.number = true
o.relativenumber = true
o.expandtab = true
o.tabstop = 4
o.shiftwidth = 4
o.autoindent = true
o.smartindent = true
o.wrap = true
o.linebreak = true
o.breakindent = true
o.ignorecase = true
o.smartcase = true          -- case-sensitive only when the query has uppercase
o.hlsearch = true
o.incsearch = true
o.hidden = true
o.autowrite = true
o.autoread = true
o.scrolloff = 5
o.sidescrolloff = 5
o.mouse = ""                -- let the terminal own selection for cmd+C copy
o.undofile = true           -- persistent undo (dir defaults under stdpath state)
o.signcolumn = "yes"        -- stop the gutter from jumping when signs appear
o.updatetime = 250
o.completeopt = { "menu", "menuone", "noselect" }
o.termguicolors = true      -- 24-bit color (Gruvbox needs it)

-- ctags fallback: <C-]> jumps via this even when clangd is down.
-- ge-tags writes to <repo>/.git/tags; search upward from the file too.
o.tags:prepend("./.git/tags")
o.tags:append(".git/tags")

-- Y yanks to end of line (consistent with D and C).
vim.keymap.set("n", "Y", "y$")
-- System clipboard leader maps (match the vim config).
vim.keymap.set({ "n", "v" }, "<leader>y", '"+y')
vim.keymap.set("n", "<leader>Y", '"+y$')
vim.keymap.set({ "n", "v" }, "<leader>p", '"+p')
vim.keymap.set("n", "<leader>P", '"+P')
-- Clear search highlight.
vim.keymap.set("n", "<leader>/", "<cmd>nohlsearch<CR>")
vim.keymap.set("n", "<Esc><Esc>", "<cmd>nohlsearch<CR>", { silent = true })

-- =========================================================================
-- Bootstrap lazy.nvim
-- =========================================================================
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.loop.fs_stat(lazypath) then
  vim.fn.system({
    "git", "clone", "--filter=blob:none",
    "https://github.com/folke/lazy.nvim.git", "--branch=stable", lazypath,
  })
end
vim.opt.rtp:prepend(lazypath)

-- =========================================================================
-- Plugins
-- =========================================================================
require("lazy").setup({
  -- Theme -----------------------------------------------------------------
  {
    "ellisonleao/gruvbox.nvim",
    priority = 1000,             -- load before other plugins so UI is themed
    config = function()
      require("gruvbox").setup({ contrast = "hard" })
      vim.o.background = "dark"
      vim.cmd.colorscheme("gruvbox")
    end,
  },

  -- Syntax highlighting via Treesitter -----------------------------------
  {
    "nvim-treesitter/nvim-treesitter",
    branch = "main",             -- master is archived + breaks at runtime on nvim 0.12
    build = ":TSUpdate",
    config = function()
      -- The main branch installs parsers on demand and does NOT auto-enable
      -- highlighting; we install our languages then start core treesitter
      -- per buffer. markdown_inline is needed so LSP hover floats highlight.
      require("nvim-treesitter").install({
        "c", "cpp", "lua", "python", "bash", "json",
        "vim", "vimdoc", "markdown", "markdown_inline",
      })
      vim.api.nvim_create_autocmd("FileType", {
        callback = function()
          -- pcall guards filetypes whose parser isn't installed yet.
          pcall(vim.treesitter.start)
        end,
      })
    end,
  },

  -- Fuzzy finding ---------------------------------------------------------
  {
    "nvim-telescope/telescope.nvim",
    branch = "master",           -- 0.1.x predates nvim 0.11 make_position_params(encoding)
    dependencies = {
      "nvim-lua/plenary.nvim",
      -- Native FZF sorter: much faster on a repo this size. Needs `make`.
      { "nvim-telescope/telescope-fzf-native.nvim", build = "make" },
    },
    config = function()
      local telescope = require("telescope")
      telescope.setup({
        defaults = {
          -- Skip vendored / generated trees so live_grep and find_files stay fast.
          file_ignore_patterns = {
            "Client/dependencies/", "build.*/", "Client/Android/", "Client/iOS/", "%.git/",
          },
        },
      })
      pcall(telescope.load_extension, "fzf")
      local b = require("telescope.builtin")
      vim.keymap.set("n", "<leader>ff", b.find_files, { desc = "Find files" })
      vim.keymap.set("n", "<leader>fg", b.live_grep, { desc = "Live grep" })
      vim.keymap.set("n", "<leader>fb", b.buffers, { desc = "Buffers" })
      vim.keymap.set("n", "<leader>fr", b.oldfiles, { desc = "Recent files" })
      vim.keymap.set("n", "<leader>fs", b.lsp_dynamic_workspace_symbols, { desc = "Workspace symbols" })
      vim.keymap.set("n", "<leader>fd", b.diagnostics, { desc = "Diagnostics" })
    end,
  },

  -- LSP (clangd) ----------------------------------------------------------
  {
    "neovim/nvim-lspconfig",
    config = function()
      -- Per-buffer LSP keymaps; definitions/references route through Telescope
      -- for a searchable picker. <C-]> still uses ctags as a fallback.
      vim.api.nvim_create_autocmd("LspAttach", {
        callback = function(ev)
          local b = require("telescope.builtin")
          local map = function(keys, fn, desc)
            vim.keymap.set("n", keys, fn, { buffer = ev.buf, desc = desc })
          end
          map("gd", b.lsp_definitions, "Go to definition")
          map("gr", b.lsp_references, "References")
          map("gi", b.lsp_implementations, "Implementations")
          map("gy", b.lsp_type_definitions, "Type definition")
          map("K", vim.lsp.buf.hover, "Hover")
          map("<leader>rn", vim.lsp.buf.rename, "Rename symbol")
          map("<leader>ca", vim.lsp.buf.code_action, "Code action")
          map("[d", function() vim.diagnostic.jump({ count = -1 }) end, "Prev diagnostic")
          map("]d", function() vim.diagnostic.jump({ count = 1 }) end, "Next diagnostic")
        end,
      })

      -- nvim 0.11+ native LSP API. nvim-lspconfig ships the base clangd config
      -- (lsp/clangd.lua); we deep-merge overrides here, then enable it.
      vim.lsp.config("clangd", {
        cmd = {
          "clangd",
          "--background-index",
          "--header-insertion=never",     -- don't auto-insert #include on completion
          "--completion-style=detailed",
          "--function-arg-placeholders",
          "--offset-encoding=utf-16",      -- match Neovim's expected encoding
        },
        -- Find the project root (where compile_commands.json lives) even when
        -- editing headers deep in the tree.
        root_markers = { "compile_commands.json", ".git" },
      })
      vim.lsp.enable("clangd")
    end,
  },

  -- Git gutter + which-key hints -----------------------------------------
  { "lewis6991/gitsigns.nvim", config = true },
  { "folke/which-key.nvim", event = "VeryLazy", config = true },
}, {
  ui = { border = "rounded" },
})
