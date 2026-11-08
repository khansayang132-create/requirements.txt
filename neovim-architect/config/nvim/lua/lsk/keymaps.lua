-- Core (plugin-independent) mappings. Plugin mappings live with their plugin spec.
-- Every mapping has a desc so which-key and :map show what it does.
local map = vim.keymap.set

map("n", "<Esc>", "<cmd>nohlsearch<cr>", { desc = "Clear search highlight" })
map("n", "<leader>w", "<cmd>write<cr>", { desc = "Save file" })
map("n", "<leader>q", "<cmd>confirm quit<cr>", { desc = "Quit window" })

-- Windows
map("n", "<C-h>", "<C-w>h", { desc = "Go to left window" })
map("n", "<C-j>", "<C-w>j", { desc = "Go to lower window" })
map("n", "<C-k>", "<C-w>k", { desc = "Go to upper window" })
map("n", "<C-l>", "<C-w>l", { desc = "Go to right window" })

-- Buffers
map("n", "<S-l>", "<cmd>bnext<cr>", { desc = "Next buffer" })
map("n", "<S-h>", "<cmd>bprevious<cr>", { desc = "Previous buffer" })
map("n", "<leader>bd", "<cmd>bdelete<cr>", { desc = "Delete buffer" })

-- Move selected lines
map("v", "J", ":m '>+1<cr>gv=gv", { desc = "Move selection down", silent = true })
map("v", "K", ":m '<-2<cr>gv=gv", { desc = "Move selection up", silent = true })
map("v", "<", "<gv", { desc = "Indent left, keep selection" })
map("v", ">", ">gv", { desc = "Indent right, keep selection" })

-- Diagnostics (]d / [d are Neovim defaults)
map("n", "<leader>cd", vim.diagnostic.open_float, { desc = "Line diagnostics" })
map("n", "<leader>xq", vim.diagnostic.setqflist, { desc = "Diagnostics to quickfix" })

-- Terminal: leave terminal mode with Esc Esc
map("t", "<Esc><Esc>", "<C-\\><C-n>", { desc = "Exit terminal mode" })

-- Git merge conflicts: jump between conflict markers
map("n", "]x", "<cmd>call search('^<<<<<<<\\|^=======\\|^>>>>>>>', 'W')<cr>", { desc = "Next conflict marker" })
map("n", "[x", "<cmd>call search('^<<<<<<<\\|^=======\\|^>>>>>>>', 'bW')<cr>", { desc = "Previous conflict marker" })

-- Documentation
map("n", "<leader>hc", function()
  vim.cmd.edit(vim.fn.stdpath("config") .. "/KEYBINDINGS.md")
end, { desc = "Open keybinding cheat sheet" })
map("n", "<leader>hl", function()
  vim.cmd.edit(vim.fn.expand("~/Developer/Neovim-Learning/README.md"))
end, { desc = "Open learning library index" })
