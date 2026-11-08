local project = require("lsk.project")

local function builtin(name, opts)
  return function() require("telescope.builtin")[name](opts and opts() or {}) end
end
local at_root = function() return { cwd = project.root() } end

return {
  {
    "nvim-telescope/telescope.nvim",
    cmd = "Telescope",
    dependencies = {
      "nvim-lua/plenary.nvim",
      {
        "nvim-telescope/telescope-fzf-native.nvim",
        build = "make",
        cond = function() return vim.fn.executable("make") == 1 end,
      },
    },
    keys = {
      { "<leader><space>", builtin("find_files", at_root), desc = "Find files (project root)" },
      { "<leader>ff", builtin("find_files", at_root), desc = "Find files (project root)" },
      { "<leader>fg", builtin("live_grep", at_root), desc = "Live grep (project root)" },
      { "<leader>fw", builtin("grep_string", at_root), desc = "Grep word under cursor" },
      { "<leader>fb", builtin("buffers"), desc = "Buffers" },
      { "<leader>fr", builtin("oldfiles"), desc = "Recent files" },
      { "<leader>fs", builtin("lsp_document_symbols"), desc = "Document symbols" },
      { "<leader>fS", builtin("lsp_dynamic_workspace_symbols"), desc = "Workspace symbols" },
      { "<leader>fd", builtin("diagnostics"), desc = "Diagnostics" },
      { "<leader>fh", builtin("help_tags"), desc = "Help pages" },
      { "<leader>fk", builtin("keymaps"), desc = "Keymaps" },
      { "<leader>fR", builtin("registers"), desc = "Registers" },
      { "<leader>f/", builtin("current_buffer_fuzzy_find"), desc = "Search in buffer" },
      { "<leader>gc", builtin("git_commits"), desc = "Git commits" },
      { "<leader>po", project.pick, desc = "Open project" },
      { "<leader>pr", project.cd_root, desc = "cd to project root" },
    },
    config = function()
      local telescope = require("telescope")
      telescope.setup({
        defaults = { file_ignore_patterns = { "%.git/" }, layout_strategy = "flex" },
        pickers = { find_files = { hidden = true } },
      })
      pcall(telescope.load_extension, "fzf")
    end,
  },
  {
    "folke/todo-comments.nvim",
    event = { "BufReadPost", "BufNewFile" },
    dependencies = { "nvim-lua/plenary.nvim" },
    opts = { signs = vim.g.have_nerd_font },
    keys = {
      { "]t", function() require("todo-comments").jump_next() end, desc = "Next TODO comment" },
      { "[t", function() require("todo-comments").jump_prev() end, desc = "Previous TODO comment" },
      { "<leader>tt", "<cmd>TodoTelescope<cr>", desc = "Search TODO comments" },
    },
  },
  {
    "folke/persistence.nvim",
    event = "BufReadPre",
    opts = {},
    keys = {
      { "<leader>qs", function() require("persistence").load() end, desc = "Restore session (this dir)" },
      { "<leader>ql", function() require("persistence").load({ last = true }) end, desc = "Restore last session" },
      { "<leader>qd", function() require("persistence").stop() end, desc = "Don't save this session" },
    },
  },
  {
    "akinsho/toggleterm.nvim",
    version = "*",
    cmd = { "ToggleTerm", "TermExec" },
    opts = { open_mapping = [[<c-\>]], autochdir = true, shade_terminals = false },
    keys = {
      { [[<c-\>]], desc = "Toggle terminal" },
      { "<leader>tf", "<cmd>ToggleTerm direction=float<cr>", desc = "Floating terminal" },
      { "<leader>th", "<cmd>ToggleTerm direction=horizontal size=15<cr>", desc = "Horizontal terminal" },
      { "<leader>tv", "<cmd>ToggleTerm direction=vertical size=80<cr>", desc = "Vertical terminal" },
    },
  },
}
