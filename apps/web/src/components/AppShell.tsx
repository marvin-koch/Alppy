'use client';

import {
  AlppyLogo,
  IconAi,
  IconBook,
  IconButton,
  IconClock,
  IconHome,
  IconMatrix,
  IconMenu,
  IconScan,
  IconSettings,
  IconSheet,
  IconTrend,
  Sheet,
} from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useRef, useState, type ReactNode } from 'react';

// next-intl's usePathname already has the locale prefix stripped, so route
// matching below never has to know which locale it is in.
import { Link, usePathname } from '@/i18n/navigation';
import { ScopeSwitcher } from '@/components/ScopeSwitcher';
import { useSelectedYear } from '@/lib/school-year';
import { useConnection } from '@/lib/connection';
import { applyDisplay, readDisplay } from '@/lib/display';
import { useUpdatePreferences } from '@/lib/api/queries';
import { type AppLocale } from '@/i18n/routing';

interface Destination {
  href: string;
  labelKey:
    | 'home'
    | 'classes'
    | 'sheets'
    | 'scans'
    | 'results'
    | 'adaptive'
    | 'sources'
    | 'settings'
    | 'timeline';
  icon: ReactNode;
  primary: boolean;
}

const DESTINATIONS: Destination[] = [
  { href: '/', labelKey: 'home', icon: <IconHome />, primary: true },
  { href: '/classes', labelKey: 'classes', icon: <IconMatrix />, primary: true },
  { href: '/sheets', labelKey: 'sheets', icon: <IconSheet />, primary: true },
  { href: '/scans/new', labelKey: 'scans', icon: <IconScan />, primary: true },
  // Build, mark, then see how it went: results sit at the end of the daily
  // loop rather than in the settings tail.
  { href: '/results', labelKey: 'results', icon: <IconTrend />, primary: true },
  // The agenda is where a teacher goes to find what they did last week, so it
  // sits with the daily destinations rather than in the settings tail.
  { href: '/timeline', labelKey: 'timeline', icon: <IconClock />, primary: false },
  { href: '/sources', labelKey: 'sources', icon: <IconBook />, primary: false },
  { href: '/adaptive', labelKey: 'adaptive', icon: <IconAi />, primary: false },
  { href: '/settings', labelKey: 'settings', icon: <IconSettings />, primary: false },
];

function isActive(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/';
  return pathname.startsWith(href);
}

/**
 * Below `md` the rail collapses into a drawer plus a bottom tab bar; at `md`+
 * it is a persistent left rail. The teacher uses this on a laptop at a desk and
 * on a phone in the classroom, and photographing copies is a phone workflow —
 * so mobile is a first-class layout, not a squeezed desktop.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const t = useTranslations('nav');
  const tconn = useTranslations('connection');
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const connection = useConnection();
  const tdiscreet = useTranslations('discreet');
  const tyear = useTranslations('schoolYear');
  const { selectedYear, currentYear, isPastYear, setSchoolYear } = useSelectedYear();
  const locale = useLocale() as AppLocale;
  const updatePrefs = useUpdatePreferences();
  /** What the shortcut just did, for the live region below. */
  const [shortcutSaid, setShortcutSaid] = useState<string | null>(null);
  const offline = !connection.online || !connection.reachable;

  // Focus follows the route (F20). A client-side navigation replaces the page
  // under a screen reader without telling it anything: the announcement never
  // happens, and the keyboard caret is left on the link in a rail that is now
  // describing somewhere else. `#main` already carried `tabIndex={-1}` for
  // exactly this and nothing ever focused it.
  //
  // Guarded on the first render: focusing the main region on load would move
  // the caret past the skip link, which is the one control that exists to be
  // reached first.
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    document.getElementById('main')?.focus({ preventScroll: true });
  }, [pathname]);

  // Projector mode, from anywhere, without a trip to the settings screen
  // (Phase 5). The realistic trigger is realising you need it while the
  // projector is already on and the class is already looking — which is the
  // one moment a teacher cannot go hunting through Réglages.
  //
  // Shift+D, and only when the focus is not in a field: a bare letter would
  // fire while someone types a sheet title, and a modifier combination the
  // browser already owns (Ctrl/Cmd+D is bookmark) would be taken from us.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key !== 'D' && event.key !== 'd') return;
      const target = event.target as HTMLElement | null;
      if (target?.isContentEditable) return;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      event.preventDefault();

      const prefs = readDisplay();
      const next = { ...prefs, discreet: prefs.discreet === 'on' ? null : ('on' as const) };
      applyDisplay(next);
      // Announced, because the whole point is that the screen just changed
      // under an audience and the teacher needs to know which way.
      setShortcutSaid(next.discreet === 'on' ? tdiscreet('toggled') : tdiscreet('untoggled'));
      // And persisted, so the choice survives the lesson it was made in.
      updatePrefs.mutate({ locale, ...next });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [locale, tdiscreet, updatePrefs]);

  // The login screen is chromeless.
  if (pathname === '/login') {
    return <main className="min-h-screen">{children}</main>;
  }

  const nav = (onNavigate?: () => void) => (
    <nav className="flex flex-col gap-1" aria-label={t('primary')}>
      {DESTINATIONS.map((d) => (
        <Link
          key={d.href}
          href={d.href}
          onClick={onNavigate}
          aria-current={isActive(pathname, d.href) ? 'page' : undefined}
          className="flex min-h-11 items-center gap-3 rounded-md px-3 py-2 text-body-s font-bold no-underline transition-colors aria-[current=page]:bg-primary-100 aria-[current=page]:text-primary-700 hover:bg-primary-050 text-ink-700"
        >
          <span aria-hidden="true" className="shrink-0">
            {d.icon}
          </span>
          {t(d.labelKey)}
        </Link>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="visually-hidden focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-surface focus:px-4 focus:py-2"
      >
        {t('skipToContent')}
      </a>

      {/* What the keyboard shortcut just did. A live region rather than a
          toast: it is the screen changing under an audience, and it has to be
          announced without anything to dismiss. */}
      <p className="visually-hidden" role="status" aria-live="polite">
        {shortcutSaid ?? ''}
      </p>

      {/* One bar, and it stays until a request succeeds (F24). The product is
          used on a phone in a classroom — the worst wifi in the building — and
          nothing told a teacher that the reason a verdict would not save was
          the connection: every failure read as "L'envoi a échoué. Réessayez."

          Never colour alone (DC-colour-08): the word says it too. */}
      {offline ? (
        <p
          role="status"
          aria-live="polite"
          className="flex min-h-11 items-center justify-center gap-2 bg-warn-100 px-4 py-2 text-center text-body-s font-bold text-warn-700"
        >
          {tconn('offline')}
        </p>
      ) : null}

      {/* A past year, said loudly and on every screen.
          Deliberately a full-width bar and not a chip. Every number below it —
          the matrix, the roster, the piles, a class average — belongs to a year
          that has ended, and a teacher reading last year's figures as this
          year's is a worse outcome than not being able to look at all (G3).
          It offers the way back in the same breath, because the commonest reason
          to be here is having forgotten the switcher is set.

          Never colour alone (DC-colour-08): the year is named in words. */}
      {selectedYear && isPastYear ? (
        <p
          role="status"
          aria-live="polite"
          data-past-year
          className="flex min-h-11 flex-wrap items-center justify-center gap-x-2 gap-y-1 bg-warn-100 px-4 py-2 text-center text-body-s font-bold text-warn-700"
        >
          <span>{tyear('pastYear', { year: selectedYear.label })}</span>
          {currentYear ? (
            <button
              type="button"
              onClick={() => setSchoolYear(currentYear.id)}
              className="min-h-11 underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:shadow-[var(--focus-ring)]"
            >
              {tyear('backToCurrent', { year: currentYear.label })}
            </button>
          ) : null}
        </p>
      ) : null}

      {/* Mobile header */}
      <header
        data-app-header
        className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-surface px-4 py-3 md:hidden"
      >
        {/* The logo is a link home, so it is a tap target and takes the 44px
            floor like every other one. */}
        <Link href="/" className="flex min-h-11 items-center no-underline">
          <AlppyLogo size="sm" />
        </Link>
        <IconButton
          label={t('openMenu')}
          icon={<IconMenu />}
          onClick={() => setDrawerOpen(true)}
          variant="ghost"
        />
      </header>

      <Sheet
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={t('menu')}
        closeLabel={t('closeMenu')}
      >
        <div className="mb-4">
          <ScopeSwitcher onNavigate={() => setDrawerOpen(false)} />
        </div>
        {nav(() => setDrawerOpen(false))}
      </Sheet>

      <div className="md:flex">
        {/* Persistent rail from md up */}
        <aside className="hidden w-60 shrink-0 border-r border-line bg-surface p-4 md:block md:min-h-screen">
          <Link href="/" className="mb-6 flex min-h-11 items-center no-underline">
            <AlppyLogo size="md" />
          </Link>
          <div className="mb-4">
            <ScopeSwitcher />
          </div>
          {nav()}
        </aside>

        <main
          id="main"
          tabIndex={-1}
          className="min-w-0 flex-1 px-4 pb-24 pt-4 md:px-8 md:pb-12 md:pt-8"
        >
          {children}
        </main>
      </div>

      {/* Bottom tabs, phone only. Four primary destinations, 44px targets. */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-surface md:hidden"
        aria-label={t('primary')}
      >
        {DESTINATIONS.filter((d) => d.primary).map((d) => (
          <Link
            key={d.href}
            href={d.href}
            aria-current={isActive(pathname, d.href) ? 'page' : undefined}
            className="flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-label no-underline aria-[current=page]:text-primary-700 text-ink-500"
          >
            <span aria-hidden="true">{d.icon}</span>
            {t(d.labelKey)}
          </Link>
        ))}
      </nav>
    </div>
  );
}
