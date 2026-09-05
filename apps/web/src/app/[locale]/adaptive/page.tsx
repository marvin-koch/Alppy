'use client';

import {
  AiBadge,
  Badge,
  Button,
  Card,
  ConceptTag,
  EmptyState,
  Field,
  IconDownload,
  IlloSummit,
  LoadingState,
  Panel,
  Slider,
  Toggle,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  useBatchAdaptive,
  useClasses,
  useJob,
  useProposeAdaptive,
  useSubjects,
} from '@/lib/api/queries';
import type { AdaptiveProposeResponse } from '@/lib/api/types';

export default function AdaptivePage() {
  const t = useTranslations('adaptive');
  const tc = useTranslations('common');
  const classes = useClasses();
  const subjects = useSubjects();

  const [itemsPerStudent, setItemsPerStudent] = useState(8);
  const [allowGeneration, setAllowGeneration] = useState(true);
  const [plan, setPlan] = useState<AdaptiveProposeResponse | null>(null);
  const [approved, setApproved] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);

  const propose = useProposeAdaptive();
  const batch = useBatchAdaptive();
  const job = useJob(jobId);

  const classId = classes.data?.[0]?.id ?? '';
  const subjectId = subjects.data?.[0]?.id ?? '';

  const generatedCount = plan?.generated_count ?? 0;

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6">
        <h1>{t('title')}</h1>
        <p className="text-ink-500">{t('subtitle')}</p>
      </header>

      <Card className="mb-6">
        <Field label={t('itemsPerStudent')}>
          <Slider
            min={1}
            max={16}
            value={itemsPerStudent}
            onValueChange={setItemsPerStudent}
          />
        </Field>

        <div className="mt-4">
          <Toggle
            label={t('allowGeneration')}
            description={t('allowGenerationHelp')}
            checked={allowGeneration}
            onCheckedChange={setAllowGeneration}
          />
        </div>

        <div className="mt-4">
          <Button
            variant="primary"
            loading={propose.isPending}
            busyLabel={t('preparing')}
            onClick={() =>
              propose.mutate(
                {
                  class_id: classId,
                  subject_id: subjectId,
                  student_ids: [],
                  items_per_student: itemsPerStudent,
                  allow_generation: allowGeneration,
                },
                {
                  onSuccess: (r) => {
                    setPlan(r);
                    setApproved(false);
                  },
                },
              )
            }
          >
            {t('propose')}
          </Button>
        </div>
      </Card>

      {propose.isPending ? (
        <LoadingState shape="list" label={t('preparing')} rows={5} />
      ) : !plan ? (
        <EmptyState
          illustration={<IlloSummit />}
          title={t('empty.title')}
          description={t('empty.body')}
        />
      ) : (
        <>
          {generatedCount > 0 ? (
            <Card tint="warm" className="mb-4">
              <p className="text-body-s">{t('aiNotice')}</p>
              <p className="mt-2 text-body-s font-bold">
                {t('needsApproval', { count: generatedCount })}
              </p>
              {!approved ? (
                <>
                  <p className="mt-1 text-body-s">{t('notApprovedWarning')}</p>
                  <div className="mt-3">
                    {/* The single sanctioned accent action (F4). */}
                    <Button variant="accent" onClick={() => setApproved(true)}>
                      {t('approveAll')}
                    </Button>
                  </div>
                </>
              ) : (
                <p className="mt-2 text-body-s" role="status">
                  {t('approved')}
                </p>
              )}
            </Card>
          ) : null}

          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-h3">{t('targeting')}</h2>
            <Button
              variant="primary"
              leadingIcon={<IconDownload />}
              loading={batch.isPending || job.data?.status === 'running'}
              busyLabel={t('exporting')}
              // Generated items must be approved before anything is printed.
              disabled={generatedCount > 0 && !approved}
              onClick={() =>
                batch.mutate(
                  {
                    class_id: classId,
                    subject_id: subjectId,
                    title: t('title'),
                    language: (plan.language ?? 'fr') as 'fr' | 'de' | 'en',
                    plans: plan.plans,
                  },
                  { onSuccess: (j) => setJobId(j.id) },
                )
              }
            >
              {t('exportBatch')}
            </Button>
          </div>

          {job.data?.status === 'succeeded' ? (
            <Panel className="mb-4" role="status">
              <p className="text-body-s">{t('batchReady')}</p>
            </Panel>
          ) : null}

          <ul className="flex list-none flex-col gap-3 p-0">
            {plan.plans.map((p) => (
              <li key={p.student_id}>
                <Panel>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    {/* The UID, not the name: this is what is printed and what
                        reaches a model. */}
                    <span className="mono font-bold" data-numeric>
                      {p.student_uid}
                    </span>
                    <div className="flex flex-wrap gap-2">
                      <Badge variant="info">
                        {t('retrieved')} · {p.retrieved.length}
                      </Badge>
                      {p.generated.length > 0 ? (
                        <Badge variant="neutral">
                          <AiBadge label={t('aiBadge')} size="sm" /> {p.generated.length}
                        </Badge>
                      ) : null}
                    </div>
                  </div>

                  {p.targeted_competency_ids.length > 0 ? (
                    <ul className="mt-2 flex list-none flex-wrap gap-1 p-0">
                      {p.targeted_competency_ids.slice(0, 6).map((id) => (
                        <li key={id}>
                          <ConceptTag code={id.slice(0, 8)} />
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </Panel>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="sr-only">{tc('loading')}</p>
    </div>
  );
}
