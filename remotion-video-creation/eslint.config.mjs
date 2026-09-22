import {config} from "@remotion/eslint-config-flat";

export default [
  ...config,
  {
    linterOptions: {
      // Recovered third-party payloads carry explicit file-level suppressions.
      reportUnusedDisableDirectives: "off",
    },
  },
  {
    files: ["src/videos/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/ban-ts-comment": "off",
    },
  },
];
