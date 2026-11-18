'use client';

import {MutationCache, QueryCache, QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {MotionConfig} from 'framer-motion';
import {useState, type ReactNode} from 'react';
import {ApiError} from '@/lib/api';

function redirectOnExpiredSession(error: unknown) {
  if (error instanceof ApiError && error.status === 401 && typeof window !== 'undefined') {
    const locale = window.location.pathname.split('/')[1] || 'en';
    // Full reload on purpose: drops every cached query of the expired session.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/${locale}/login?next=${encodeURIComponent(window.location.pathname)}`);
  }
}

export function Providers({children}: {children: ReactNode}) {
  const [client] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({onError: redirectOnExpiredSession}),
        mutationCache: new MutationCache({onError: redirectOnExpiredSession}),
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2
          }
        }
      })
  );
  return (
    <QueryClientProvider client={client}>
      {/* Framer Motion honours the OS reduced-motion setting everywhere. */}
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </QueryClientProvider>
  );
}
