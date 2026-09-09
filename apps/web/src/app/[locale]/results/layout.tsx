import type { Metadata } from 'next';
import { getTranslations } from 'next-intl/server';
import type { ReactNode } from 'react';

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'results' });
  return { title: `${t('title')} · Alppy` };
}

export default function SegmentLayout({ children }: { children: ReactNode }) {
  return children;
}
