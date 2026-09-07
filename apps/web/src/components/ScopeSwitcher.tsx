'use client';

import { Field, Select } from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';

import { useScope } from '@/lib/scope';
import type { Uuid } from '@/lib/api/types';

/**
 * The class and subject every screen below is scoped to.
 *
 * Two native `<select>`s on purpose: this is the control a teacher touches
 * most, it has to be operable from the keyboard without learning anything, and
 * on a phone the platform picker beats any listbox we would write. `Field`
 * gives each one a real `<label>`, so the accessible name is the word
 * "Class"/"Subject" and not the current value.
 *
 * It renders nothing at all when there is only one class and one subject —
 * a switcher with one option in it is furniture, not a control.
 */
export function ScopeSwitcher({ onNavigate }: { onNavigate?: () => void }) {
  const t = useTranslations('nav');
  const locale = useLocale();
  const { classes, subjects, classId, subjectId, setClass, setSubject, isLoading } =
    useScope();

  if (isLoading) return null;
  if (classes.length <= 1 && subjects.length <= 1) return null;

  return (
    <div className="flex flex-col gap-3" data-scope-switcher>
      {classes.length > 1 ? (
        <Field label={t('currentClass')}>
          <Select
            value={classId ?? ''}
            onChange={(event) => {
              setClass(event.currentTarget.value as Uuid);
              onNavigate?.();
            }}
          >
            {classes.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code}
                {c.label ? ` — ${c.label}` : ''}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}

      {subjects.length > 1 ? (
        <Field label={t('currentSubject')}>
          <Select
            value={subjectId ?? ''}
            onChange={(event) => {
              setSubject(event.currentTarget.value as Uuid);
              onNavigate?.();
            }}
          >
            {subjects.map((s) => (
              <option key={s.id} value={s.id}>
                {s.labels?.[locale] ?? s.labels?.fr ?? s.key}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}
    </div>
  );
}
