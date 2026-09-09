import type { Metadata } from 'next';
import { getTranslations } from 'next-intl/server';
import type { ReactNode } from 'react';

/** Its own title, like every other segment: a tab must name its screen. */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'tree' });
  return { title: `${t('competence')} · Alppy` };
}

export default function SegmentLayout({ children }: { children: ReactNode }) {
  return children;
}
