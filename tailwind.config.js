/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"] },
      colors: {
        brand: {
          DEFAULT: "#005EA8",
          dark: "#004A87",
          light: "#1A73BE",
        },
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};
