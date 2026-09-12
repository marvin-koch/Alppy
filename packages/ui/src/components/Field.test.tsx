import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Field } from './Field';
import { Input } from './Input';

describe('Field', () => {
  it('wires a single control to its label', () => {
    render(
      <Field label="Énoncé">
        <Input aria-label="Énoncé" />
      </Field>,
    );
    const input = screen.getByLabelText('Énoncé');
    expect(input.id).toBeTruthy();
    // The label points at exactly that control.
    expect(document.querySelector('label')?.getAttribute('for')).toBe(input.id);
  });

  it('gives a group of controls no shared id', () => {
    // A fieldset labels a GROUP through its legend, which has no `htmlFor`, so
    // there is no single control to point at. Handing the Field's one id to
    // every child rendered four MCQ answer inputs carrying an identical
    // `id="…-control"` — invalid HTML, and enough to make a label click or
    // `getElementById` resolve to whichever happened to come first.
    render(
      <Field as="fieldset" label="Réponses">
        <Input aria-label="Réponse A" />
        <Input aria-label="Réponse B" />
        <Input aria-label="Réponse C" />
      </Field>,
    );

    const ids = ['Réponse A', 'Réponse B', 'Réponse C']
      .map((name) => screen.getByLabelText(name).id)
      .filter(Boolean);

    expect(new Set(ids).size).toBe(ids.length);
  });

  it('still describes every control in a group through the legend’s help', () => {
    render(
      <Field as="fieldset" label="Réponses" help="Deux au minimum">
        <Input aria-label="Réponse A" />
        <Input aria-label="Réponse B" />
      </Field>,
    );
    for (const name of ['Réponse A', 'Réponse B']) {
      expect(screen.getByLabelText(name)).toHaveAttribute('aria-describedby');
    }
  });
});
