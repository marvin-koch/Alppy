// ESLint for the component library.
//
// This package had no `lint` script, so `pnpm lint` ran ESLint over the web app
// alone — and every F3 component (the matrix, the cell, the meter, the band
// glyphs) lives here. The house rules were enforced by `tsc` alone across the
// whole design system.
import tseslint from 'typescript-eslint';

export default [
  {
    ignores: ['dist/**', 'node_modules/**'],
  },
  ...tseslint.configs.recommended,
  {
    rules: {
      // The house rule, made enforceable here too.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
];
