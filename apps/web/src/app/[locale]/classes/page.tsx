'use client';

import { Badge, Button, Card, EmptyState, ErrorState, IlloSlate, LoadingState } from '@alppy/ui';
import { useTranslations } from 'next-intl';

import { Link } from '@/i18n/navigation';
import { useClasses } from '@/lib/api/queries';

export default function ClassesPage() {
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
      <h1 className="mb-6">{th('title')}</h1>
      {classes.length === 0 ? (
        <EmptyState
          illustration={<IlloSlate />}
          title={th('empty.title')}
          description={th('empty.body')}
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
