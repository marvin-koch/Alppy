'use client';

import {
  Badge,
  Button,
  Card,
  ConfidenceBar,
  ErrorState,
  LoadingState,
  Panel,
  SegmentedControl,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { use, useMemo } from 'react';

import { useConfirmScan, useCorrectDetection, useScan } from '@/lib/api/queries';
import type { DetectionOut } from '@/lib/api/types';

const LOW_CONFIDENCE = 0.65;

export default function ScanReviewPage({ params }: { params: Promise<{ scanId: string }> }) {
  const { scanId } = use(params);
  const t = useTranslations('scans');
  const tc = useTranslations('common');
  const te = useTranslations('errors.generic');

  const scan = useScan(scanId);
  const correct = useCorrectDetection(scanId);
  const confirm = useConfirmScan(scanId);

  // Low confidence first: the whole point of the review screen is that the
  // teacher's attention goes where the machine is least sure, not top to bottom.
  const pages = useMemo(() => {
    return (scan.data?.pages ?? []).map((page) => ({
      ...page,
      detections: [...page.detections].sort((a, b) => a.confidence - b.confidence),
    }));
  }, [scan.data]);

  const toCheck = pages.reduce(
    (n, p) => n + p.detections.filter((d) => d.confidence < LOW_CONFIDENCE).length,
    0,
  );

  if (scan.isLoading) return <LoadingState shape="list" label={tc('loading')} rows={6} />;
  if (scan.isError || !scan.data) {
    return (
      <ErrorState
        title={te('title')}
        description={te('body')}
        action={<Button onClick={() => void scan.refetch()}>{tc('retry')}</Button>}
      />
    );
  }

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1>{t('review')}</h1>
          <p className="text-body-s text-ink-500">{t('reviewHelp')}</p>
        </div>
        <Button
          variant="primary"
          loading={confirm.isPending}
          busyLabel={t('confirming')}
          onClick={() => confirm.mutate()}
          disabled={scan.data.status === 'confirmed'}
        >
          {t('confirm')}
        </Button>
      </header>

      <Panel className="mb-4">
        <p className="text-body-s">{t('itemsToCheck', { count: toCheck })}</p>
      </Panel>

      {confirm.isSuccess ? (
        <Panel className="mb-4" role="status">
          <p className="text-body-s">{t('confirmed')}</p>
        </Panel>
      ) : null}

      <div className="flex flex-col gap-4">
        {pages.map((page) => (
          <Card key={page.id}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-h3">
                {page.detected_uid ? (
                  t('identifiedAs', { uid: page.detected_uid })
                ) : (
                  <span className="text-danger-600">{t('notIdentified')}</span>
                )}
              </h2>
              {!page.registered ? (
                <Badge variant="danger">{t('registrationFailed')}</Badge>
              ) : null}
            </div>

            {!page.registered ? (
              <p className="text-body-s text-ink-700">{t('registrationHelp')}</p>
            ) : (
              <ul className="flex list-none flex-col gap-3 p-0">
                {page.detections.map((d) => (
                  <li key={d.id}>
                    <DetectionRow
                      detection={d}
                      onCorrect={(index) =>
                        correct.mutate({ detectionId: d.id, body: { detected_index: index } })
                      }
                    />
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}

function DetectionRow({
  detection,
  onCorrect,
}: {
  detection: DetectionOut;
  onCorrect: (index: number | null) => void;
}) {
  const t = useTranslations('scans');
  const options = detection.fill_ratios?.length ?? 4;

  return (
    <Panel sunken={detection.confidence < LOW_CONFIDENCE}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="mono text-body-s" data-numeric>
          #{detection.item_index + 1}
        </span>
        <Badge
          variant={
            detection.outcome === 'detected'
              ? 'success'
              : detection.outcome === 'corrected'
                ? 'primary'
                : detection.outcome === 'not_gradeable'
                  ? 'neutral'
                  : 'warn'
          }
        >
          {t(`outcome.${detection.outcome}`)}
        </Badge>
      </div>

      <div className="mt-2">
        <ConfidenceBar
          value={detection.confidence}
          threshold={LOW_CONFIDENCE}
          label={t('confidence')}
          lowLabel={t('lowConfidence')}
        />
      </div>

      {detection.outcome !== 'not_gradeable' ? (
        <div className="mt-3">
          {/* One click corrects the machine. Always available, never buried. */}
          <SegmentedControl
            value={String(detection.detected_index ?? '')}
            onValueChange={(v) => onCorrect(v === '' ? null : Number(v))}
            label={t('detected')}
            size="sm"
            options={[
              ...Array.from({ length: options }, (_, i) => ({
                value: String(i),
                label: 'ABCD'[i] ?? String(i),
              })),
              { value: '', label: '—' },
            ]}
          />
        </div>
      ) : null}
    </Panel>
  );
}
