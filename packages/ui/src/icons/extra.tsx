/**
 * Pictograms the product needs that the shipped brand library does not include.
 *
 * The 48 in `set.tsx` are generated from
 * `docs/design/alppy-brand-assets/brand/icons/` and are the authority. This file
 * is only for genuine gaps, and every glyph here is drawn to the same spec:
 * 24px grid, 20x20 safe area, stroke 2.2, round caps and joins, currentColor.
 *
 * Keep this list short. If one of these becomes load-bearing, it belongs in the
 * brand library proper, not here.
 */
import { createIcon } from './Icon';

/**
 * The drawer trigger on phones. The brand set has no hamburger because the
 * manual assumes the desktop rail; the mobile layout needs one.
 */
export const IconMenu = createIcon(
  'IconMenu',
  <>
    <path d="M4 7h16" />
    <path d="M4 12h16" />
    <path d="M4 17h16" />
  </>,
);
