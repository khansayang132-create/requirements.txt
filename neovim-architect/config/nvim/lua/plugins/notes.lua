-- Knowledge management: nvim-orgmode (pure Lua, no luarocks). Chosen over
-- Neorg, which needs luarocks/rocks.nvim — fragile on Termux.
local notes = vim.fn.expand("~/Developer/Notes")

return {
  {
    "nvim-orgmode/orgmode",
    ft = "org",
    keys = {
      { "<leader>oa", function() require("orgmode").action("agenda.prompt") end, desc = "Org agenda" },
      { "<leader>oc", function() require("orgmode").action("capture.prompt") end, desc = "Org capture" },
      { "<leader>on", function() vim.cmd.edit(notes .. "/inbox.org") end, desc = "Open notes inbox" },
      { "<leader>of", function() require("telescope.builtin").find_files({ cwd = notes }) end, desc = "Find note" },
    },
    opts = {
      org_agenda_files = notes .. "/**/*",
      org_default_notes_file = notes .. "/inbox.org",
    },
    config = function(_, opts)
      vim.fn.mkdir(notes, "p")
      require("orgmode").setup(opts)
    end,
  },
  {
    -- Optional: interactive evaluation for Lisps (Clojure, Fennel, Janet, Racket...).
    -- Off by default; enable with NVIM_CONJURE=1.
    "Olical/conjure",
    enabled = vim.env.NVIM_CONJURE == "1",
    ft = { "clojure", "fennel", "janet", "racket", "hy", "scheme", "guile" },
  },
}
