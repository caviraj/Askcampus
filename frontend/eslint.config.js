import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommendedTypeChecked,
      // Test files import describe/it/expect explicitly (no globals), so nothing
      // here needs a test-specific environment beyond the vitest globals absent
      // by design.
      // `configs.flat[...]`, not `configs[...]`: the plugin ships both shapes and
      // the un-namespaced one is the eslintrc form, whose `plugins` is an array
      // of strings that flat config rejects outright.
      reactHooks.configs.flat["recommended-latest"],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        project: ["./tsconfig.app.json", "./tsconfig.node.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    // Config files sit outside the app project's include list.
    files: ["*.config.{js,ts}"],
    extends: [tseslint.configs.disableTypeChecked],
  },
);
