import type { Config } from "tailwindcss";

// CADENCE — token-driven Tailwind theme. Colors map 1:1 to the CSS custom
// properties defined in app/globals.css (:root), so changing a token there
// re-themes both the raw CSS and every utility class below. Six colors only,
// plus the single permitted exception (#FF6B6B) for negative deltas.
const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
    "./lib/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    // Replace the default palette entirely — only our tokens exist.
    colors: {
      transparent: "transparent",
      current: "currentColor",
      void: "var(--void)",
      surface: "var(--surface)",
      edge: "var(--edge)",
      signal: "var(--signal)",
      ink: "var(--ink)",
      muted: "var(--muted)",
      negative: "var(--negative)",
      // Gamification accent palette — layered on top of the six core tokens.
      "xp-purple": "var(--xp-purple)",
      "xp-teal": "var(--xp-teal)",
      "xp-amber": "var(--xp-amber)",
      "xp-coral": "var(--xp-coral)",
      "xp-blue": "var(--xp-blue)",
    },
    // BSA's soft corners (it rounds cards and controls; the old theme's
    // sharp corners were its signature).
    borderRadius: {
      none: "0",
      sm: "6px",
      DEFAULT: "8px",
      lg: "12px",
      full: "9999px",
    },
    boxShadow: {
      none: "none",
    },
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        eyebrow: ["10px", { lineHeight: "1.2", letterSpacing: "0.12em" }],
        nav: ["13px", { lineHeight: "1.2" }],
        body: ["13px", { lineHeight: "1.45" }],
        // Defined panel/card title — Inter, sits below the uppercase eyebrow.
        title: ["15px", { lineHeight: "1.3", letterSpacing: "-0.01em" }],
        callout: ["32px", { lineHeight: "1", letterSpacing: "-0.02em" }],
        kpi: ["48px", { lineHeight: "1", letterSpacing: "-0.02em" }],
      },
      letterSpacing: {
        eyebrow: "0.12em",
      },
    },
  },
  plugins: [],
};

export default config;
