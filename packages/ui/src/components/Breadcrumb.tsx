import { Fragment, type HTMLAttributes, type ReactNode } from 'react';

import { cx } from '../lib/cx';
import { IconChevronRight } from '../icons/set';

export interface BreadcrumbItem {
  /** The written label. Already localised — this package holds no strings. */
  label: string;
  /**
   * Where the crumb goes. A crumb WITHOUT an href is not a link: the last one
   * is where you already are, and an ancestor the app cannot address yet is
   * honestly plain text rather than a link that goes nowhere.
   */
  href?: string;
  /** Stable key when two crumbs share a label ("MSN 33" under two branches). */
  key?: string;
}

export interface BreadcrumbProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  items: BreadcrumbItem[];
  /** Accessible name for the landmark, e.g. "Vous êtes ici". Required. */
  label: string;
  /**
   * How to render a crumb that has an href. The app passes its router-aware
   * Link; the default is a plain anchor, which navigates correctly but without
   * client-side routing. `packages/ui` cannot import a router.
   */
  renderLink?: (item: BreadcrumbItem, children: ReactNode) => ReactNode;
  className?: string;
}

/**
 * Where you are in `Class → Branch → Competence → Theme → Sheet`, in words.
 *
 * Extracted from the class page, which hand-rolled it, and where the crumbs
 * were `<span>`s: the hierarchy is carried by `?competency=&chapter=` rather
 * than by path segments, so without a breadcrumb the only thing naming your
 * position is a pair of selects — and without LINKS there is no way back up
 * except the browser's own button.
 *
 * On a phone the leading crumbs collapse to an ellipsis and the last two
 * survive. Truncating from the front is deliberate: the tail is where you are
 * and the crumb you are most likely to want back is its parent. The collapse
 * is CSS-only, so it costs no hydration and prints correctly.
 */
export function Breadcrumb({
  items,
  label,
  renderLink,
  className,
  ...rest
}: BreadcrumbProps) {
  if (items.length === 0) return null;

  const lastIndex = items.length - 1;

  return (
    <nav aria-label={label} className={className} {...rest}>
      <ol className="flex flex-wrap items-center gap-1.5 text-body-s font-semibold text-ink-500">
        {/* The ellipsis stands in for everything hidden at phone width. It is
            aria-hidden because the links it replaces are still in the list —
            hidden visually, never removed from the accessibility tree. */}
        {items.length > 2 ? (
          <li aria-hidden className="sm:hidden">
            <span className="text-ink-300">…</span>
          </li>
        ) : null}
        {items.map((item, index) => {
          const isLast = index === lastIndex;
          // Everything but the last two folds away on a phone.
          const collapses = items.length > 2 && index < lastIndex - 1;
          const body = (
            <span className={isLast ? 'text-ink-900' : undefined}>{item.label}</span>
          );
          return (
            <Fragment key={item.key ?? `${item.label}-${index}`}>
              {index > 0 ? (
                <li
                  aria-hidden
                  className={cx('flex items-center', collapses && 'hidden sm:flex')}
                >
                  <IconChevronRight size={14} className="text-ink-300" />
                </li>
              ) : null}
              <li
                className={cx('min-w-0', collapses && 'hidden sm:block')}
                {...(isLast ? { 'aria-current': 'page' as const } : {})}
              >
                {item.href && !isLast
                  ? (renderLink?.(item, body) ?? (
                      <a href={item.href} className="hover:text-ink-900">
                        {body}
                      </a>
                    ))
                  : body}
              </li>
            </Fragment>
          );
        })}
      </ol>
    </nav>
  );
}
