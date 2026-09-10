import { readFileSync } from 'node:fs';
import path from 'node:path';

import { API_ROUTES } from '@alppy/shared/api-routes';
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
 * does not check the method: the option object is often built a line or three
 * away from the call, and a regex that pretended to read it would be a check
 * that lies about its own reach. A wrong method returns 405 on the first
 * click; a wrong path can sit behind a feature flag for a milestone.
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
