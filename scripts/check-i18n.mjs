#!/usr/bin/env node
// Fails CI when a translation key exists in one locale's messages file but is
// missing from another, in either direction. next-intl (apps/web) reads
// apps/web/messages/{fr,de,en}.json — fr is the default (architecture.md),
// but "default" only affects fallback UI copy, never which keys must exist:
// every key must exist in all three, or a teacher using de/en silently sees
// French (or nothing) where a translation was forgotten.
//
// Usage: node scripts/check-i18n.mjs
// Exit code: 0 if the files are absent (nothing to check yet) or in sync,
//            1 if any key is present in one locale and missing in another.

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const LOCALES = ['fr', 'de', 'en'];
const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '..');
const MESSAGES_DIR = join(REPO_ROOT, 'apps', 'web', 'messages');

/** Recursively flattens a nested messages object into dotted keys, e.g.
 * {"nav": {"home": "Accueil"}} -> Set(["nav.home"]). */
function flattenKeys(obj, prefix = '') {
  const keys = new Set();
  for (const [key, value] of Object.entries(obj ?? {})) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      for (const nested of flattenKeys(value, path)) keys.add(nested);
    } else {
      keys.add(path);
    }
  }
  return keys;
}

function loadLocale(locale) {
  const path = join(MESSAGES_DIR, `${locale}.json`);
  if (!existsSync(path)) return { locale, path, exists: false, keys: new Set() };
  let json;
  try {
    json = JSON.parse(readFileSync(path, 'utf8'));
  } catch (err) {
    console.error(`✗ ${path} is not valid JSON: ${err.message}`);
    process.exit(1);
  }
  return { locale, path, exists: true, keys: flattenKeys(json) };
}

function main() {
  const locales = LOCALES.map(loadLocale);
  const present = locales.filter((l) => l.exists);

  if (present.length === 0) {
    console.log(
      `i18n check: skipped — none of ${LOCALES.map((l) => `messages/${l}.json`).join(', ')} exist yet in ${MESSAGES_DIR}.`,
    );
    return 0;
  }

  const missingFiles = locales.filter((l) => !l.exists);
  let hasDrift = false;

  for (const missing of missingFiles) {
    hasDrift = true;
    console.error(
      `✗ ${missing.locale}: apps/web/messages/${missing.locale}.json does not exist, but ` +
        `${present.map((l) => l.locale).join(', ')} do. All ${LOCALES.length} locales must ship together.`,
    );
  }

  // Union of every key seen anywhere, so we can report drift symmetrically
  // regardless of which locale is "missing from".
  const allKeys = new Set();
  for (const l of present) for (const k of l.keys) allKeys.add(k);

  for (const key of [...allKeys].sort()) {
    const missingIn = present.filter((l) => !l.keys.has(key)).map((l) => l.locale);
    if (missingIn.length > 0) {
      hasDrift = true;
      const presentIn = present.filter((l) => l.keys.has(key)).map((l) => l.locale);
      console.error(
        `✗ "${key}": present in [${presentIn.join(', ')}], missing from [${missingIn.join(', ')}]`,
      );
    }
  }

  if (hasDrift) {
    console.error(
      `\ni18n check failed: translations are out of sync across ${LOCALES.join('/')}.`,
    );
    return 1;
  }

  console.log(
    `i18n check: ok — ${allKeys.size} keys in sync across ${present.map((l) => l.locale).join(', ')}.`,
  );
  return 0;
}

process.exit(main());
