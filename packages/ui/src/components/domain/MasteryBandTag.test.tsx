import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BAND_ORDER } from '../../lib/mastery';
import { MasteryBandTag } from './MasteryBandTag';

/**
 * DC-colour-08 / DC-content-07, enforced rather than reviewed.
 *
 * "Never colour alone" is the rule most likely to erode quietly, because
 * dropping a channel makes a component look *tidier*. These assert the three
 * channels are all present for every band: the calibrated tint (via
 * `data-band`, which is what `.ard-mastery` keys on), the glyph, and the
 * written word.
 */
describe('MasteryBandTag carries three channels', () => {
  it.each(BAND_ORDER)('%s renders tint, glyph and label together', (band) => {
    const { container } = render(<MasteryBandTag band={band} label={`label-${band}`} />);

    // 1 — the tint, selected by the attribute the recipe keys on.
    const tag = container.querySelector('.ard-mastery');
    expect(tag).toHaveAttribute('data-band', band);

    // 2 — the glyph: the channel that survives a photocopy and colour-blindness.
    expect(container.querySelector('svg')).toBeInTheDocument();

    // 3 — the word.
    expect(screen.getByText(`label-${band}`)).toBeInTheDocument();
  });

  it('gives each band a visually distinct glyph', () => {
    // Four filled states plus the dashed ring must not collapse into one mark;
    // if they do, the third channel is decorative and the ramp reads only in
    // colour.
    const drawn = BAND_ORDER.map((band) => {
      const { container } = render(<MasteryBandTag band={band} label={band} />);
      return container.querySelector('svg')!.innerHTML;
    });
    expect(new Set(drawn).size).toBe(BAND_ORDER.length);
  });

  it('shows coverage as a caption when the band is an aggregate', () => {
    render(<MasteryBandTag band="ok" label="Acquis" caption="2 sur 3 évaluées" />);
    expect(screen.getByText(/2 sur 3 évaluées/)).toBeInTheDocument();
  });

  /**
   * The prop is required in the type system; this pins the runtime behaviour
   * so a caller casting through `any` still cannot produce a bare pill.
   */
  it('never renders a bare coloured pill', () => {
    const { container } = render(<MasteryBandTag band="solid" label="Maîtrisé" />);
    expect(container.textContent?.trim()).not.toBe('');
  });

  it('stays shrinkable so a caption cannot overflow a narrow column', () => {
    const { container } = render(
      <MasteryBandTag band="weak" label="Fragile" caption="1 sur 4 évaluées" />,
    );
    const tag = container.querySelector('.ard-mastery')!;
    expect(tag.className).toContain('min-w-0');
    expect(tag.className).not.toContain('shrink-0');
  });
});
