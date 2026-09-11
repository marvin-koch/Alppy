/**
 * The error boundary renders, and its retry button retries.
 *
 * Next's wiring — "a throw below this segment lands here" — is the framework's
 * own contract and is exercised by the e2e suite's not-found case; what a unit
 * test can pin is that the boundary Next hands the error to is a real screen
 * with the translated strings and a working `reset`, rather than a component
 * that throws again while trying to report a throw.
 */

import { NextIntlClientProvider } from 'next-intl';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import messages from '../../../messages/fr.json';
import LocaleError from './error';

function renderBoundary(reset: () => void) {
  return render(
    <NextIntlClientProvider locale="fr" messages={messages}>
      <LocaleError error={Object.assign(new Error('boom'), { digest: 'abc123' })} reset={reset} />
    </NextIntlClientProvider>,
  );
}

describe('the locale error boundary', () => {
  it('shows the translated failure rather than Next’s English default', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderBoundary(() => {});

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(messages.errors.generic.title)).toBeInTheDocument();
    expect(screen.getByText(messages.errors.generic.body)).toBeInTheDocument();
  });

  /** The thrown message is the API's or the runtime's own English and belongs
   *  in the console — `api/client.ts` says so, and it is why no screen renders
   *  `error.message`. A boundary is the easiest place to forget that. */
  it('never puts the exception’s own text on screen', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { container } = renderBoundary(() => {});

    expect(container.textContent).not.toContain('boom');
    expect(container.textContent).not.toContain('abc123');
  });

  it('retries through reset', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const reset = vi.fn();
    renderBoundary(reset);

    fireEvent.click(screen.getByRole('button', { name: messages.errors.generic.action }));
    expect(reset).toHaveBeenCalledTimes(1);
  });
});
