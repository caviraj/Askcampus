// One config for dev, build and test, so the three transforms cannot drift.
// `vitest/config`'s defineConfig is a superset of vite's and keeps the `test`
// block typed without a separate vitest.config.ts.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Tailwind never runs in tests. Assertions are on class names instead, which
    // is exactly AGENTS.md section 7's "do not hardcode hex values in
    // components" check -- a mistyped token is caught by `npm run build`.
    css: false,
    restoreMocks: true,
  },
});
