'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ToastProvider, TooltipProvider } from '@alppy/ui';
import { useState, type ReactNode } from 'react';

export function Providers({ children }: { children: ReactNode }) {
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
        <ToastProvider>{children}</ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
