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
    const key =
      typeof value === 'function'
        ? (value as (...a: unknown[]) => readonly unknown[])(dummy, {})
        : value;
    if (Array.isArray(key) && typeof key[0] === 'string') out.add(key[0]);
  }
  return out;
}

/** `queries.ts` with its comments removed.
 *
 *  Stripped first because this module documents the bug it fixed by quoting the
 *  broken call, and a scanner that reads prose would report the very example
 *  written to explain itself. */
function source(): string {
  return readFileSync(SOURCE, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
}

/**
 * The first segment of every namespace an `invalidateQueries` call can reach.
 *
 * Both spellings count, and missing the second is what made the converse test
 * below report false orphans on its first run. A literal `['sheets']` is a
 * deliberate PREFIX invalidation; `queryKeys.scan(id)` and `queryKeys.homePrefix`
 * are the same intent expressed through a builder, and those are resolved by
 * asking the builder rather than by parsing what it returns.
 */
function invalidatedNamespaces(): string[] {
  const text = source();
  const literal = /invalidateQueries\(\{\s*queryKey:\s*\[\s*'([^']+)'/g;
  const viaBuilder = /invalidateQueries\(\{\s*queryKey:\s*queryKeys\.(\w+)/g;

  const out = [...text.matchAll(literal)].map((m) => m[1] as string);

  const dummy = '00000000-0000-4000-8000-000000000001';
  for (const [, name] of text.matchAll(viaBuilder)) {
    const builder = (queryKeys as Record<string, unknown>)[name as string];
    const key =
      typeof builder === 'function'
        ? (builder as (...a: unknown[]) => readonly unknown[])(dummy, {})
        : builder;
    if (Array.isArray(key) && typeof key[0] === 'string') out.push(key[0]);
  }
  return out;
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

  /**
   * The converse, and the one that would have caught G8.
   *
   * The test above asks "does every invalidation hit something?". This asks "is
   * everything hit by some invalidation?" — and the answer was no. `sheet-mastery`
   * is its own namespace, so the `['sheets']` prefix in `useConfirmScan` never
   * touched it, and confirming a pile left the sheet screen's class-band panel
   * showing pre-confirmation bands for the full 30s staleTime. `timeline` was
   * missed the same way.
   *
   * A namespace nothing ever invalidates is not automatically a bug — some data
   * genuinely only changes when the server says so — so the exceptions are listed
   * by name with a reason. The point is that adding a namespace forces a decision
   * rather than defaulting to silence.
   */
  it('leaves no namespace that nothing ever invalidates', () => {
    /** Read-only or self-invalidating, on purpose. */
    const NEVER_INVALIDATED = new Map([
      ['me', 'the session; `useLogin`/`useSwitchSchool` write it directly or clear the cache'],
      ['school-years', 'a school gains one a year; staleTime is Infinity'],
      ['subjects', 'school-level reference data, invalidated through `classes`'],
      ['chapters', 'curriculum reference data; `everyClassTree` covers the trees that read it'],
      ['competencies', 'the curriculum itself, seeded server-side'],
      ['adaptive', 'one proposal per job id, immutable once built'],
      ['jobs', 'polled to a terminal state, never invalidated'],
      ['feedback', 'derived from a sheet that is already invalidated'],
      ['colleagues', 'school-level, invalidated through `classes`'],
    ]);

    const invalidated = new Set(invalidatedNamespaces());
    const orphans = [...namespaces()].filter(
      (ns) => !invalidated.has(ns) && !NEVER_INVALIDATED.has(ns),
    );

    expect(
      orphans,
      'a namespace no mutation invalidates: either invalidate it, or add it to ' +
        'NEVER_INVALIDATED with the reason it does not need it',
    ).toEqual([]);
  });
});
