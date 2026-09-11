/**
 * A barème a teacher types arrives as the number they typed.
 *
 * The custom field used to parse with `Number(event.currentTarget.value)` and
 * write the result straight back into its own `value`. Typing `1.5` produced
 * **5**: the HTML value-sanitisation algorithm says `1.` is not a valid
 * floating-point number and replaces it with the empty string, `Number('')` is
 * `0`, React writes that `0` back over the field, and the `5` lands in a box
 * that had been silently reset one keystroke earlier. A comma failed one step
 * sooner — a number input discards it before any handler runs.
 *
 * So these type character by character. `fireEvent.change` with a final value of
 * `'1.5'` passes against the broken version, because it never produces the
 * intermediate state that breaks it — which is exactly why this bug survived a
 * suite that had a builder test.
 */

import { NextIntlClientProvider } from 'next-intl';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import messages from '../../../messages/fr.json';
import { PointsSelect } from './SheetComposer';
import { POINTS_PRESETS, PENALTY_PRESETS } from './useDraftSheet';

/** The control, already switched to its custom field. `2.5` is not a preset, so
 *  `showCustom` is true from the first render and the field is on screen. */
function renderCustom(
  onChange: (value: number | undefined) => void,
  options: { value?: number; presets?: readonly number[]; emptyMeans?: number } = {},
) {
  return render(
    <NextIntlClientProvider locale="fr" messages={messages}>
      <PointsSelect
        value={options.value ?? 2.5}
        presets={options.presets ?? POINTS_PRESETS}
        emptyMeans={options.emptyMeans}
        label={(v) => String(v)}
        onChange={onChange}
      />
    </NextIntlClientProvider>,
  );
}

/** The custom field is the textbox; the presets are a `select`. */
function field(): HTMLInputElement {
  return screen.getByRole('textbox') as HTMLInputElement;
}

function lastCall(onChange: { mock: { calls: unknown[][] } }): unknown {
  const { calls } = onChange.mock;
  return calls[calls.length - 1]?.[0];
}

describe('the custom barème field', () => {
  it('reads 1.5 as 1.5, typed one character at a time', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderCustom(onChange);

    await user.clear(field());
    await user.type(field(), '1.5');

    expect(lastCall(onChange)).toBe(1.5);
    // And the field shows what was typed, not a number it was rewritten into.
    expect(field().value).toBe('1.5');
  });

  it('reads a typed comma as a decimal point', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderCustom(onChange);

    await user.clear(field());
    await user.type(field(), '1,5');

    expect(lastCall(onChange)).toBe(1.5);
    // The comma stays visible: it is what the teacher typed, and rewriting it
    // under the cursor is its own small betrayal. Display formatting elsewhere
    // stays fr-CH's period, which is correct and is not what this touches.
    expect(field().value).toBe('1,5');
  });

  it('survives the intermediate states on the way to 0.25', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderCustom(onChange);

    await user.clear(field());
    await user.type(field(), '0.25');

    expect(lastCall(onChange)).toBe(0.25);
  });

  /** Clearing the POINTS box means the default, and clearing the PENALTY box
   *  means none. One shared fallback cannot say both, and the one that existed
   *  said "default points" — so emptying a penalty field would have set a
   *  penalty of a full point. */
  it('reads an emptied field as what that field says empty means', async () => {
    const user = userEvent.setup();

    const onPoints = vi.fn();
    const { unmount } = renderCustom(onPoints);
    await user.clear(field());
    expect(lastCall(onPoints)).toBe(1);
    unmount();

    const onPenalty = vi.fn();
    renderCustom(onPenalty, { value: 0.75, presets: PENALTY_PRESETS, emptyMeans: 0 });
    await user.clear(field());
    expect(lastCall(onPenalty)).toBe(0);
  });

  it('clamps what a teacher types rather than sending it on', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderCustom(onChange);

    await user.clear(field());
    await user.type(field(), '999');

    expect(lastCall(onChange)).toBeLessThanOrEqual(20);
  });
});
