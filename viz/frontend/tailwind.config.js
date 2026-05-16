/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "#070809",
        card: "#0d0f14",
        border: "#1c1f26",
        good: "#00ff87",
        bad: "#ff3b3b",
        warn: "#ffd60a",
        active: "#ff8c00",
        muted: "#3d4151",
      },
      fontFamily: {
        sys: [
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      borderRadius: {
        card: "12px",
        pill: "8px",
      },
      letterSpacing: {
        widest: "0.2em",
      },
    },
  },
  plugins: [],
};
