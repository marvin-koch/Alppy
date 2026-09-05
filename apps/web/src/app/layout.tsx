import type { ReactNode } from 'react';

/**
 * The locale layout owns <html> and <body> so it can stamp `lang` correctly.
 * This root exists only because the App Router requires one.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return children;
}
