-- Project root detection and a small "open project" picker (no extra plugin).
local M = {}

M.markers = { ".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Makefile", "init.lua" }
-- Folders scanned by <leader>po for git repositories (depth 3).
M.search_roots = { "~/Developer", "~/projects", "~/src", "~" }

function M.root(buf)
  local path = vim.api.nvim_buf_get_name(buf or 0)
  return vim.fs.root(path ~= "" and path or vim.uv.cwd(), M.markers) or vim.uv.cwd()
end

function M.cd_root()
  local root = M.root()
  vim.cmd.cd(root)
  vim.notify("cwd: " .. root)
end

function M.list()
  local seen, found = {}, {}
  for _, dir in ipairs(M.search_roots) do
    dir = vim.fs.normalize(dir)
    if vim.uv.fs_stat(dir) then
      for name in vim.fs.dir(dir, { depth = 3, skip = function(n) return n:sub(1, 1) ~= "." and n ~= "node_modules" end }) do
        if vim.fs.basename(name) == ".git" then
          local repo = vim.fs.joinpath(dir, vim.fs.dirname(name))
          if not seen[repo] then seen[repo] = true; table.insert(found, repo) end
        end
      end
    end
  end
  table.sort(found)
  return found
end

function M.pick()
  vim.ui.select(M.list(), { prompt = "Open project" }, function(choice)
    if not choice then return end
    vim.cmd.cd(choice)
    require("telescope.builtin").find_files({ cwd = choice })
  end)
end

vim.api.nvim_create_user_command("ProjectRoot", M.cd_root, { desc = "cd to project root" })

return M
