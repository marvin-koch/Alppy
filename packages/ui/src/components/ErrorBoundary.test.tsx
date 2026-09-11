/**
 * One subtree fails, and its siblings do not.
 *
 * The app had a single boundary, at the locale segment, so a detection with a
 * shape nobody anticipated threw away all thirty pages of a class's corrected
 * work (G22). The property worth pinning is exactly that containment: a sibling
 * that renders fine must still be on screen after its neighbour has thrown.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ErrorBoundary } from './ErrorBoundary';

function Boom({ throws }: { throws: boolean }): JSX.Element {
  if (throws) throw new Error('boom');
  return <p>intact</p>;
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    // React logs a caught render error; the point here is that it was CAUGHT.
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('renders its children when nothing throws', () => {
    render(
      <ErrorBoundary fallback={() => <p>fallback</p>}>
        <Boom throws={false} />
      </ErrorBoundary>,
    );

    expect(screen.getByText('intact')).toBeInTheDocument();
    expect(screen.queryByText('fallback')).not.toBeInTheDocument();
  });

  it('shows the fallback instead of propagating the throw', () => {
    render(
      <ErrorBoundary fallback={() => <p>fallback</p>}>
        <Boom throws />
      </ErrorBoundary>,
    );

    expect(screen.getByText('fallback')).toBeInTheDocument();
  });

  /** The whole reason it exists: one bad page is one bad page. */
  it('contains the failure, leaving its siblings rendered', () => {
    render(
      <div>
        <ErrorBoundary fallback={() => <p>page 2 unavailable</p>}>
          <Boom throws />
        </ErrorBoundary>
        <ErrorBoundary fallback={() => <p>page 3 unavailable</p>}>
          <Boom throws={false} />
        </ErrorBoundary>
      </div>,
    );

    expect(screen.getByText('page 2 unavailable')).toBeInTheDocument();
    expect(screen.getByText('intact')).toBeInTheDocument();
    expect(screen.queryByText('page 3 unavailable')).not.toBeInTheDocument();
  });

  /**
   * `reset` the way a caller actually uses it: the fallback offers an action, the
   * caller deals with the cause, and then asks the boundary to try the subtree
   * again. Nothing mutates during render — React 19 re-renders a failed
   * concurrent root synchronously, so a component that throws on its first render
   * and succeeds on its second is not a thing a test can rely on.
   */
  it('hands the fallback a reset that lets the subtree try again', () => {
    function Case(): JSX.Element {
      const [broken, setBroken] = useState(true);
      return (
        <ErrorBoundary
          fallback={(reset) => (
            <button
              type="button"
              onClick={() => {
                setBroken(false);
                reset();
              }}
            >
              again
            </button>
          )}
        >
          <Boom throws={broken} />
        </ErrorBoundary>
      );
    }

    render(<Case />);
    expect(screen.getByRole('button', { name: 'again' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'again' }));

    expect(screen.getByText('intact')).toBeInTheDocument();
  });

  /** The library ships no copy: a boundary that hard-coded "Something went
   *  wrong" would be the one English sentence in a French product, at the worst
   *  possible moment. */
  it('renders no text of its own', () => {
    const { container } = render(
      <ErrorBoundary fallback={() => <p>fallback</p>}>
        <Boom throws />
      </ErrorBoundary>,
    );

    expect(container.textContent).toBe('fallback');
  });
});
