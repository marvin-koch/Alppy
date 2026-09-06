// ESLint for the web app.
//
// `pnpm lint` used to execute zero tasks — turbo declared a `lint` pipeline,
// no package defined a `lint` script, and no ESLint config or dependency
// existed anywhere. CI ran `turbo run lint typecheck build` and the lint third
// was a silent no-op, so "TypeScript: strict, no `any`" (CLAUDE.md) was
// enforced by `tsc` alone.
import tseslint from 'typescript-eslint';

export default [
  {
    ignores: ['.next/**', 'node_modules/**', 'e2e/**/*-snapshots/**', 'next-env.d.ts'],
  },
  ...tseslint.configs.recommended,
  {
    rules: {
      // The house rule, made enforceable.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
];
