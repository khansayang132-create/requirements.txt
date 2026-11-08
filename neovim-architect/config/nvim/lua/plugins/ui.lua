local icons = vim.g.have_nerd_font

return {
  {
    "folke/tokyonight.nvim",
    lazy = false,
    priority = 1000,
    opts = { style = "night" },
    config = function(_, opts)
      require("tokyonight").setup(opts)
      vim.cmd.colorscheme("tokyonight")
    end,
  },
  { "nvim-tree/nvim-web-devicons", enabled = icons },
  {
    "nvim-lualine/lualine.nvim",
    event = "VeryLazy",
    opts = {
      options = {
        theme = "tokyonight",
        globalstatus = true,
        icons_enabled = icons,
        section_separators = icons and nil or "",
        component_separators = icons and nil or "|",
      },
      sections = {
        lualine_b = { "branch", "diff", "diagnostics" },
        lualine_c = { { "filename", path = 1 } },
        lualine_x = { "lsp_status", "filetype" },
      },
    },
  },
  {
    "akinsho/bufferline.nvim",
    event = "VeryLazy",
    opts = {
      options = {
        diagnostics = "nvim_lsp",
        show_buffer_icons = icons,
        always_show_bufferline = false,
        offsets = { { filetype = "NvimTree", text = "Files" } },
      },
    },
    keys = {
      { "<leader>bp", "<cmd>BufferLinePick<cr>", desc = "Pick buffer" },
      { "<leader>bo", "<cmd>BufferLineCloseOthers<cr>", desc = "Close other buffers" },
    },
  },
  {
    "nvim-tree/nvim-tree.lua",
    cmd = { "NvimTreeToggle", "NvimTreeFindFile" },
    keys = {
      { "<leader>e", "<cmd>NvimTreeToggle<cr>", desc = "File explorer" },
      { "<leader>E", "<cmd>NvimTreeFindFile<cr>", desc = "Reveal current file in explorer" },
    },
    opts = {
      sync_root_with_cwd = true,
      update_focused_file = { enable = true },
      renderer = { icons = { show = { file = icons, folder = icons, folder_arrow = true, git = true } } },
      filters = { dotfiles = false, custom = { "^.git$" } },
    },
  },
  {
    "folke/which-key.nvim",
    event = "VeryLazy",
    opts = {
      preset = "modern",
      icons = { mappings = icons },
      spec = {
        { "<leader>b", group = "buffer" },
        { "<leader>c", group = "code" },
        { "<leader>f", group = "find" },
        { "<leader>g", group = "git" },
        { "<leader>h", group = "help/docs" },
        { "<leader>o", group = "org notes" },
        { "<leader>p", group = "project" },
        { "<leader>q", group = "quit/session" },
        { "<leader>t", group = "terminal/todo" },
        { "<leader>u", group = "toggle" },
        { "<leader>x", group = "diagnostics" },
      },
    },
    keys = {
      { "<leader>?", function() require("which-key").show({ global = false }) end, desc = "Buffer-local keymaps" },
    },
  },
  {
    "j-hui/fidget.nvim", -- LSP progress + vim.notify notifications
    event = "VeryLazy",
    opts = { notification = { override_vim_notify = true } },
  },
}
