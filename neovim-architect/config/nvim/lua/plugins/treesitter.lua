-- nvim-treesitter `main` branch (the maintained rewrite). It does not lazy-load.
-- Parsers are compiled locally: needs tree-sitter CLI 0.26.1+ and a C compiler.
local parsers = require("lsk.ts_parsers")

return {
  {
    "nvim-treesitter/nvim-treesitter",
    branch = "main",
    lazy = false,
    build = ":TSUpdate",
    config = function()
      local ts = require("nvim-treesitter")
      -- Interactive sessions fill in missing parsers in the background; headless
      -- runs (install.sh) call install():wait() explicitly instead.
      if #vim.api.nvim_list_uis() > 0 and vim.fn.executable("tree-sitter") == 1 then
        local missing = vim.tbl_filter(function(p)
          return not vim.list_contains(ts.get_installed(), p)
        end, parsers)
        if #missing > 0 then ts.install(missing) end
      end

      vim.api.nvim_create_autocmd("FileType", {
        group = vim.api.nvim_create_augroup("lsk_treesitter", { clear = true }),
        desc = "Start treesitter highlight, indent and folds",
        callback = function(ev)
          local lang = vim.treesitter.language.get_lang(ev.match)
          if not lang or not pcall(vim.treesitter.start, ev.buf, lang) then return end
          vim.wo.foldmethod = "expr"
          vim.wo.foldexpr = "v:lua.vim.treesitter.foldexpr()"
          vim.bo[ev.buf].indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
        end,
      })
    end,
  },
}
