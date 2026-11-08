-- LSP via Neovim's built-in vim.lsp.config/enable; nvim-lspconfig supplies the
-- server definitions. A server is enabled only if its executable is on PATH,
-- so a missing language never errors. Servers are installed by the OS package
-- manager / npm (scripts/install.sh), not Mason: Mason's prebuilt binaries do
-- not run on Termux (Android bionic libc).
local S = require("lsk.servers")
local servers, runnable = S.servers, S.runnable

return {
  {
    "neovim/nvim-lspconfig",
    event = { "BufReadPre", "BufNewFile" },
    dependencies = { "saghen/blink.cmp" },
    config = function()
      vim.lsp.config("*", { capabilities = require("blink.cmp").get_lsp_capabilities() })

      for name, cfg in pairs(servers) do
        local bin = cfg.bin
        cfg = vim.deepcopy(cfg); cfg.bin = nil
        if next(cfg) then vim.lsp.config(name, cfg) end
        if runnable(bin) then vim.lsp.enable(name) end
      end

      vim.api.nvim_create_autocmd("LspAttach", {
        group = vim.api.nvim_create_augroup("lsk_lsp", { clear = true }),
        callback = function(ev)
          local function map(lhs, rhs, desc, mode)
            vim.keymap.set(mode or "n", lhs, rhs, { buffer = ev.buf, desc = desc })
          end
          -- Neovim defaults also apply: K hover, grn rename, gra action,
          -- grr references, gri implementation, gO symbols, <C-s> signature.
          map("gd", vim.lsp.buf.definition, "Go to definition")
          map("gD", vim.lsp.buf.declaration, "Go to declaration")
          map("<leader>cr", vim.lsp.buf.rename, "Rename symbol")
          map("<leader>ca", vim.lsp.buf.code_action, "Code action", { "n", "v" })
          map("<leader>cR", function() require("telescope.builtin").lsp_references() end, "Find references")
          map("<leader>ci", "<cmd>checkhealth vim.lsp<cr>", "LSP info")
          map("<leader>uh", function()
            vim.lsp.inlay_hint.enable(not vim.lsp.inlay_hint.is_enabled({ bufnr = ev.buf }), { bufnr = ev.buf })
          end, "Toggle inlay hints")
        end,
      })
    end,
  },
}
