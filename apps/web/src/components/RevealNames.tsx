'use client';

/**
 * The deliberate act that puts names back on a projected screen.
 *
 * Renders nothing at all when projector mode is off, which is the common case
 * — a control that is present but inert on every screen would be furniture,
 * and the point of this one is that it is only there when it means something.
 *
 * The reveal is React state in `RevealProvider` and nowhere else: leaving the
 * screen ends it, a reload ends it, and it never reaches storage or the
 * teacher record. A reveal that persisted would be a projector mode that
 * quietly turns itself off between lessons.
 */

import { Button, IconWarning } from '@alppy/ui';
import { useTranslations } from 'next-intl';

import { useDiscretion } from '@/lib/discreet';

export function RevealNames({ className }: { className?: string }) {
  const t = useTranslations('discreet');
  const { discreet, revealed, setRevealed } = useDiscretion();

  if (!discreet) return null;

  return (
    <div className={className}>
      <Button
        size="sm"
        variant="secondary"
        leadingIcon={revealed ? <IconWarning /> : undefined}
        onClick={() => setRevealed(!revealed)}
        // The state it is IN, announced: a teacher who has revealed names on a
        // projector needs the screen to keep saying so.
        aria-pressed={revealed}
      >
        {revealed ? t('hideNames') : t('showNames')}
      </Button>
      {revealed ? (
        <p className="mt-1 text-body-s text-warn-700" role="status">
          {t('revealedWarning')}
        </p>
      ) : null}
    </div>
  );
}
