import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({
  baseDirectory: import.meta.dirname,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    ignores: [
      ".next/**",
      "next-env.d.ts",
      "src/generated/**",
      "tests/e2e/playwright-report/**",
      "tests/e2e/test-results/**",
    ],
  },
  {
    rules: {
      "react/no-unescaped-entities": "off",
    },
  },
  {
    files: [
      "scripts/**/*.{js,mjs,ts,mts}",
      "tests/**/*.{ts,tsx}",
      "a11y-*.mjs",
      "playwright.config.ts",
    ],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-require-imports": "off",
      "@typescript-eslint/no-unused-expressions": "off",
      "@typescript-eslint/no-unused-vars": "off",
    },
  },
];

export default eslintConfig;
