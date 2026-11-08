-- Functional checks, run inside a real (headless) Neovim with the installed config:
--   nvim --headless -c "lua TEST='lsp'" -c "luafile tests/verify.lua"
-- Prints lines "RESULT|<id>|<PASS|FAIL|PARTIAL|NOT TESTED>|<detail>" then quits.
local SAMPLES = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":p:h") .. "/samples"

local function out(id, status, detail)
  io.stdout:write(("\nRESULT|%s|%s|%s\n"):format(id, status, (detail or ""):gsub("\n", " ")))
end
local function load(name) require("lazy").load({ plugins = { name } }) end

local tests = {}

function tests.config()
  local errs = {}
  for _, f in ipairs(vim.fn.globpath(vim.fn.stdpath("config"), "**/*.lua", false, true)) do
    local _, err = loadfile(f)
    if err then table.insert(errs, err) end
  end
  local msgs = vim.api.nvim_exec2("messages", { output = true }).output
  if msgs:match("E%d+:") or msgs:match("Error") then table.insert(errs, "startup messages: " .. msgs) end
  if #errs == 0 then out("config", "PASS", "all Lua files parse; no startup errors")
  else out("config", "FAIL", table.concat(errs, "; ")) end
end

function tests.plugins()
  local lazy = require("lazy")
  local missing, names = {}, {}
  for _, p in ipairs(lazy.plugins()) do
    table.insert(names, p.name)
    if not p._.installed then table.insert(missing, p.name) end
  end
  -- force-load every plugin to catch config errors
  local load_err = {}
  for _, p in ipairs(lazy.plugins()) do
    local ok, e = pcall(load, p.name)
    if not ok then table.insert(load_err, p.name .. ": " .. tostring(e)) end
  end
  if #missing == 0 and #load_err == 0 then
    out("plugins", "PASS", ("%d plugins installed and loaded: %s"):format(#names, table.concat(names, ", ")))
  else
    out("plugins", "FAIL", "missing: " .. table.concat(missing, ",") .. " load errors: " .. table.concat(load_err, "; "))
  end
end

function tests.health()
  -- { health check name, lazy plugin to load first }
  local checks = {
    { "vim.lsp", "nvim-lspconfig" }, { "vim.treesitter" }, { "vim.provider" }, { "lazy" },
    { "nvim-treesitter" }, { "telescope", "telescope.nvim" }, { "blink.cmp", "blink.cmp" },
    { "conform", "conform.nvim" }, { "which-key", "which-key.nvim" },
  }
  local summary, errors = {}, 0
  for _, c in ipairs(checks) do
    if c[2] then load(c[2]) end
    vim.cmd("silent! checkhealth " .. c[1])
    local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
    local e, w, first = 0, 0, nil
    for _, l in ipairs(lines) do
      if l:match("ERROR") then e = e + 1; first = first or vim.trim(l) end
      if l:match("WARNING") then w = w + 1 end
    end
    errors = errors + e
    table.insert(summary, ("%s: %d error, %d warn%s"):format(c[1], e, w, first and (" [" .. first .. "]") or ""))
    vim.cmd("silent! bwipeout!")
  end
  out("health", errors == 0 and "PASS" or "PARTIAL", table.concat(summary, "; "))
end

-- Open a file, wait for an LSP client, check diagnostics + definition.
local function lsp_case(file, server, expect_diag)
  vim.cmd.edit(SAMPLES .. "/" .. file)
  local buf = vim.api.nvim_get_current_buf()
  if not vim.wait(30000, function() return #vim.lsp.get_clients({ bufnr = buf, name = server }) > 0 end, 200) then
    return false, server .. " did not attach"
  end
  local got_diag = not expect_diag or vim.wait(30000, function() return #vim.diagnostic.get(buf) > 0 end, 200)
  return got_diag, ("%s attached, %d diagnostics"):format(server, #vim.diagnostic.get(buf))
end

function tests.lsp()
  load("nvim-lspconfig")
  local cases = {
    { "sample.lua", "lua_ls", true }, { "sample.py", "pyright", true },
    { "sample.ts", "ts_ls", true }, { "sample.sh", "bashls", false },
    { "sample.json", "jsonls", false }, { "sample.yaml", "yamlls", false },
    { "sample.html", "html", false }, { "sample.css", "cssls", false },
    { "sample.c", "clangd", true }, { "sample.rs", "rust_analyzer", false },
    { "sample.go", "gopls", false },
  }
  local S = require("lsk.servers")
  local passed, failed, skipped = {}, {}, {}
  for _, c in ipairs(cases) do
    if not S.runnable(S.servers[c[2]].bin) then
      table.insert(skipped, c[2])
    else
      local ok, detail = lsp_case(c[1], c[2], c[3])
      table.insert(ok and passed or failed, detail)
    end
  end
  -- go-to-definition on the Lua sample: `greet` call -> its definition on line 2
  vim.cmd.edit(SAMPLES .. "/sample.lua")
  local buf = vim.api.nvim_get_current_buf()
  local client = vim.lsp.get_clients({ bufnr = buf, name = "lua_ls" })[1]
  if client then
    -- position on the `greet` call inside print(greet("world"))
    local pos = vim.fn.searchpos([[print(\zsgreet]], "n")
    local resp = client:request_sync("textDocument/definition", {
      textDocument = { uri = vim.uri_from_bufnr(buf) }, position = { line = pos[1] - 1, character = pos[2] - 1 },
    }, 10000, buf)
    local res = resp and resp.result
    local loc = res and (res[1] or res)
    local def_line = loc and (loc.range or loc.targetRange).start.line
    if def_line == 1 then table.insert(passed, "lua_ls go-to-definition ok")
    else table.insert(failed, "lua_ls definition returned " .. vim.inspect(def_line)) end
  end
  local status = #failed == 0 and (#skipped == 0 and "PASS" or "PARTIAL") or "FAIL"
  out("lsp", status, ("ok: %s | failed: %s | not installed: %s"):format(
    table.concat(passed, "; "), table.concat(failed, "; "), table.concat(skipped, ", ")))
end

function tests.completion()
  load("nvim-lspconfig"); load("blink.cmp")
  vim.cmd.edit(SAMPLES .. "/sample.lua")
  local buf = vim.api.nvim_get_current_buf()
  local attached = vim.wait(30000, function() return #vim.lsp.get_clients({ bufnr = buf, name = "lua_ls" }) > 0 end, 200)
  local items, has_greet = 0, false
  if attached then
    local client = vim.lsp.get_clients({ bufnr = buf, name = "lua_ls" })[1]
    local n = vim.api.nvim_buf_line_count(buf)
    vim.api.nvim_buf_set_lines(buf, n, n, false, { "gre" })
    -- lua_ls indexes the workspace after attach; retry until it answers
    vim.wait(30000, function()
      local resp = client:request_sync("textDocument/completion", {
        textDocument = { uri = vim.uri_from_bufnr(buf) }, position = { line = n, character = 3 },
      }, 5000, buf)
      local r = resp and resp.result
      local list = r and (r.items or r) or {}
      items = #list
      for _, it in ipairs(list) do if it.label:match("^greet") then has_greet = true end end
      return has_greet
    end, 500)
  end
  -- snippet engine: expand a snippet with a placeholder and check the text
  vim.cmd.enew()
  vim.cmd.startinsert()
  vim.snippet.expand("local ${1:name} = ${2:value}")
  local text = vim.api.nvim_get_current_line()
  vim.cmd.stopinsert()
  local snippets = #vim.fn.globpath(vim.fn.stdpath("data"), "lazy/friendly-snippets/snippets/lua/*.json", false, true)
  local blink_ok = package.loaded["blink.cmp"] ~= nil
  local ok = has_greet and text == "local name = value" and snippets > 0 and blink_ok
  out("completion", ok and "PASS" or "FAIL", ("lua_ls completion for 'gre': %d items, includes greet(): %s; snippet expand -> %q; friendly-snippets lua files: %d; blink.cmp loaded: %s")
    :format(items, tostring(has_greet), text, snippets, tostring(blink_ok)))
end

function tests.search()
  load("telescope.nvim")
  local fzf = pcall(require("telescope").load_extension, "fzf")
  -- Open the real pickers and read their result counts.
  local function count(fn, opts)
    require("telescope.builtin")[fn](opts)
    local n = 0
    vim.wait(10000, function()
      local p = require("telescope.actions.state").get_current_picker(vim.api.nvim_get_current_buf())
      n = p and p.manager and p.manager:num_results() or 0
      return n > 0
    end, 100)
    vim.api.nvim_input("<Esc><Esc>"); vim.wait(300)
    return n
  end
  local want = #vim.fn.glob(SAMPLES .. "/*", false, true)
  local files = count("find_files", { cwd = SAMPLES })
  local grep = count("live_grep", { cwd = SAMPLES, default_text = "ARCHITECT_MARKER" })
  local bufs = count("buffers", {})
  local ok = files == want and grep == 1 and bufs > 0
  out("search", ok and "PASS" or "FAIL", ("find_files: %d/%d sample files; live_grep 'ARCHITECT_MARKER': %d hit (expect 1); buffers picker: %d; fzf-native sorter: %s")
    :format(files, want, grep, bufs, tostring(fzf)))
end

function tests.git()
  local dir = vim.fn.tempname()
  vim.fn.mkdir(dir, "p")
  local function git(...) return vim.system({ "git", "-C", dir, ... }, { text = true }):wait() end
  git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
  vim.fn.writefile({ "one", "two" }, dir .. "/f.txt")
  git("add", "."); git("commit", "-qm", "init")
  vim.fn.writefile({ "one", "TWO changed", "three" }, dir .. "/f.txt")
  vim.cmd.edit(dir .. "/f.txt")
  local buf = vim.api.nvim_get_current_buf()
  load("gitsigns.nvim"); load("vim-fugitive")
  vim.cmd("doautocmd BufReadPost")
  local hunks
  vim.wait(10000, function()
    hunks = require("gitsigns").get_hunks(buf)
    return hunks and #hunks > 0
  end, 200)
  local head = vim.fn.FugitiveHead()
  local n = hunks and #hunks or 0
  out("git", (n > 0 and head ~= "") and "PASS" or "FAIL",
    ("gitsigns hunks: %d; fugitive branch: %q"):format(n, head))
end

function tests.terminal()
  load("toggleterm.nvim")
  vim.cmd("ToggleTerm direction=float")
  local opened = vim.wait(5000, function() return vim.bo.buftype == "terminal" end)
  local job = vim.b.terminal_job_id
  local running = job and vim.fn.jobwait({ job }, 0)[1] == -1
  vim.cmd("ToggleTerm")
  local closed = vim.bo.buftype ~= "terminal"
  out("terminal", (opened and running and closed) and "PASS" or "FAIL",
    ("opened: %s, shell running: %s, closed: %s"):format(tostring(opened), tostring(running), tostring(closed)))
end

function tests.treesitter()
  local installed = require("nvim-treesitter").get_installed()
  local want = require("lsk.ts_parsers")
  local missing = vim.tbl_filter(function(p) return not vim.list_contains(installed, p) end, want)
  vim.cmd.edit(SAMPLES .. "/sample.lua")
  vim.cmd("doautocmd FileType lua")
  local buf = vim.api.nvim_get_current_buf()
  local ok_parse, tree = pcall(function() return vim.treesitter.get_parser(buf, "lua"):parse()[1] end)
  local hl = vim.treesitter.highlighter.active[buf] ~= nil
  local status = (#missing == 0 and ok_parse and hl) and "PASS" or ((ok_parse and hl) and "PARTIAL" or "FAIL")
  out("treesitter", status, ("parsers %d/%d installed (missing: %s); lua parse: %s; highlighter active: %s")
    :format(#want - #missing, #want, table.concat(missing, ","), ok_parse and tree:root():type() or "fail", tostring(hl)))
end

function tests.format()
  load("conform.nvim")
  local conform = require("conform")
  local avail = {}
  for _, f in ipairs(vim.fn.glob(SAMPLES .. "/sample.*", false, true)) do
    vim.cmd.edit(f)
    local names = vim.tbl_map(function(x) return x.name end,
      vim.tbl_filter(function(x) return x.available end, conform.list_formatters(0)))
    table.insert(avail, ("%s=%s"):format(vim.fn.fnamemodify(f, ":e"), #names > 0 and table.concat(names, "+") or "lsp/none"))
  end
  -- Real format run on badly indented Lua in a scratch buffer
  vim.cmd.enew(); vim.bo.filetype = "lua"
  vim.api.nvim_buf_set_lines(0, 0, -1, false, { "local   x={1,2}", "if x then", "print( x )", "end" })
  local ok = conform.format({ bufnr = 0, timeout_ms = 5000, lsp_format = "never" })
  local text = table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n")
  out("format", ok and text:match("^local x = { 1, 2 }") and "PASS" or "PARTIAL",
    ("lua format run: %s -> %q; available: %s"):format(tostring(ok), text, table.concat(avail, ", ")))
end

local ok, err = pcall(tests[TEST])
if not ok then out(TEST, "FAIL", "test crashed: " .. tostring(err)) end
vim.cmd("qa!")
