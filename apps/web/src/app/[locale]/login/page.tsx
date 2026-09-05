'use client';

import { AlppyLogo, Button, Card, Field, Input } from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState, type FormEvent } from 'react';

import { useRouter } from '@/i18n/navigation';
import { useLogin } from '@/lib/api/queries';

export default function LoginPage() {
  const t = useTranslations('auth');
  const router = useRouter();
  const login = useLogin();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    login.mutate(
      { email, password },
      { onSuccess: () => router.push('/') },
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-4">
      <Card className="w-full max-w-sm">
        <div className="mb-6 flex justify-center">
          <AlppyLogo size="lg" />
        </div>
        <h1 className="mb-6 text-center text-h2">{t('signIn')}</h1>

        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <Field label={t('email')} required requiredLabel={t('email')}>
            <Input
              type="email"
              name="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </Field>

          <Field
            label={t('password')}
            required
            requiredLabel={t('password')}
            // The error lives on the password field but describes the pair:
            // never say which half was wrong.
            error={login.isError ? t('invalidCredentials') : undefined}
          >
            <Input
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>

          <Button
            type="submit"
            variant="primary"
            block
            loading={login.isPending}
            busyLabel={t('signingIn')}
          >
            {t('signIn')}
          </Button>
        </form>
      </Card>
    </div>
  );
}
