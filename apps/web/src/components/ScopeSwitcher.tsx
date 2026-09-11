'use client';

import { IconChevronDown, SelectSurface } from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';

import { useMe, useSwitchSchool } from '@/lib/api/queries';
import { useScope } from '@/lib/scope';
import { useSelectedYear } from '@/lib/school-year';
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
 * teacher recognises, so it leads; the label follows on its own line, because
 * in Cycle 3 a "class" may be a niveau group and the label is the only place
 * that says so (F9).
 *
 * It renders nothing at all when there is only one class and one subject — a
 * switcher with one option in it is furniture, not a control. When only one of
 * the two is a real choice, the other stays as plain text rather than an empty
 * gap: the rail should still say which class you are in.
 */
export function ScopeSwitcher({ onNavigate }: { onNavigate?: () => void }) {
  const t = useTranslations('nav');
  const locale = useLocale();
  const { classes, subjects, classId, subjectId, setClass, setSubject, isLoading } = useScope();
  const me = useMe();
  const switchSchool = useSwitchSchool();
  // Above the class row, because it is above it in meaning: class and subject
  // narrow what you see WITHIN a year, and the year decides which year's roster,
  // sheets, piles and mastery are being narrowed.
  const { years, schoolYearId, setSchoolYear, isPastYear } = useSelectedYear();

  // A teacher at one school never sees a school row: switching is real but
  // rare, and a control with one option is furniture (D74).
  const schools = me.data?.schools ?? [];
  const currentSchool = schools.find((school) => school.id === me.data?.school_id);

  if (isLoading) return null;
  // A school in its first year has one year and gets no row, like a teacher at
  // one school. But a teacher LOOKING at a past year always gets the row, even
  // in the degenerate case: the way back must never be missing.
  const showYears = years.length > 1 || isPastYear;
  if (classes.length <= 1 && subjects.length <= 1 && schools.length <= 1 && !showYears) {
    return null;
  }

  const current = classes.find((c) => c.id === classId) ?? classes[0];
  const currentSubject = subjects.find((s) => s.id === subjectId) ?? subjects[0];
  const subjectName = (s: (typeof subjects)[number]) => s.labels?.[locale] ?? s.labels?.fr ?? s.key;

  const row = 'flex min-h-11 items-center gap-2 px-3';
  // The class row stacks instead of sharing one line. A code and a label were
  // competing for the same width with a chevron, so `10MB — Maths, niveau 2`
  // arrived as `10MB — Maths, nive…`. Until a class carries a `kind`, that
  // label is the ONLY thing telling a teacher whether they are looking at
  // their homeroom or at one of their teaching groups, and truncating it is
  // truncating the answer (F9).
  const classRow = 'flex min-h-11 flex-col justify-center gap-0.5 px-3 py-1.5';
  const classLabel = 'line-clamp-2 text-body-s leading-snug text-ink-700';

  return (
    <div className="overflow-hidden rounded-md border border-line bg-surface" data-scope-switcher>
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

      {showYears ? (
        <SelectSurface
          label={t('switchYear')}
          value={schoolYearId ?? ''}
          onChange={(value) => {
            setSchoolYear(value as Uuid);
            onNavigate?.();
          }}
          options={years.map((year) => ({ value: year.id, label: year.label }))}
        >
          <span className={`${row} border-b border-line`}>
            <span
              className="min-w-0 flex-1 truncate text-body-s font-semibold text-ink-900"
              data-numeric
            >
              {years.find((y) => y.id === schoolYearId)?.label ?? ''}
            </span>
            {/* The chip is the second channel: the row alone reads as a label,
                and a teacher who left the year selected yesterday needs the
                switcher itself to say so, not just the banner on the page. */}
            {isPastYear ? (
              <span className="shrink-0 rounded-sm bg-warn-100 px-1.5 py-0.5 text-label uppercase text-warn-600">
                {t('pastYearShort')}
              </span>
            ) : null}
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
          <span className={classRow}>
            <span className="flex items-center gap-2">
              <span className="rounded-sm bg-primary-100 px-2 py-0.5 font-display text-body-s font-semibold text-primary-700">
                {current?.code}
              </span>
              <IconChevronDown size={16} className="ml-auto shrink-0 text-ink-500" />
            </span>
            {current?.label ? <span className={classLabel}>{current.label}</span> : null}
          </span>
        </SelectSurface>
      ) : current ? (
        <span className={classRow}>
          <span className="flex items-center gap-2">
            <span className="rounded-sm bg-primary-100 px-2 py-0.5 font-display text-body-s font-semibold text-primary-700">
              {current.code}
            </span>
          </span>
          {current.label ? <span className={classLabel}>{current.label}</span> : null}
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
