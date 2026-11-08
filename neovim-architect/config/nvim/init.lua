-- Neovim Architect: entry point.
-- Requires Neovim 0.12+ (nvim-treesitter `main` and vim.lsp.config need it).
if vim.fn.has("nvim-0.12") == 0 then
  vim.api.nvim_echo({ { "Neovim Architect needs Neovim 0.12 or newer.", "ErrorMsg" } }, true, {})
  return
end

vim.loader.enable() -- built-in byte-code cache (replaces impatient.nvim)

require("lsk.options")
require("lsk.keymaps")
require("lsk.autocmds")
require("lsk.lazy")
