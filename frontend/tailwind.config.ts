import { fontFamily } from "tailwindcss/defaultTheme"

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["index.html", "src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Karla carries running text; Inter carries titles, labels and every
        // figure, because its tabular digits line up in columns.
        sans: ["Karla", ...fontFamily.sans],
        display: ["Inter", ...fontFamily.sans],
      },
      colors: {
        // Neutral ramp, light (1) to dark (7).
        n: {
          1: "#FEFEFE",
          2: "#F3F5F7",
          3: "#E8ECEF",
          4: "#6C7275",
          // n-4 fails contrast on the dark surfaces; this is its dark-mode twin.
          "4d": "#9CA1A4",
          5: "#343839",
          6: "#232627",
          7: "#141718",
        },
        primary: {
          // OnPoint Insights brand blue, sampled from the logo file.
          1: "#2369D2",
          // The brand blue lifted for marks on dark surfaces, where #2369D2
          // falls under 3:1 against the dark panels.
          "1d": "#4F8FEA",
          2: "#3FDD78",
        },
        accent: {
          1: "#D84C10",
          2: "#3E90F0",
          3: "#8E55EA",
          4: "#8C6584",
          5: "#DDA82A",
        },
      },
      borderRadius: {
        "2.5xl": "1.25rem",
      },
      boxShadow: {
        lift: "0 0 1rem 0.25rem rgba(0,0,0,0.04), 0 2rem 1.5rem -1rem rgba(0,0,0,0.12)",
        pill: "inset 0 0.0625rem 0 rgba(255,255,255,0.05), 0 0.25rem 0.5rem 0 rgba(0,0,0,0.1)",
        tile: "0 0.5rem 1.25rem -0.25rem rgba(35,105,210,0.45)",
      },
      keyframes: {
        "dot-pulse": {
          "0%, 80%, 100%": { opacity: "0.25", transform: "scale(0.8)" },
          "40%": { opacity: "1", transform: "scale(1)" },
        },
        // A chart bar rising from the zero line; the origin is set per bar.
        "bar-grow": {
          from: { transform: "scaleY(0)" },
          to: { transform: "scaleY(1)" },
        },
        // A horizontal bar filling out from its start (Insights bullet bars).
        "grow-x": {
          from: { transform: "scaleX(0)" },
          to: { transform: "scaleX(1)" },
        },
      },
      animation: {
        "dot-pulse": "dot-pulse 1.2s ease-in-out infinite",
        "bar-grow": "bar-grow 0.7s cubic-bezier(0.22, 1, 0.36, 1) both",
        "grow-x": "grow-x 0.8s cubic-bezier(0.22, 1, 0.36, 1) both",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}
