'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { ToastProvider, TooltipProvider } from '@alppy/ui';
import { Suspense, useEffect, useState, type ReactNode } from 'react';

import { setUnauthorizedHandler } from '@/lib/api/client';
import { usePathname, useRouter } from '@/i18n/navigation';
import { RevealProvider } from '@/lib/discreet';
import { ScopeProvider } from '@/lib/scope';
import { useSchoolYears } from '@/lib/api/queries';
import { SchoolYearProvider } from '@/lib/school-year';

export function Providers({ children }: { children: ReactNode }) {
  const t = useTranslations('common');
  const a11y = useTranslations('a11y');
  const router = useRouter();
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: (failureCount, error) => {
              // A 401 means the session is gone; retrying just delays the
              // redirect to login.
              const status = (error as { status?: number } | null)?.status;
              if (status === 401 || status === 404) return false;
              return failureCount < 2;
            },
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  // The other half of the retry rule above. Declining to retry a 401 stops the
  // pointless requests; it does not tell the teacher anything, and the
  // middleware only redirects on a navigation — which is exactly what someone
  // working inside one screen never does. So the redirect happens here, at the
  // one place every request already passes through.
  //
  // The cache is cleared first and deliberately: it holds another teacher's
  // session's worth of rosters and results, keyed by nothing that changes when
  // the session does. Leaving it would show the next person to sign in on this
  // browser the previous teacher's classes until each key happened to refetch.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      client.clear();
      // `from` carries the locale prefix, the way the middleware writes it —
      // `login/page.tsx` strips it back off. Read from `window` rather than
      // from a hook: this fires from inside a fetch, and the pathname that
      // matters is the one on screen at that moment.
      const here = `${window.location.pathname}${window.location.search}`;
      if (here.includes('/login')) return;
      router.replace(`/login?from=${encodeURIComponent(here)}`);
    });
    return () => setUnauthorizedHandler(null);
  }, [client, router]);

  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <ToastProvider regionLabel={a11y('loading')} dismissLabel={t('close')}>
          {/* ScopeProvider reads the query string, so it needs a Suspense
              boundary or the statically-rendered locale routes fail to build. */}
          <Suspense fallback={null}>
            {/* Projector mode's temporary reveal: one provider, reset on every
                navigation, so it cannot outlive the screen it was meant for. */}
            <RevealProvider>
              {/* ABOVE ScopeProvider, which calls `useClasses` — and `useClasses`
                  now reads the selected year. Below it and the class list would
                  be fetched for "no year" on the first render and cached under
                  that key. */}
              <SchoolYearGate>
                <ScopeProvider>{children}</ScopeProvider>
              </SchoolYearGate>
            </RevealProvider>
          </Suspense>
        </ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

/**
 * Fetches the year list and hands it to `SchoolYearProvider`.
 *
 * Split out because `lib/school-year.tsx` must not import `lib/api/queries`:
 * `queries` imports `useSelectedYear`, and the other direction would close a
 * cycle. So the provider takes the list as a prop and this component is the one
 * place that knows where the list comes from.
 */
function SchoolYearGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  // The login screen is outside the session, exactly as `ScopeProvider` treats it.
  const years = useSchoolYears(pathname !== '/login');
  return (
    <SchoolYearProvider years={years.data ?? []} isLoading={years.isLoading}>
      {children}
    </SchoolYearProvider>
  );
}
