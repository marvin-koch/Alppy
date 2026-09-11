'use client';

import { Card, Field, SegmentedControl, Toggle } from '@alppy/ui';
import { useLocale, useTranslations } from 'next-intl';

import { PasswordSettings } from '@/components/PasswordSettings';
import { SchoolSettings } from '@/components/SchoolSettings';
import { useEffect, useState } from 'react';

import { useRouter, usePathname } from '@/i18n/navigation';
import { useUpdatePreferences } from '@/lib/api/queries';
import { applyDisplay, defaultDisplay, readDisplay, type DisplayPrefs } from '@/lib/display';
import { locales, type AppLocale } from '@/i18n/routing';

export default function SettingsPage() {
  const t = useTranslations('settings');
  const td = useTranslations('discreet');
  const router = useRouter();
  const pathname = usePathname();
  const locale = useLocale() as AppLocale;
  const updatePrefs = useUpdatePreferences();

  const [prefs, setPrefs] = useState<DisplayPrefs | null>(null);

  // Read once on the client: the server render has no access to localStorage,
  // and ThemeScript has already applied the attributes before paint.
  useEffect(() => setPrefs(readDisplay()), []);

  function update(patch: Partial<DisplayPrefs>) {
    const next = { ...(prefs ?? readDisplay()), ...patch };
    setPrefs(next);
    applyDisplay(next);
    // Persist server-side too, so the choice follows the teacher to the
    // staffroom machine. A failure here is not worth interrupting them for:
    // the local setting has already taken effect.
    updatePrefs.mutate({ locale, ...next });
  }

  const current = prefs ?? defaultDisplay;

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6">{t('title')}</h1>

      {/* The school's own nouns, above the display switches: renaming a
          Branch is rarer than changing a theme, but it is the only place it
          can be done at all. */}
      <div className="mb-8">
        <SchoolSettings />
      </div>

      {/* The account, below the school and above the display switches. Rarer
          than a theme change and more consequential than either: a teacher
          handed a generated password when their school was set up had no way
          to replace it at all before this (D12). */}
      <div className="mb-8">
        <PasswordSettings />
      </div>

      <Card className="mb-4">
        <h2 className="mb-4 text-h3">{t('language')}</h2>
        <Field label={t('language')} help={t('languageHelp')} hideLabel>
          <SegmentedControl
            value={locale}
            onValueChange={(next) => {
              const chosen = next as AppLocale;
              // Persist the LANGUAGE too. This handler only did the route
              // replace, so `TeacherPreferences.locale` was written solely as a
              // side effect of later touching a display toggle, and a teacher's
              // language never followed them to another machine.
              updatePrefs.mutate({ locale: chosen, ...(prefs ?? readDisplay()) });
              router.replace(pathname, { locale: chosen });
            }}
            options={locales.map((l) => ({
              value: l,
              label: l.toUpperCase(),
            }))}
            label={t('language')}
          />
        </Field>
      </Card>

      <Card>
        <h2 className="mb-4 text-h3">{t('appearance')}</h2>

        <div className="flex flex-col gap-6">
          <Field label={t('theme')}>
            <SegmentedControl
              value={current.theme ?? 'system'}
              onValueChange={(v) =>
                update({ theme: v === 'system' ? null : (v as 'light' | 'dark') })
              }
              options={[
                { value: 'system', label: t('themeSystem') },
                { value: 'light', label: t('themeLight') },
                { value: 'dark', label: t('themeDark') },
              ]}
              label={t('theme')}
            />
          </Field>

          <Toggle
            label={t('contrast')}
            description={t('contrastHelp')}
            checked={current.contrast === 'high'}
            onCheckedChange={(on) => update({ contrast: on ? 'high' : null })}
          />

          <Toggle
            label={t('motion')}
            description={t('motionHelp')}
            checked={current.motion === 'off'}
            onCheckedChange={(on) => update({ motion: on ? 'off' : null })}
          />

          <Toggle
            label={t('calm')}
            description={t('calmHelp')}
            checked={current.calm === 'on'}
            onCheckedChange={(on) => update({ calm: on ? 'on' : null })}
          />

          {/* The one display switch that is about the room rather than the
              reader. The shortcut is named here because the moment you need
              this setting is the moment you cannot go looking for it. */}
          <Toggle
            label={td('title')}
            description={`${td('help')} (${td('shortcutHint')})`}
            checked={current.discreet === 'on'}
            onCheckedChange={(on) => update({ discreet: on ? 'on' : null })}
          />
        </div>

        {updatePrefs.isSuccess ? (
          <p className="mt-4 text-body-s text-ink-500" role="status">
            {t('saved')}
          </p>
        ) : null}
      </Card>
    </div>
  );
}
