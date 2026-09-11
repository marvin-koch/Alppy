'use client';

import { Button, Card, Field, Input, RosterInput, parseRoster } from '@alppy/ui';
import { classCodeRe } from '@alppy/shared';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Link, useRouter } from '@/i18n/navigation';
import { useAddStudents, useCreateClass } from '@/lib/api/queries';
import { apiErrorMessage } from '@/lib/api/error-message';

/**
 * Create a class and paste its roster, in one screen.
 *
 * This route did not exist. `POST /classes` and `POST /classes/{id}/students`
 * shipped, `RosterInput` shipped, and nine `classes.*` strings were translated
 * three times — but nothing called any of it, so a teacher with no classes was
 * sent to a page with no controls and could not start.
 *
 * One screen rather than two steps: a class with no pupils in it cannot do
 * anything, so making the roster a separate errand afterwards just invites
 * stopping halfway. The roster is still optional — a teacher who does not have
 * the list to hand should not be blocked from creating the class.
 */
export default function NewClassPage() {
  const t = useTranslations('classes');
  const tc = useTranslations('common');
  const tcode = useTranslations('errors.code');
  const router = useRouter();

  const [code, setCode] = useState('');
  const [label, setLabel] = useState('');
  const [roster, setRoster] = useState('');
  const [error, setError] = useState<string | null>(null);

  const createClass = useCreateClass();
  const addStudents = useAddStudents();
  const busy = createClass.isPending || addStudents.isPending;

  // Exactly `_CLASS_RE` in `alppy/core/uid.py` — one or two digits then one or
  // two letters. It has to be exact: looser here (this accepted `11ABC`) and
  // the form green-lights a code the server then rejects with a 422 the teacher
  // has to decode; stricter, and it refuses a code that would have worked.
  // The pattern comes from `alppy/core/uid.py` through the generated
  // contract, not from a copy typed here (F21). The copy had already drifted
  // once, and the drift was found by a person reading two files side by side.
  const codeValid = classCodeRe().test(code.trim());
  const parsed = parseRoster(roster);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!codeValid) {
      setError(t('codeInvalid'));
      return;
    }
    try {
      const created = await createClass.mutateAsync({
        code: code.trim().toUpperCase(),
        label: label.trim() || null,
      });
      if (parsed.length > 0) {
        await addStudents.mutateAsync({
          classId: created.id,
          body: {
            students: parsed.map((s) => ({
              first_name: s.firstName,
              last_name: s.lastName,
            })),
          },
        });
      }
      router.push(`/classes/${created.id}`);
    } catch (cause) {
      setError(apiErrorMessage(cause, tcode));
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6">{t('createHeading')}</h1>

      <form onSubmit={submit} noValidate>
        <Card className="mb-4">
          <div className="flex flex-col gap-4">
            <Field
              label={t('code')}
              help={t('createHelp')}
              error={code !== '' && !codeValid ? t('codeInvalid') : undefined}
            >
              <Input
                value={code}
                onChange={(event) => setCode(event.currentTarget.value)}
                placeholder="7B"
                autoComplete="off"
                aria-invalid={code !== '' && !codeValid}
                required
              />
            </Field>

            <Field label={t('labelField')}>
              <Input
                value={label}
                onChange={(event) => setLabel(event.currentTarget.value)}
                autoComplete="off"
              />
            </Field>
          </div>
        </Card>

        <Card className="mb-4">
          <h2 className="mb-3 text-h3">{t('addStudents')}</h2>
          <Field label={t('addStudents')} help={t('rosterHelp')} hideLabel>
            <RosterInput
              value={roster}
              onValueChange={setRoster}
              rows={8}
              renderSummary={(count) => t('rosterPreview', { count })}
            />
          </Field>
        </Card>

        {error ? (
          <p role="alert" className="mb-4 text-body-s text-danger-600">
            {error}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" disabled={busy || !codeValid}>
            {busy ? tc('loading') : t('create')}
          </Button>
          <Link href="/classes">{t('cancel')}</Link>
        </div>
      </form>
    </div>
  );
}
