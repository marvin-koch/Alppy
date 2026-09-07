'use client';

import { Badge, Button, Card, EmptyState, ErrorState, IlloSlate, LoadingState } from '@alppy/ui';
import { useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';
import { useClasses } from '@/lib/api/queries';

export default function ClassesPage() {
  const t = useTranslations('classes');
  const th = useTranslations('home');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');
  const { data, isLoading, isError, refetch } = useClasses();

  if (isLoading) return <LoadingState shape="list" label={tc('loading')} rows={5} />;
  if (isError) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={<Button onClick={() => void refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  const classes = data ?? [];

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        {/* Its own string. This screen and the home screen both rendered
            `home.title`, so `/fr` and `/fr/classes` shared one <h1>. */}
        <h1>{t('allClasses')}</h1>
        <Link href="/classes/new" className="ard-btn" data-variant="primary">
          {t('create')}
        </Link>
      </div>
      {classes.length === 0 ? (
        <EmptyState
          illustration={<IlloSlate />}
          title={th('empty.title')}
          description={th('empty.body')}
          // This screen is where the home screen's "create a class" sends a
          // brand-new teacher. It had no action at all, so the onboarding path
          // terminated here.
          action={
            <Link href="/classes/new" className="ard-btn" data-variant="primary">
              {t('create')}
            </Link>
          }
        />
      ) : (
        <ul className="grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
          {classes.map((c) => (
            <li key={c.id}>
              <Card>
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-h3">
                    <Link
                      href={`/classes/${c.id}`}
                      className="text-ink-900 no-underline hover:text-primary-700"
                    >
                      {c.code}
                    </Link>
                  </h2>
                  <Badge>{th('students', { count: c.student_count })}</Badge>
                </div>
                {c.label ? <p className="mt-1 text-body-s text-ink-500">{c.label}</p> : null}
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
