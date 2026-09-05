#!/usr/bin/env node
/**
 * Verifies the invariant DESIGN.md §8 rests on:
 *
 *   "A colour defined only behind [data-theme] never applies in the unmarked
 *    state."
 *
 * The bare `:root` block must declare the COMPLETE light palette, and every
 * later block may only *redefine* those names — never introduce a new one.
 * A token that exists solely inside a dark block renders as an empty value for
 * every user on the default setting, and empty `var()` fails silently: no
 * error, no fallback, just an invisible element.
 *
 * Also checks that the two dark blocks agree (media-query dark and explicit
 * dark must produce the same palette), and that the Tailwind bridge uses
 * `@theme inline` — without `inline`, Tailwind freezes token values at build
 * time and live theme switching repaints nothing.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const cssPath = join(here, '..', 'src', 'design', 'tokens.css');
const css = readFileSync(cssPath, 'utf8');

/** Extract the body of the first block whose selector line matches `re`. */
function block(re) {
  const m = css.match(re);
  if (!m) return null;
  const start = css.indexOf('{', m.index);
  let depth = 0;
  for (let i = start; i < css.length; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}') {
      depth--;
      if (depth === 0) return css.slice(start + 1, i);
    }
  }
  return null;
}

const declared = (body) =>
  new Set([...(body ?? '').matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));

const errors = [];

const rootBody = block(/^:root\s*\{/m);
if (!rootBody) errors.push('no bare `:root` block found in tokens.css');
const root = declared(rootBody);

const themed = [
  ['dark (system preference)', /:root:not\(\[data-theme='light'\]\)\s*\{/],
  ["dark (data-theme='dark')", /:root\[data-theme='dark'\]\s*\{/],
  ["high contrast", /:root\[data-contrast='high'\]\s*\{/],
  ["high contrast + dark", /:root\[data-contrast='high'\]\[data-theme='dark'\]\s*\{/],
];

for (const [name, re] of themed) {
  const body = block(re);
  if (!body) {
    errors.push(`missing required block: ${name}`);
    continue;
  }
  for (const token of declared(body)) {
    if (!root.has(token)) {
      errors.push(
        `${token} is declared in "${name}" but not on bare :root — it will be ` +
          `empty for every user on the default setting`
      );
    }
  }
}

// The two dark blocks must agree, or an explicit choice looks different from
// the same choice made by the operating system.
const darkMedia = declared(block(/:root:not\(\[data-theme='light'\]\)\s*\{/));
const darkExplicit = declared(block(/:root\[data-theme='dark'\]\s*\{/));
for (const t of darkMedia) {
  if (!darkExplicit.has(t)) errors.push(`${t} set for system dark but not for data-theme="dark"`);
}
for (const t of darkExplicit) {
  if (!darkMedia.has(t)) errors.push(`${t} set for data-theme="dark" but not for system dark`);
}

if (!/@theme\s+inline\s*\{/.test(css)) {
  errors.push(
    '@theme is not declared `inline` — Tailwind would freeze token values at ' +
      'build time and live theme switching would repaint nothing'
  );
}

const colourTokens = [...root].filter((t) => t.startsWith('--c-'));
if (colourTokens.length < 40) {
  errors.push(`only ${colourTokens.length} --c-* tokens on :root; expected the full palette`);
}

if (errors.length) {
  console.error('tokens.css check FAILED:\n');
  for (const e of errors) console.error('  - ' + e);
  process.exit(1);
}

console.log(
  `tokens.css OK — ${root.size} tokens on :root (${colourTokens.length} colour), ` +
    `all theme blocks redefine only existing names, both dark blocks agree, @theme is inline.`
);
