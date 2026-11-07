import type { Config } from "tailwindcss";

// Direction: graphite trading ledger (same tokens as the V2.0 terminal). Dark only on purpose.
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0e1116", surface: "#151a21", line: "#262e38", ink: "#e6e9ee", muted: "#9aa4b2",
        up: "#2fbf9f", down: "#ef7a6e", accent: "#e8b04b",
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
