-- Language servers: name -> settings, with `bin` = executable that must be on PATH.
-- Shared by plugins/lsp.lua and tests/verify.lua.
-- `bin` is the executable that must be on PATH. It is listed explicitly
-- because some lspconfig definitions build `cmd` with a function.
local servers = {
  lua_ls = {
    bin = "lua-language-server",
    settings = {
      Lua = {
        runtime = { version = "LuaJIT" },
        diagnostics = { globals = { "vim" } },
        workspace = { checkThirdParty = false, library = { vim.env.VIMRUNTIME } },
        telemetry = { enable = false },
      },
    },
  },
  pyright = { bin = "pyright-langserver" },
  ts_ls = { bin = "typescript-language-server" },
  html = { bin = "vscode-html-language-server" },
  cssls = { bin = "vscode-css-language-server" },
  jsonls = { bin = "vscode-json-language-server" },
  yamlls = { bin = "yaml-language-server" },
  bashls = { bin = "bash-language-server" },
  clangd = { bin = "clangd" },
  gopls = { bin = "gopls" },
  rust_analyzer = { bin = "rust-analyzer" },
  jdtls = { bin = "jdtls" },
  marksman = { bin = "marksman" },
}

-- rustup installs a rust-analyzer proxy even when the component is missing;
-- only treat it as present if it actually runs.
local function runnable(bin)
  if vim.fn.executable(bin) == 0 then return false end
  if bin ~= "rust-analyzer" then return true end
  return vim.system({ bin, "--version" }):wait().code == 0
end

return { servers = servers, runnable = runnable }
