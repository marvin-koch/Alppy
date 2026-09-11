/**
 * Every invalidation names a key something is actually stored under.
 *
 * `useUpdateChapter` and `useDeleteChapter` invalidated `['classTree']` for two
 * milestones. No query in the app is registered under that key — the real
 * prefix is `['classes', id, 'tree']` — so the call did nothing at all, and
 * renaming a Theme left the programme beside it showing the old name until
 * something else happened to refetch. It looked exactly like a working
 * invalidation, which is the whole problem: TanStack Query does not complain
 * about a key that matches nothing, because "nothing to invalidate" is a
 * perfectly ordinary state.
 *
 * Banning literal arrays outright would be wrong — `['classes']` and
 * `['sheets']` are deliberate PREFIX invalidations, and a prefix is not a key
 * any builder returns. What can be checked is the first segment: if it is not a
 * namespace `queryKeys` ever produces, the invalidation cannot match anything,
 * ever, under any argument.
 */

import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { queryKeys } from './queries';

const SOURCE = path.resolve(__dirname, './queries.ts');

/** Every namespace a key can begin with, asked of the builders themselves. */
function namespaces(): Set<string> {
  const dummy = '00000000-0000-4000-8000-000000000001';
  const out = new Set<string>();
  for (const value of Object.values(queryKeys)) {
    const key = typeof value === 'function' ? (value as (...a: unknown[]) => readonly unknown[])(dummy, {}) : value;
    if (Array.isArray(key) && typeof key[0] === 'string') out.add(key[0]);
  }
  return out;
}

/** The first segment of every literal array passed as a `queryKey`. */
function invalidatedNamespaces(): string[] {
  // Comments stripped first: this module documents the bug it fixed by quoting
  // the broken call, and a scanner that reads prose would report the very
  // example written to explain itself.
  const source = readFileSync(SOURCE, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
  const call = /invalidateQueries\(\{\s*queryKey:\s*\[\s*'([^']+)'/g;
  return [...source.matchAll(call)].map((m) => m[1] as string);
}

describe('cache keys', () => {
  it('finds the builders and the invalidations (neither regex has gone quiet)', () => {
    expect(namespaces().size).toBeGreaterThan(8);
    expect(invalidatedNamespaces().length).toBeGreaterThan(5);
  });

  it('never invalidates a namespace nothing is stored under', () => {
    const known = namespaces();
    const unknown = [...new Set(invalidatedNamespaces())].filter((ns) => !known.has(ns));
    expect(unknown, 'an invalidation that can never match any query').toEqual([]);
  });

  /** The specific shape of the bug, kept as a named case so the reason this
   *  file exists survives a refactor of the regex above. */
  it('has no key beginning with the one that matched nothing', () => {
    expect(namespaces().has('classTree')).toBe(false);
    expect(invalidatedNamespaces()).not.toContain('classTree');
  });
});
