'use client';

import { Button, Card, Field, Input, Select } from '@alppy/ui';
import { SWISS_CANTONS } from '@alppy/shared/api-constants';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { LockedValue } from '@/components/LockedValue';
import { Link } from '@/i18n/navigation';
import { apiErrorMessage } from '@/lib/api/error-message';
import {
  useCreateSchool,
  useCreateSubject,
  useMe,
  useSubjects,
  useUpdateSchool,
  useUpdateSubject,
} from '@/lib/api/queries';
import type { SubjectOut, Uuid } from '@/lib/api/types';

/**
 * The school's own nouns: its name, and the Branches it studies.
 *
 * Both were seed-only until now, which meant a school that wanted a fourth
 * Branch had to ask someone with database access.
 *
 * Two fields are deliberately shown and locked rather than hidden. The
 * curriculum, because every Theme is already attached to it and changing it
 * would re-file the whole programme (D56); and a Branch's `key`, because the
 * curriculum joins on that string. A locked field with its reason reads as a
 * rule; an absent one reads as a missing feature.
 */
export function SchoolSettings() {
  const t = useTranslations('settings');
  const tc = useTranslations('common');
  const tcode = useTranslations('errors.code');
  const locale = useLocale();

  const me = useMe();
  const subjects = useSubjects();
  const updateSchool = useUpdateSchool();
  const createSchool = useCreateSchool();
  const createSubject = useCreateSubject();
  const updateSubject = useUpdateSubject();

  const school = (me.data?.schools ?? []).find((s) => s.id === me.data?.school_id);
  const [name, setName] = useState('');
  const [canton, setCanton] = useState('');
  const [newKey, setNewKey] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [renaming, setRenaming] = useState<Uuid | null>(null);
  const [renameTo, setRenameTo] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [newSchoolName, setNewSchoolName] = useState('');
  const [newSchoolCanton, setNewSchoolCanton] = useState('');

  const label = (subject: SubjectOut) =>
    subject.labels?.[locale] ?? subject.labels?.fr ?? subject.key;

  function report(caught: unknown) {
    setError(apiErrorMessage(caught, tcode));
  }

  return (
    <div className="flex flex-col gap-6">
      <Card className="flex flex-col gap-4">
        <h2 className="text-h3">{t('school')}</h2>
        <Field label={t('schoolName')}>
          <Input
            value={name || (school?.name ?? '')}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        {/* A picker, not a two-character box (F21). `School.canton` is what a
            curriculum mapping keys on, so "XX" or a typo for "ZH" was a stored
            fact nothing downstream could use — and the teacher was told about
            it, if at all, by a 422 after saving. The list is the server's own
            `SWISS_CANTONS`, generated rather than retyped, so the picker
            cannot offer a value the API would refuse. */}
        <Field label={t('canton')}>
          <Select
            className="max-w-[12rem]"
            value={canton || (school?.canton ?? '')}
            onChange={(e) => setCanton(e.target.value)}
          >
            <option value="">{tc('none')}</option>
            {SWISS_CANTONS.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('curriculum')} help={t('curriculumLocked')}>
          {/* An em dash rather than an empty box: a blank locked field reads
              as a screen that failed to load, not as a settled value. */}
          <LockedValue>{school?.default_curriculum ?? '—'}</LockedValue>
        </Field>
        <div className="flex justify-end border-t border-line pt-4">
          <Button
            variant="primary"
            disabled={updateSchool.isPending}
            onClick={() => {
              setError(null);
              updateSchool.mutate(
                { name: name || school?.name, canton: canton || school?.canton },
                { onError: report },
              );
            }}
          >
            {tc('save')}
          </Button>
        </div>
      </Card>

      {/* A second establishment (F27). `POST /schools` has existed since the
          contract was written and nothing called it, so a teacher who moves,
          or who teaches at two, could not make the second one — and every
          screen is scoped to a school. Creating does not switch: the route
          says so itself, and moving the tenant out from under someone who was
          only setting things up is not what they asked for. */}
      <Card className="flex flex-col gap-4">
        <div>
          <h2 className="text-h3">{t('newSchoolTitle')}</h2>
          <p className="mt-1 max-w-prose text-body-s text-ink-700">{t('newSchoolHelp')}</p>
        </div>
        <Field label={t('schoolName')}>
          <Input value={newSchoolName} onChange={(e) => setNewSchoolName(e.target.value)} />
        </Field>
        <Field label={t('canton')}>
          <Select
            className="max-w-[12rem]"
            value={newSchoolCanton}
            onChange={(e) => setNewSchoolCanton(e.target.value)}
          >
            <option value="">{tc('none')}</option>
            {SWISS_CANTONS.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </Select>
        </Field>
        <div className="flex justify-end border-t border-line pt-4">
          <Button
            variant="secondary"
            disabled={!newSchoolName.trim() || createSchool.isPending}
            loading={createSchool.isPending}
            busyLabel={tc('saving')}
            onClick={() => {
              setError(null);
              createSchool.mutate(
                { name: newSchoolName.trim(), canton: newSchoolCanton || null },
                {
                  onSuccess: () => {
                    setNewSchoolName('');
                    setNewSchoolCanton('');
                  },
                  onError: report,
                },
              );
            }}
          >
            {t('newSchoolAction')}
          </Button>
        </div>
      </Card>

      <Card className="flex flex-col gap-3">
        <h2 className="text-h3">{t('branches')}</h2>
        <ul className="flex flex-col gap-2">
          {(subjects.data ?? []).map((subject) => (
            <li
              key={subject.id}
              className="flex min-h-11 items-center gap-3 rounded-md border border-line bg-surface px-4 py-2"
            >
              {renaming === subject.id ? (
                <>
                  <Input
                    className="flex-1"
                    value={renameTo}
                    onChange={(e) => setRenameTo(e.target.value)}
                  />
                  <Button
                    variant="primary"
                    onClick={() => {
                      setError(null);
                      updateSubject.mutate(
                        {
                          subjectId: subject.id,
                          labels: { ...subject.labels, [locale]: renameTo },
                        },
                        { onSuccess: () => setRenaming(null), onError: report },
                      );
                    }}
                  >
                    {tc('save')}
                  </Button>
                </>
              ) : (
                <>
                  <span className="min-w-0 flex-1 truncate font-semibold">
                    {label(subject)}
                  </span>
                  <span className="font-mono text-label text-ink-500">{subject.key}</span>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setRenaming(subject.id);
                      setRenameTo(label(subject));
                    }}
                  >
                    {t('rename')}
                  </Button>
                  {/* Themes and textbooks are what a Branch is MADE of, and
                      there are enough of them to need their own screen. */}
                  <Link href={`/settings/branches/${subject.id}`} className="text-body-s font-semibold">
                    {t('manageBranch')}
                  </Link>
                </>
              )}
            </li>
          ))}
        </ul>

        <div className="mt-2 flex flex-col gap-3 rounded-md border border-line bg-surface-2 p-4">
          <p className="text-label font-semibold uppercase tracking-label text-ink-500">
            {t('addBranch')}
          </p>
          <Field label={t('branchName')}>
            <Input value={newLabel} onChange={(e) => setNewLabel(e.target.value)} />
          </Field>
          <Field label={t('branchKey')} help={t('branchKeyHelp')}>
            <Input
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              spellCheck={false}
            />
          </Field>
          <div className="flex justify-end">
            <Button
              variant="primary"
              disabled={createSubject.isPending || newKey.trim().length < 2}
              onClick={() => {
                setError(null);
                createSubject.mutate(
                  { key: newKey, labels: { [locale]: newLabel || newKey } },
                  {
                    onSuccess: () => {
                      setNewKey('');
                      setNewLabel('');
                    },
                    onError: report,
                  },
                );
              }}
            >
              {t('create')}
            </Button>
          </div>
        </div>
      </Card>

      {error ? (
        <p role="alert" className="text-body-s text-danger-600">
          {error}
        </p>
      ) : null}
    </div>
  );
}
