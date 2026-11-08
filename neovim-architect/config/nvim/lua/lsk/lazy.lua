-- Bootstrap lazy.nvim (pinned by lazy-lock.json; `:Lazy restore` returns to the lock).
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.uv.fs_stat(lazypath) then
  local out = vim.fn.system({
    "git", "clone", "--filter=blob:none", "--branch=stable",
    "https://github.com/folke/lazy.nvim.git", lazypath,
  })
  if vim.v.shell_error ~= 0 then
    vim.api.nvim_echo({ { "Failed to clone lazy.nvim:\n" .. out, "ErrorMsg" } }, true, {})
    return
  end
  -- Pin lazy.nvim itself to the lockfile: `Lazy restore` can't move the
  -- manager while it is running, so a fresh install would stay on `stable`.
  local ok, lock = pcall(function()
    return vim.json.decode(table.concat(vim.fn.readfile(vim.fn.stdpath("config") .. "/lazy-lock.json"), "\n"))
  end)
  local commit = ok and lock["lazy.nvim"] and lock["lazy.nvim"].commit
  if commit then vim.fn.system({ "git", "-C", lazypath, "checkout", "-q", commit }) end
end
vim.opt.rtp:prepend(lazypath)

require("lazy").setup({
  spec = { { import = "plugins" } },
  defaults = { lazy = true },
  install = { colorscheme = { "tokyonight", "habamax" } },
  checker = { enabled = false }, -- no background network; update with scripts/update.sh
  change_detection = { notify = false },
  rocks = { enabled = false }, -- no luarocks dependency
  ui = { icons = vim.g.have_nerd_font and {} or {
    cmd = "⌘", config = "🛠", event = "📅", ft = "📂", init = "⚙", keys = "🗝",
    plugin = "🔌", runtime = "💻", require = "🌙", source = "📄", start = "🚀",
    task = "📌", lazy = "💤 ",
  } },
  performance = {
    rtp = {
      -- Vim Tips Wiki as :help pages, if the learning library is installed
      paths = vim.tbl_filter(function(p) return vim.uv.fs_stat(p) ~= nil end,
        { vim.fn.expand("~/Developer/Neovim-Learning/03-Vim-Tips-Wiki") }),
      disabled_plugins = { "gzip", "tarPlugin", "tohtml", "tutor", "zipPlugin", "netrwPlugin" } },
  },
})
