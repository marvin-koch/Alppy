import { readFileSync } from 'node:fs';
import path from 'node:path';

import { API_RESPONSES, API_ROUTES } from '@alppy/shared/api-routes';
import { describe, expect, it } from 'vitest';

/**
 * Every path `endpoints.ts` calls is a path the API serves.
 *
 * `endpoints.ts` has claimed since it was written that this file checks it.
 * It did not exist. The failure it was meant to catch had already happened:
 * `POST /scans/{id}/pages/{id}/assign` was called for two milestones against
 * an API that only ever exposed `PATCH …/pages/{id}`, and no type could see
 * it — the payload was right and only the address was wrong.
 *
 * This checks the ADDRESS, which is the half the generated types cannot. It
 * does not check the method for that purpose: the option object is often built
 * a line or three away from the call, and a regex that pretended to read it
 * would be a check that lies about its own reach. A wrong method returns 405
 * on the first click; a wrong path can sit behind a feature flag for a
 * milestone.
 *
 * The second suite below checks the SHAPE, which the generated types also
 * cannot: `apiRequest<T>` is an assertion, so the client states what it
 * expects and TypeScript believes it. A route whose response model changes
 * compiles at every call site while the data underneath is something else —
 * which is how `getSourceStatus` came to declare `SourceOut` for a route that
 * has always returned `JobOut`.
 */

const ENDPOINTS = path.resolve(__dirname, '../endpoints.ts');

/** `/classes/${id}/students` -> `/classes/{}/students` */
function templateToPattern(raw: string): string {
  return raw.replace(/\$\{[^}]*\}/g, '{}');
}

/** `/api/v1/classes/{class_id}/students` -> `/classes/{}/students` */
function routeToPattern(route: string): string {
  const withoutMethod = route.slice(route.indexOf(' ') + 1);
  return withoutMethod.replace(/^\/api\/v1/, '').replace(/\{[^}]*\}/g, '{}');
}

function calledPaths(): string[] {
  const source = readFileSync(ENDPOINTS, 'utf8');
  // `apiRequest<T>('/path')` and `apiRequestText(`/path/${id}`)`, quoted with
  // either ' or `. The path is always the first argument and always a literal
  // — a computed one would be exactly the guess this test exists to stop.
  const call = /apiRequest(?:Text)?(?:<[^>]*>)?\(\s*(['`])([^'`]+)\1/g;
  const found = new Set<string>();
  for (const match of source.matchAll(call)) {
    const raw = match[2];
    if (raw !== undefined && raw.startsWith('/')) {
      found.add(templateToPattern(raw));
    }
  }
  return [...found].sort();
}

/** Every `apiRequest` call, with the whole argument list, by paren matching.
 *  A regex cannot find the end of a call that contains nested calls. */
function* callSites(source: string): Generator<{ declared: string; body: string }> {
  const opener = /apiRequest(Text)?(<[^>]*>)?\(/g;
  let match: RegExpExecArray | null;
  while ((match = opener.exec(source)) !== null) {
    let depth = 0;
    let index = match.index + match[0].length - 1;
    const start = index + 1;
    for (; index < source.length; index += 1) {
      if (source[index] === '(') depth += 1;
      else if (source[index] === ')') {
        depth -= 1;
        if (depth === 0) break;
      }
    }
    // `apiRequestText` has no type parameter and always answers with a string.
    const declared = match[1] ? 'string' : (match[2] ?? '<unknown>').slice(1, -1).trim();
    yield { declared, body: source.slice(start, index) };
  }
}

function routeKeyOf(body: string): { method: string; pattern: string } | null {
  const literal = /^\s*(['`])([^'`]+)\1/.exec(body);
  if (literal?.[2] === undefined || !literal[2].startsWith('/')) return null;
  const method = /method:\s*'(\w+)'/.exec(body)?.[1]?.toUpperCase() ?? 'GET';
  return { method, pattern: templateToPattern(literal[2]) };
}

describe('the client expects the shape the API returns', () => {
  const served = new Map<string, string>();
  for (const [route, type] of Object.entries(API_RESPONSES)) {
    const method = route.slice(0, route.indexOf(' '));
    served.set(`${method} ${routeToPattern(route)}`, type);
  }

  const sites: { key: string; declared: string; expected: string }[] = [];
  for (const { declared, body } of callSites(readFileSync(ENDPOINTS, 'utf8'))) {
    const route = routeKeyOf(body);
    if (route === null) continue;
    const expected = served.get(`${route.method} ${route.pattern}`);
    // Paths that do not resolve are the first suite's business, not this one.
    if (expected === undefined) continue;
    sites.push({ key: `${route.method} ${route.pattern}`, declared, expected });
  }

  it('resolves essentially every call to a route', () => {
    expect(sites.length).toBeGreaterThan(80);
  });

  it.each(sites)('$key returns $expected', ({ declared, expected }) => {
    expect(declared.replace(/\s+/g, '')).toBe(expected.replace(/\s+/g, ''));
  });
});

describe('the client calls paths the API serves', () => {
  const served = new Set(API_ROUTES.map(routeToPattern));
  const called = calledPaths();

  it('finds the calls (the regex has not silently stopped matching)', () => {
    // A regex that matches nothing would make every assertion below vacuous.
    expect(called.length).toBeGreaterThan(60);
  });

  it.each(called)('%s is served', (pattern) => {
    expect(served.has(pattern)).toBe(true);
  });
});
