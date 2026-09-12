#!/usr/bin/env node
// Fails CI when a translation key exists in one locale's messages file but is
// missing from another, in either direction. next-intl (apps/web) reads
// apps/web/messages/{fr,de,en}.json — fr is the default (architecture.md),
// but "default" only affects fallback UI copy, never which keys must exist:
// every key must exist in all three, or a teacher using de/en silently sees
// French (or nothing) where a translation was forgotten.
//
// Usage: node scripts/check-i18n.mjs
// Exit code: 0 if the catalogues are in sync, 1 otherwise — including when
//            they are ABSENT. A gate that reports success when its input is
//            missing has the wrong default: the one arrangement it cannot
//            distinguish from "perfectly in sync" is "there is nothing here",
//            and a build that deleted or moved the catalogues is exactly when
//            you want to hear about it (T26).
//
// ALPPY_I18N_DIR overrides where the catalogues are read from. It exists so the
// absent case is testable without deleting the real ones.

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const LOCALES = ['fr', 'de', 'en'];
const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '..');
const MESSAGES_DIR = process.env.ALPPY_I18N_DIR ?? join(REPO_ROOT, 'apps', 'web', 'messages');

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

/**
 * The error codes, read out of the generated contract.
 *
 * Parsed rather than imported: this is a plain `.mjs` run by `node` with no
 * build step, and the generated file is TypeScript. The shape it parses is the
 * one the generator writes and a test would notice if it changed — an empty
 * result fails loudly below rather than passing vacuously.
 */
function generatedList(name) {
  const path = new URL('../packages/shared/src/api-constants.generated.ts', import.meta.url);
  const source = readFileSync(path, 'utf8');
  // Only the named block: the same file also lists the cantons, which are
  // uppercase and therefore cannot match, but slicing says so out loud.
  const start = source.indexOf(`${name} = [`);
  const block = source.slice(start, source.indexOf('] as const;', start));
  const values = [...block.matchAll(/^ {2}'([a-z_]+)',$/gm)].map((m) => m[1]);
  if (values.length === 0) {
    console.error(`✗ could not read any ${name} from api-constants.generated.ts`);
    process.exit(1);
  }
  return values;
}

function main() {
  const locales = LOCALES.map(loadLocale);
  const present = locales.filter((l) => l.exists);

  if (present.length === 0) {
    // Not "nothing to check yet". The web app cannot render a single screen
    // without these files, so their absence is never the innocent state — it
    // is a moved directory, a bad merge, or a build that ran somewhere
    // unexpected. Reporting success here is the one answer that guarantees
    // nobody finds out until a teacher sees an untranslated page.
    console.error(
      `✗ none of ${LOCALES.map((l) => `${l}.json`).join(', ')} exist in ${MESSAGES_DIR}. ` +
        `The catalogues are required, not optional: next-intl reads them for every ` +
        `screen. If they have moved, point ALPPY_I18N_DIR at them.`,
    );
    return 1;
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

  // Every error code the API can emit has a sentence (F14).
  //
  // Cross-locale sync alone could not catch this: the catalogue covered
  // thirteen codes *consistently in all three languages*, and every other code
  // fell through to `errors.code.fallback` — so a rate limit, a permission
  // refusal and a dead API all read "L'envoi a échoué. Réessayez." The code
  // list is generated from the API itself, so a new `code="..."` fails here
  // rather than silently joining the fallback.
  for (const code of generatedList('API_ERROR_CODES')) {
    const key = `errors.code.${code}`;
    const missingIn = present.filter((l) => !l.keys.has(key)).map((l) => l.locale);
    if (missingIn.length > 0) {
      hasDrift = true;
      console.error(`✗ API error code "${code}" has no sentence in [${missingIn.join(', ')}]`);
    }
  }

  // And every kind of event the agenda can be handed has a label, for exactly
  // the same reason and with exactly the same blind spot.
  //
  // The timeline renders `timeline.kind.<value>`. Three members of `EventKind`
  // had no label in ANY locale — so cross-locale sync saw nothing wrong — and
  // `scan_reopened` is produced by the Rouvrir button on the review screen:
  // reopening a pile wrote the raw key `timeline.kind.scan_reopened` into the
  // teacher's agenda, with a MISSING_MESSAGE in the console and a green gate.
  for (const kind of generatedList('EVENT_KINDS')) {
    const key = `timeline.kind.${kind}`;
    const missingIn = present.filter((l) => !l.keys.has(key)).map((l) => l.locale);
    if (missingIn.length > 0) {
      hasDrift = true;
      console.error(`✗ event kind "${kind}" has no label in [${missingIn.join(', ')}]`);
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
