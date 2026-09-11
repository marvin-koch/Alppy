#!/usr/bin/env node
// Fails CI when docs/plan.md §5 stops matching the routes the app actually
// registers.
//
// §5 is the screen inventory of record, and it had drifted to listing eleven
// screens of twenty-four — which is the failure any document that repeats a
// source of truth eventually has, and the same one §4 already solved by pointing
// at a generated list instead (audit 02 M11). Two frontend audits in a row asked
// whether §5 was still the record; the honest answer is "yes, and nothing was
// stopping it going stale again". This is that something.
//
// Not generated, deliberately. Each line of §5 says what a screen is FOR, which
// no generator can produce and which is the only reason to read the section at
// all. So the prose stays hand-written and this checks the set of paths it
// covers, which is the half that can drift silently.
//
// Usage: node scripts/check-screens.mjs
// Exit: 0 when the inventory matches (or the files are absent), 1 on any
//       difference, in either direction.

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '..');
const APP_DIR = join(REPO_ROOT, 'apps', 'web', 'src', 'app', '[locale]');
const PLAN = join(REPO_ROOT, 'docs', 'plan.md');

/**
 * Registered but not screens, and each for its own reason.
 *
 * The catch-all answers an unmatched path in the teacher's own language rather
 * than in Next's English default; `_gallery` is the component workbench and is
 * gated on fixture mode. §5 names both in prose and lists neither.
 */
const NOT_SCREENS = new Set(['[...rest]', '%5Fgallery']);

/** Every `page.tsx` under the locale segment, as the URL path it serves. */
function registeredRoutes(dir, prefix = '') {
  const out = new Set();
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      for (const nested of registeredRoutes(full, `${prefix}/${entry}`)) out.add(nested);
    } else if (entry === 'page.tsx') {
      out.add(prefix === '' ? '/' : prefix);
    }
  }
  return out;
}

/** The paths §5 lists, read out of its numbered entries' leading code span. */
function documentedRoutes(markdown) {
  const section = markdown.split('\n## 5. Screens')[1]?.split('\n## ')[0];
  if (section === undefined) return null;
  const entries = section.matchAll(/^\s*\d+\.\s+`([^`]+)`/gm);
  return new Set([...entries].map((m) => m[1]));
}

function main() {
  if (!existsSync(APP_DIR) || !existsSync(PLAN)) {
    console.log('screens check: skipped — nothing to check yet.');
    return 0;
  }

  const registered = new Set(
    [...registeredRoutes(APP_DIR)].filter(
      (route) => !NOT_SCREENS.has(route.replace(/^\//, '').split('/')[0]),
    ),
  );
  const documented = documentedRoutes(readFileSync(PLAN, 'utf8'));

  if (documented === null) {
    console.error('screens check: could not find "## 5. Screens" in docs/plan.md.');
    return 1;
  }

  const undocumented = [...registered].filter((r) => !documented.has(r)).sort();
  const phantom = [...documented].filter((r) => !registered.has(r)).sort();

  if (undocumented.length === 0 && phantom.length === 0) {
    console.log(`screens check: ok — ${registered.size} screens, all of them in §5.`);
    return 0;
  }

  console.error('screens check: docs/plan.md §5 no longer matches the app.\n');
  for (const route of undocumented) {
    console.error(`  registered, not in §5:  ${route}`);
  }
  for (const route of phantom) {
    console.error(`  in §5, not registered:  ${route}`);
  }
  console.error(
    '\nAdd the screen to §5 with a line saying what it is for, or remove the entry.',
  );
  console.error(`(${relative(REPO_ROOT, PLAN)} §5, and ${relative(REPO_ROOT, APP_DIR)})`);
  return 1;
}

process.exit(main());
