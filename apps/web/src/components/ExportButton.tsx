'use client';

import { Button } from '@alppy/ui';
import { useState } from 'react';

import { apiErrorMessage } from '@/lib/api/error-message';
import { downloadJson, exportFilename } from '@/lib/download';

interface ExportButtonProps {
  /** Fetches the document. Not a URL: the export is an authenticated read. */
  fetcher: () => Promise<unknown>;
  /** What the file is of — `7B`, or a pupil's name. Becomes the filename. */
  subject: string;
  label: string;
  busyLabel: string;
  /** The `errors.code` namespace, so this stays free of `useTranslations`. */
  translateError: (key: string, values?: Record<string, string | number>) => string;
  variant?: 'secondary' | 'ghost';
}

/**
 * Download an export as a file (D36).
 *
 * Both export routes existed and **neither was reachable from the product** —
 * `exportStudent` had been in the API client since it was written and nothing
 * ever called it. So the data-portability promise in `docs/privacy.md` §4 was
 * kept by a teacher constructing a URL by hand, which is to say it was not
 * kept: a parent asking what is held about their child, or a school taking its
 * data elsewhere, both ended at "ask whoever runs the server".
 *
 * A button and not a link, because the export is an authenticated read through
 * the normal client. A plain `<a href>` would work — the session cookie is sent
 * — and would open a megabyte of JSON in a tab instead of saving it.
 *
 * No loading state beyond the button's own: a class export is one request, and
 * a spinner over the roster would imply the roster was reloading.
 */
export function ExportButton({
  fetcher,
  subject,
  label,
  busyLabel,
  translateError,
  variant = 'secondary',
}: ExportButtonProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      downloadJson(await fetcher(), exportFilename(subject));
    } catch (caught) {
      setError(apiErrorMessage(caught, translateError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-col items-end gap-1">
      <Button
        variant={variant}
        type="button"
        loading={busy}
        busyLabel={busyLabel}
        onClick={() => void run()}
      >
        {label}
      </Button>
      {error ? (
        <span role="alert" className="text-body-s text-danger-600">
          {error}
        </span>
      ) : null}
    </span>
  );
}
