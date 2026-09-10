import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';

import { THEME_SCRIPT, THEME_SCRIPT_CSP_HASH } from './theme-script';

describe('theme script CSP hash', () => {
  /**
   * The whole point of the committed constant. Edit the script and forget the
   * hash and the browser refuses to run it: no flash-of-wrong-palette guard,
   * and a console error nobody reads. This is the test that makes that
   * impossible to ship.
   */
  it('matches the script it is supposed to allow', () => {
    const digest = createHash('sha256').update(THEME_SCRIPT, 'utf8').digest('base64');
    expect(THEME_SCRIPT_CSP_HASH).toBe(`'sha256-${digest}'`);
  });

  it('is quoted the way a script-src source expression has to be', () => {
    expect(THEME_SCRIPT_CSP_HASH).toMatch(/^'sha256-[A-Za-z0-9+/]+={0,2}'$/);
  });
});
