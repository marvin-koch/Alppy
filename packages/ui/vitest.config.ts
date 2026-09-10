import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    // Only src. The library ships no other test-shaped files today, but an
    // explicit include is what keeps a future fixture or an example from
    // being collected as a suite.
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
