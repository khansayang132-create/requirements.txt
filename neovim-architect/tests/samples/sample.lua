-- ARCHITECT_MARKER: verify.lua expects greet() defined on line 2
local function greet(name)
  return "hello " .. name
end

print(greet("world"))
print(undefined_global_for_diagnostic) -- intentional warning
