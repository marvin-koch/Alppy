import path from 'node:path';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    // `src` only, and never `e2e`. Those are Playwright specs: the two runners
    // share the `.spec.ts` suffix, and vitest collecting one would fail on
    // Playwright's fixtures rather than skipping it — a confusing red that
    // looks like a broken test instead of a misrouted file.
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**', '.next/**'],
  },
});
