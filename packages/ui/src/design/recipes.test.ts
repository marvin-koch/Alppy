import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The design rules CI could not previously see.
 *
 * Stylelint enforces "no colour literal"; nothing enforced what the recipes
 * actually *say*. These are the two rules CLAUDE.md names as reviewer-only,
 * asserted against the stylesheet itself — no DOM, no Tailwind build, so they
 * cost nothing and cannot be defeated by a component choosing a class.
 */
const recipes = readFileSync(join(__dirname, 'recipes.css'), 'utf8');

function block(selector: string): string {
  const start = recipes.indexOf(`${selector} {`);
  if (start === -1) throw new Error(`${selector} not found in recipes.css`);
  return recipes.slice(start, recipes.indexOf('}', start));
}

describe('DC-shape-01 — a card and a panel are different objects', () => {
  const card = block('.ard-card');
  const panel = block('.ard-panel');

  it('a card is a separate object: radius lg, solid edge, shadow', () => {
    expect(card).toContain('border-radius: var(--r-lg)');
    expect(card).toContain('box-shadow:');
  });

  it('a panel is a subdivision: radius md, border, NO shadow', () => {
    expect(panel).toContain('border-radius: var(--r-md)');
    expect(panel).toContain('border:');
    // The whole rule. Shadows everywhere flattens the hierarchy into noise.
    expect(panel).not.toContain('box-shadow');
  });

  it('they do not share a radius, which is what makes them tell apart', () => {
    expect(card).not.toContain('var(--r-md)');
    expect(panel).not.toContain('var(--r-lg)');
  });
});

describe('DC-colour-06 — the mandarin accent means AI-generated content', () => {
  /**
   * The accent marks an exercise a model wrote. If it turns up on a "new"
   * badge or a call to action it stops meaning anything, and the teacher
   * loses the signal telling them which items need a second look.
   *
   * A recipe is allowed to *offer* an accent tint (`[data-tint='accent']`) —
   * that is opt-in, and `Card`'s own props deliberately exclude it. What is
   * forbidden is a recipe that takes the accent unconditionally.
   */
  it('no recipe takes the accent as its default', () => {
    const offenders: string[] = [];
    const blockPattern = /^(\.[a-z0-9-]+)\s*\{([^}]*)\}/gim;
    for (const match of recipes.matchAll(blockPattern)) {
      const selector = match[1] ?? '';
      const body = match[2] ?? '';
      if (/var\(--c-accent-/.test(body)) offenders.push(selector);
    }
    expect(offenders).toEqual([]);
  });
});
