import { createSystem, defaultConfig, defineConfig } from "@chakra-ui/react";

const config = defineConfig({
  globalCss: {
    "html, body, #root": { minHeight: "100%" },
    body: {
      margin: 0,
      bg: "canvas",
      color: "ink",
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "15px",
      lineHeight: "1.6",
    },
    "*": { boxSizing: "border-box" },
    "::selection": { bg: "brand.100", color: "gray.950" },
  },
  theme: {
    tokens: {
      fonts: {
        body: { value: "Inter, system-ui, sans-serif" },
        heading: { value: "Inter, system-ui, sans-serif" },
      },
      colors: {
        brand: {
          50: { value: "#fff8f1" },
          100: { value: "#ffead8" },
          200: { value: "#ffd4ad" },
          300: { value: "#ffb77a" },
          400: { value: "#f49346" },
          500: { value: "#ec7e24" },
          600: { value: "#d86b18" },
          700: { value: "#b95414" },
          800: { value: "#943f17" },
          900: { value: "#773616" },
          950: { value: "#401909" },
        },
        orange: {
          50: { value: "#fff8f1" },
          100: { value: "#ffead8" },
          200: { value: "#ffd4ad" },
          300: { value: "#ffb77a" },
          400: { value: "#f49346" },
          500: { value: "#ec7e24" },
          600: { value: "#d86b18" },
          700: { value: "#b95414" },
          800: { value: "#943f17" },
          900: { value: "#773616" },
          950: { value: "#401909" },
        },
      },
      radii: {
        panel: { value: "12px" },
        control: { value: "8px" },
      },
    },
    semanticTokens: {
      colors: {
        canvas: { value: { base: "#f7f7f8", _dark: "#0c0d0e" } },
        surface: { value: { base: "#ffffff", _dark: "#141516" } },
        subtle: { value: { base: "#f1f2f3", _dark: "#1c1e20" } },
        ink: { value: { base: "#181a1d", _dark: "#f4f4f5" } },
        muted: { value: { base: "#5f6670", _dark: "#a8adb4" } },
        border: { value: { base: "#dedfe2", _dark: "#303236" } },
        accent: { value: { base: "#ec7e24", _dark: "#f49346" } },
        danger: { value: { base: "#b42318", _dark: "#f97066" } },
        success: { value: { base: "#18794e", _dark: "#5fd09a" } },
      },
    },
  },
});

export const system = createSystem(defaultConfig, config);
