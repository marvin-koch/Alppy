// jest-dom's matchers are registered at runtime by vitest.setup.ts; this makes
// them visible to `tsc`. It lives under src because `rootDir` is src — a
// declaration file emits no JavaScript, and tsconfig.build.json keeps it out
// of the published dist alongside the tests it exists for.
import '@testing-library/jest-dom/vitest';
