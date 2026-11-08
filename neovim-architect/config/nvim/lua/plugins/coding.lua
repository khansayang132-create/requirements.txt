vim.g.format_on_save = true

return {
  {
    "saghen/blink.cmp",
    version = "1.*", -- release tags ship a prebuilt fuzzy matcher
    event = { "InsertEnter", "CmdlineEnter" },
    dependencies = { "rafamadriz/friendly-snippets" },
    opts = {
      keymap = { preset = "default" }, -- <C-y> accept, <C-n>/<C-p> select, <C-space> open
      appearance = { nerd_font_variant = "mono" },
      completion = { documentation = { auto_show = true, auto_show_delay_ms = 300 } },
      signature = { enabled = true },
      sources = { default = { "lsp", "path", "snippets", "buffer" } },
      -- Falls back to the pure-Lua matcher if the binary can't load (e.g. Termux).
      fuzzy = { implementation = "prefer_rust" },
    },
  },
  {
    "stevearc/conform.nvim",
    event = "BufWritePre",
    cmd = "ConformInfo",
    keys = {
      { "<leader>cf", function() require("conform").format({ async = true, lsp_format = "fallback" }) end,
        mode = { "n", "v" }, desc = "Format buffer" },
      { "<leader>uf", function()
          vim.g.format_on_save = not vim.g.format_on_save
          vim.notify("Format on save: " .. (vim.g.format_on_save and "on" or "off"))
        end, desc = "Toggle format on save" },
    },
    opts = {
      formatters_by_ft = {
        lua = { "stylua" },
        python = { "ruff_format", "black", stop_after_first = true },
        javascript = { "prettier" }, typescript = { "prettier" },
        javascriptreact = { "prettier" }, typescriptreact = { "prettier" },
        html = { "prettier" }, css = { "prettier" }, json = { "prettier" },
        yaml = { "prettier" }, markdown = { "prettier" },
        sh = { "shfmt" }, bash = { "shfmt" },
        c = { "clang-format" }, cpp = { "clang-format" },
        go = { "gofmt" }, rust = { "rustfmt" },
      },
      format_on_save = function()
        if vim.g.format_on_save then return { timeout_ms = 1500, lsp_format = "fallback" } end
      end,
    },
  },
}
