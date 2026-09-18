/** @type {import('tailwindcss').Config} */
module.exports = {
  // Tailwind classes aren't just in templates: app/templates.py and
  // app/models.py centralise all status/severity/phase color classes as
  // Python string literals (e.g. STATUS_TAILWIND_BAR, PHASE_DOT) and Jinja
  // interpolates them (`{{ STATUS_TAILWIND_BAR[status] }}`). The scanner
  // only sees literal text, so those .py files must be scanned too, or
  // every one of those classes gets purged from the compiled CSS.
  content: ["./templates/**/*.html", "./app/**/*.py"],
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
