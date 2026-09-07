'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { ToastProvider, TooltipProvider } from '@alppy/ui';
import { Suspense, useState, type ReactNode } from 'react';

import { ScopeProvider } from '@/lib/scope';

export function Providers({ children }: { children: ReactNode }) {
  const t = useTranslations('common');
  const a11y = useTranslations('a11y');
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

  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <ToastProvider regionLabel={a11y('loading')} dismissLabel={t('close')}>
          {/* ScopeProvider reads the query string, so it needs a Suspense
              boundary or the statically-rendered locale routes fail to build. */}
          <Suspense fallback={null}>
            <ScopeProvider>{children}</ScopeProvider>
          </Suspense>
        </ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
