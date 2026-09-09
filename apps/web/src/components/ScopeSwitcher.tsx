'use client';

import { IconChevronDown, SelectSurface } from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';

import { useMe, useSwitchSchool } from '@/lib/api/queries';
import { useScope } from '@/lib/scope';
import type { Uuid } from '@/lib/api/types';

/**
 * The class and subject every screen below is scoped to.
 *
 * Still two native `<select>`s, and for the reasons they always were: this is
 * the control a teacher touches most, it has to be operable from the keyboard
 * without learning anything, and on a phone the platform picker beats any
 * listbox we would write. `SelectSurface` keeps all of that and replaces only
 * the appearance — the two stacked boxes under two shouty uppercase labels
 * cost a third of the rail's height to say two short words, and the class row
 * truncated its own name ("7B — Classe de Mm").
 *
 * One panel, two rows, one idea: where you are. The code is the thing a
 * teacher recognises, so it leads; the long label follows and truncates
 * gracefully instead of clipping mid-word.
 *
 * It renders nothing at all when there is only one class and one subject — a
 * switcher with one option in it is furniture, not a control. When only one of
 * the two is a real choice, the other stays as plain text rather than an empty
 * gap: the rail should still say which class you are in.
 */
export function ScopeSwitcher({ onNavigate }: { onNavigate?: () => void }) {
  const t = useTranslations('nav');
  const locale = useLocale();
  const { classes, subjects, classId, subjectId, setClass, setSubject, isLoading } =
    useScope();
  const me = useMe();
  const switchSchool = useSwitchSchool();

  // A teacher at one school never sees a school row: switching is real but
  // rare, and a control with one option is furniture (D74).
  const schools = me.data?.schools ?? [];
  const currentSchool = schools.find((school) => school.id === me.data?.school_id);

  if (isLoading) return null;
  if (classes.length <= 1 && subjects.length <= 1 && schools.length <= 1) return null;

  const current = classes.find((c) => c.id === classId) ?? classes[0];
  const currentSubject = subjects.find((s) => s.id === subjectId) ?? subjects[0];
  const subjectName = (s: (typeof subjects)[number]) =>
    s.labels?.[locale] ?? s.labels?.fr ?? s.key;

  const row = 'flex min-h-11 items-center gap-2 px-3';

  return (
    <div
      className="overflow-hidden rounded-md border border-line bg-surface"
      data-scope-switcher
    >
      {schools.length > 1 ? (
        <SelectSurface
          label={t('switchSchool')}
          value={me.data?.school_id ?? ''}
          onChange={(value) => {
            // Everything below this row belongs to the school we are leaving,
            // so the mutation clears the cache rather than invalidating it.
            switchSchool.mutate(value as Uuid);
            onNavigate?.();
          }}
          disabled={switchSchool.isPending}
          options={schools.map((school) => ({ value: school.id, label: school.name }))}
        >
          <span className={`${row} border-b border-line`}>
            <span className="min-w-0 flex-1 truncate text-body-s font-semibold text-ink-900">
              {currentSchool?.name ?? ''}
            </span>
            <IconChevronDown size={16} className="shrink-0 text-ink-500" />
          </span>
        </SelectSurface>
      ) : null}

      {classes.length > 1 ? (
        <SelectSurface
          label={t('switchClass')}
          value={classId ?? ''}
          onChange={(value) => {
            setClass(value as Uuid);
            onNavigate?.();
          }}
          options={classes.map((c) => ({
            value: c.id,
            label: c.label ? `${c.code} — ${c.label}` : c.code,
          }))}
        >
          <span className={row}>
            <span className="rounded-sm bg-primary-100 px-2 py-0.5 font-display text-body-s font-semibold text-primary-700">
              {current?.code}
            </span>
            <span className="min-w-0 flex-1 truncate text-body-s text-ink-700">
              {current?.label ?? ''}
            </span>
            <IconChevronDown size={16} className="shrink-0 text-ink-500" />
          </span>
        </SelectSurface>
      ) : current ? (
        <span className={row}>
          <span className="rounded-sm bg-primary-100 px-2 py-0.5 font-display text-body-s font-semibold text-primary-700">
            {current.code}
          </span>
          <span className="min-w-0 flex-1 truncate text-body-s text-ink-700">
            {current.label ?? ''}
          </span>
        </span>
      ) : null}

      {subjects.length > 1 ? (
        <SelectSurface
          className="border-t border-line"
          label={t('switchSubject')}
          value={subjectId ?? ''}
          onChange={(value) => {
            setSubject(value as Uuid);
            onNavigate?.();
          }}
          options={subjects.map((s) => ({ value: s.id, label: subjectName(s) }))}
        >
          <span className={row}>
            <span className="min-w-0 flex-1 truncate text-body-s font-semibold text-ink-900">
              {currentSubject ? subjectName(currentSubject) : ''}
            </span>
            <IconChevronDown size={16} className="shrink-0 text-ink-500" />
          </span>
        </SelectSurface>
      ) : currentSubject ? (
        <span className={`${row} border-t border-line`}>
          <span className="min-w-0 flex-1 truncate text-body-s font-semibold text-ink-900">
            {subjectName(currentSubject)}
          </span>
        </span>
      ) : null}
    </div>
  );
}
