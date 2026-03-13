/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        mono: ["JetBrains Mono", "monospace"],
      },
      colors: {
        bg: "#0a0a0a",
        grid: "#1a1a1a",
        border: "#2a2a2a",
        text: "#e0e0e0",
        neon: {
          buy: "#00ff88",
          sell: "#ff2244",
          amber: "#ffbb00",
        },
      },
      animation: {
        pulse: "pulse 1.5s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
