import '@fontsource-variable/fredoka';
import '@fontsource-variable/nunito';
import '@fontsource-variable/jetbrains-mono';
import '@fontsource-variable/caveat';
import '../globals.css';

import type { Metadata } from 'next';
import { NextIntlClientProvider } from 'next-intl';
import { getMessages, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import type { ReactNode } from 'react';

import { AppShell } from '@/components/AppShell';
import { Providers } from '@/components/Providers';
import { ThemeScript } from '@/components/ThemeScript';
import { isAppLocale, locales } from '@/i18n/routing';

export const metadata: Metadata = {
  title: 'Alppy',
  description: 'Teach more personally, work more efficiently.',
};

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isAppLocale(locale)) notFound();
  setRequestLocale(locale);
  const messages = await getMessages();

  return (
    <html lang={locale} suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      {/* body paints its own background explicitly — never inherits (DESIGN.md §8). */}
      <body className="bg-canvas text-ink-900 antialiased">
        <NextIntlClientProvider messages={messages}>
          <Providers>
            <AppShell>{children}</AppShell>
          </Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
