'use client';

import { Button, Field, Input, Panel } from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { ConfirmDestructive } from '@/components/ConfirmDestructive';
import { apiErrorMessage } from '@/lib/api/error-message';
import { useDeleteStudent, useUpdateStudent } from '@/lib/api/queries';
import type { StudentOut, Uuid } from '@/lib/api/types';

/**
 * Correct a pupil's name, or destroy them.
 *
 * The two live together because the second is what a teacher reaches for when
 * they mean the first — a misspelt name and a pupil who left look identical
 * from the roster. So the edit is the obvious path and the delete is behind a
 * dialog that names what dies and offers unenrolling beside it.
 *
 * `uid` and `number` are shown and locked rather than hidden: the teacher is
 * looking at the paper that carries them, and a field that quietly is not
 * there reads as a missing feature instead of a deliberate rule
 * (I-platform-09).
 */
export function StudentEditor({
  student,
  classId,
  onDone,
}: {
  student: StudentOut;
  classId: Uuid;
  onDone: () => void;
}) {
  const t = useTranslations('students');
  const tc = useTranslations('common');
  const tcode = useTranslations('errors.code');

  const [firstName, setFirstName] = useState(student.first_name);
  const [lastName, setLastName] = useState(student.last_name);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = useUpdateStudent();
  const remove = useDeleteStudent();
  const name = `${student.first_name} ${student.last_name}`;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await update.mutateAsync({
        studentId: student.id,
        classId,
        body: { first_name: firstName, last_name: lastName },
      });
      onDone();
    } catch (caught) {
      setError(apiErrorMessage(caught, tcode));
    }
  }

  return (
    <Panel className="flex flex-col gap-4">
      <h2 className="text-h3">{t('editStudent')}</h2>
      <form className="flex flex-col gap-4" onSubmit={(e) => void save(e)}>
        <Field label={t('firstName')}>
          <Input value={firstName} onChange={(e) => setFirstName(e.target.value)} />
        </Field>
        <Field label={t('lastName')}>
          <Input value={lastName} onChange={(e) => setLastName(e.target.value)} />
        </Field>
        <Field label={t('uid')} help={t('uidLocked')}>
          <Input value={student.uid} readOnly disabled />
        </Field>
        {error ? <p className="text-body-s text-danger-600">{error}</p> : null}
        <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
          <Button variant="danger" type="button" onClick={() => setConfirming(true)}>
            {t('delete')}
          </Button>
          <span className="flex-1" />
          <Button variant="ghost" type="button" onClick={onDone}>
            {tc('cancel')}
          </Button>
          <Button variant="primary" type="submit" disabled={update.isPending}>
            {tc('save')}
          </Button>
        </div>
      </form>

      <ConfirmDestructive
        open={confirming}
        onOpenChange={setConfirming}
        title={t('deleteStudent', { name })}
        description={t('deleteBody', { name, uid: student.uid })}
        alternative={
          <div className="rounded-md border border-line bg-surface-2 p-4">
            <p className="text-body-s font-semibold">{t('unenrolInstead')}</p>
            <p className="text-body-s text-ink-500">{t('unenrolBody')}</p>
          </div>
        }
        confirmWith={student.uid}
        confirmWithLabel={t('typeUid', { uid: student.uid })}
        cancelLabel={tc('cancel')}
        confirmLabel={t('deleteConfirm')}
        closeLabel={tc('close')}
        pending={remove.isPending}
        error={error}
        onConfirm={() => {
          setError(null);
          remove.mutate(
            { studentId: student.id, classId, confirm: student.uid },
            {
              onSuccess: () => {
                setConfirming(false);
                onDone();
              },
              onError: (caught) => setError(apiErrorMessage(caught, tcode)),
            },
          );
        }}
      />
    </Panel>
  );
}
