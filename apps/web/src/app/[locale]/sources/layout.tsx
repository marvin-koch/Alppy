import type { Metadata } from 'next';
import { getTranslations } from 'next-intl/server';
import type { ReactNode } from 'react';

/**
 * A per-route title. Every page shared one `<title>Alppy</title>`, so a browser
 * tab, a history entry and a screen-reader page announcement could not tell one
 * screen from another.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'sources' });
  return { title: `${t('title')} · Alppy` };
}

export default function SegmentLayout({ children }: { children: ReactNode }) {
  return children;
}
