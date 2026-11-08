-- Fallback parser install for networks that block GitHub tarball downloads
-- (corporate proxies, some sandboxes) but allow `git fetch`. Fetches each
-- missing grammar at the SAME revision nvim-treesitter pins, then compiles it
-- from that local checkout. Used by scripts/install.sh; safe to run anytime:
--   nvim --headless -c 'lua require("lsk.ts_git_fallback").run()' -c qa
local M = {}

function M.run()
  local ts = require("nvim-treesitter")
  local parsers = require("nvim-treesitter.parsers")
  local cache = vim.fn.stdpath("cache") .. "/ts-git"
  local missing = vim.tbl_filter(function(p)
    return not vim.list_contains(ts.get_installed(), p)
  end, require("lsk.ts_parsers"))
  if #missing == 0 then print("ts_git_fallback: nothing missing") return end

  local ready, paths = {}, {}
  for _, lang in ipairs(missing) do
    local info = parsers[lang] and parsers[lang].install_info
    if info and info.url and info.revision then
      local dir = ("%s/%s@%s"):format(cache, vim.fs.basename(info.url), info.revision)
      if not vim.uv.fs_stat(dir .. "/.git") then
        vim.fn.mkdir(dir, "p")
        local steps = {
          { "git", "-C", dir, "init", "-q" },
          { "git", "-C", dir, "fetch", "-q", "--depth", "1", info.url, info.revision },
          { "git", "-C", dir, "checkout", "-q", "FETCH_HEAD" },
        }
        for _, cmd in ipairs(steps) do
          local r = vim.system(cmd, { text = true }):wait()
          if r.code ~= 0 then print(("ts_git_fallback: %s failed: %s"):format(lang, r.stderr)); dir = nil; break end
        end
      end
      if dir then paths[lang] = dir; table.insert(ready, lang) end
    end
  end
  -- install() reloads the parsers table and fires User TSUpdate (the documented
  -- hook for parser overrides), so the local paths must be applied there.
  vim.api.nvim_create_autocmd("User", {
    pattern = "TSUpdate",
    callback = function()
      local p = require("nvim-treesitter.parsers")
      for lang, dir in pairs(paths) do p[lang].install_info.path = dir end
    end,
  })
  print(("ts_git_fallback: compiling %d parsers from git checkouts"):format(#ready))
  ts.install(ready, { force = true }):wait(900000)
end

return M
