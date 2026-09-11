'use client';

import { Button, Card, Field, Input } from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { apiErrorMessage } from '@/lib/api/error-message';
import { useChangePassword } from '@/lib/api/queries';

/** Mirrors `PasswordChangeRequest.new_password` in `alppy/schemas`. Checked
 *  here so a teacher is told before the round trip, and there so it is true. */
const MIN_LENGTH = 12;

/**
 * A teacher changing their own password (D12).
 *
 * The only account operation a teacher can perform for themselves, and until
 * now there was no way to do it at all: no endpoint, no screen, and no e-mail
 * transport for a reset link. A teacher handed a generated password when their
 * school was set up had no way to replace it, which is the state that turns one
 * printed slip of paper into the credential for a roster of children.
 *
 * Three fields rather than two. The confirmation exists because a mistyped new
 * password is not recoverable by the person who mistyped it — there is no
 * reset — so the cost of the extra field is a few seconds and the cost of
 * omitting it is a support call at 08:10.
 *
 * The current password is asked for even though they are signed in, and the
 * screen says why: a session is what an unlocked laptop in a staffroom hands to
 * whoever sits down next, and this is the one thing that person does not have.
 */
export function PasswordSettings() {
  const t = useTranslations('settings');
  const tc = useTranslations('common');
  const tcode = useTranslations('errors.code');
  const changePassword = useChangePassword();

  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const tooShort = next.length > 0 && next.length < MIN_LENGTH;
  const mismatch = confirm.length > 0 && confirm !== next;
  const ready =
    current.length > 0 && next.length >= MIN_LENGTH && confirm === next && !changePassword.isPending;

  function submit() {
    setError(null);
    setDone(false);
    changePassword.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setDone(true);
          // Never leave a password sitting in a form on a classroom machine.
          setCurrent('');
          setNext('');
          setConfirm('');
        },
        onError: (caught) => setError(apiErrorMessage(caught, tcode)),
      },
    );
  }

  return (
    <Card className="flex flex-col gap-4">
      <div>
        <h2 className="text-h3">{t('password')}</h2>
        <p className="mt-1 max-w-prose text-body-s text-ink-700">{t('passwordHelp')}</p>
      </div>

      {/* `autoComplete` values are the ones password managers look for. Without
          them a manager offers to save the CURRENT password as the new one. */}
      <Field label={t('currentPassword')} help={t('currentPasswordHelp')}>
        <Input
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
      </Field>

      <Field
        label={t('newPassword')}
        help={t('newPasswordHelp', { count: MIN_LENGTH })}
        error={tooShort ? t('newPasswordTooShort', { count: MIN_LENGTH }) : undefined}
      >
        <Input
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
      </Field>

      <Field
        label={t('confirmPassword')}
        error={mismatch ? t('confirmPasswordMismatch') : undefined}
      >
        <Input
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
      </Field>

      {/* Said on the screen, not only in a docstring: a teacher changing a
          password because somebody else knows it expects the opposite, and the
          cookie carries no password so there is nothing to invalidate. */}
      <p className="max-w-prose text-body-s text-ink-700">{t('passwordSessionsNote')}</p>

      <div className="flex items-center justify-end gap-4 border-t border-line pt-4">
        {done ? (
          <p role="status" className="text-body-s text-success-600">
            {t('passwordChanged')}
          </p>
        ) : null}
        <Button
          variant="primary"
          disabled={!ready}
          loading={changePassword.isPending}
          busyLabel={tc('saving')}
          onClick={submit}
        >
          {t('changePassword')}
        </Button>
      </div>

      {error ? (
        <p role="alert" className="text-body-s text-danger-600">
          {error}
        </p>
      ) : null}
    </Card>
  );
}
