'use client';

import {
  AlppyLogo,
  IconHome,
  IconMatrix,
  IconAi,
  IconScan,
  IconSettings,
  IconSheet,
  IconBook,
  IconMenu,
  IconButton,
  Sheet,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState, type ReactNode } from 'react';

// next-intl's usePathname already has the locale prefix stripped, so route
// matching below never has to know which locale it is in.
import { Link, usePathname } from '@/i18n/navigation';

interface Destination {
  href: string;
  labelKey: 'home' | 'classes' | 'sheets' | 'scans' | 'adaptive' | 'sources' | 'settings';
  icon: ReactNode;
  primary: boolean;
}

const DESTINATIONS: Destination[] = [
  { href: '/', labelKey: 'home', icon: <IconHome />, primary: true },
  { href: '/classes', labelKey: 'classes', icon: <IconMatrix />, primary: true },
  { href: '/sheets/new', labelKey: 'sheets', icon: <IconSheet />, primary: true },
  { href: '/scans/new', labelKey: 'scans', icon: <IconScan />, primary: true },
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
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // The login screen is chromeless.
  if (pathname === '/login') {
    return <main className="min-h-screen">{children}</main>;
  }

  const nav = (onNavigate?: () => void) => (
    <nav className="flex flex-col gap-1" aria-label={t('home')}>
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
        title={t('openMenu')}
        closeLabel={t('closeMenu')}
      >
        {nav(() => setDrawerOpen(false))}
      </Sheet>

      <div className="md:flex">
        {/* Persistent rail from md up */}
        <aside className="hidden w-60 shrink-0 border-r border-line bg-surface p-4 md:block md:min-h-screen">
          <Link href="/" className="mb-6 flex min-h-11 items-center no-underline">
            <AlppyLogo size="md" />
          </Link>
          {nav()}
        </aside>

        <main id="main" className="min-w-0 flex-1 px-4 pb-24 pt-4 md:px-8 md:pb-12 md:pt-8">
          {children}
        </main>
      </div>

      {/* Bottom tabs, phone only. Four primary destinations, 44px targets. */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-surface md:hidden"
        aria-label={t('home')}
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
