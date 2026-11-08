local opt = vim.opt

vim.g.mapleader = " "
vim.g.maplocalleader = "\\"
-- Icons need a Nerd Font in the terminal. Set NVIM_NERD_FONT=0 to use plain text.
vim.g.have_nerd_font = vim.env.NVIM_NERD_FONT ~= "0"

opt.number = true
opt.relativenumber = true
opt.signcolumn = "yes"
opt.cursorline = true
opt.termguicolors = true
opt.scrolloff = 6
opt.wrap = false
opt.splitright = true
opt.splitbelow = true
opt.mouse = "a"
opt.showmode = false
opt.winborder = "rounded" -- floating windows (hover, signature, diagnostics)
opt.laststatus = 3

-- Indentation
opt.expandtab = true
opt.shiftwidth = 2
opt.tabstop = 2
opt.smartindent = true
opt.breakindent = true

-- Search
opt.ignorecase = true
opt.smartcase = true
opt.inccommand = "split"
if vim.fn.executable("rg") == 1 then
  opt.grepprg = "rg --vimgrep --smart-case"
  opt.grepformat = "%f:%l:%c:%m"
end

-- Persistence
opt.undofile = true
opt.swapfile = false
opt.updatetime = 250
opt.timeoutlen = 400
opt.sessionoptions = { "buffers", "curdir", "tabpages", "winsize", "help", "globals" }

-- Folding (treesitter sets foldexpr per buffer); start unfolded
opt.foldlevel = 99
opt.foldlevelstart = 99

-- Clipboard: only when a provider exists (xclip/wl-copy/termux-clipboard/pbcopy),
-- otherwise every yank would print "No provider".
vim.schedule(function()
  if vim.fn.has("clipboard") == 1 then opt.clipboard = "unnamedplus" end
end)

vim.diagnostic.config({
  severity_sort = true,
  virtual_text = { spacing = 2, source = "if_many" },
  float = { source = "if_many" },
  underline = true,
  signs = vim.g.have_nerd_font and {
    text = {
      [vim.diagnostic.severity.ERROR] = " ",
      [vim.diagnostic.severity.WARN] = " ",
      [vim.diagnostic.severity.INFO] = " ",
      [vim.diagnostic.severity.HINT] = "󰌵 ",
    },
  } or true,
})
