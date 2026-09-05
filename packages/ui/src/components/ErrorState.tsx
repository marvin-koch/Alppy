import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';
import { IconWarning } from '../icons/set';

export interface ErrorStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title: ReactNode;
  description?: ReactNode;
  /**
   * Technical detail the teacher can quote in a support message. Rendered as
   * data (`[data-transcription]` → mono) because that is what it is.
   */
  details?: string;
  action?: ReactNode;
  secondaryAction?: ReactNode;
  /** Announce on mount. Turn off when several errors render at once. */
  announce?: boolean;
}

/** Every screen ships one. Colour is never the message: the icon and the text are. */
export const ErrorState = forwardRef<HTMLDivElement, ErrorStateProps>(function ErrorState(
  { title, description, details, action, secondaryAction, announce = true, className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      role={announce ? 'alert' : undefined}
      className={cx('flex flex-col items-center gap-3 px-4 py-10 text-center sm:py-14', className)}
      {...rest}
    >
      <span
        aria-hidden="true"
        className="inline-flex h-14 w-14 items-center justify-center rounded-pill bg-danger-100 text-danger-600"
      >
        <IconWarning size={28} />
      </span>
      <h3 className="font-display text-h2 font-bold text-ink-900">{title}</h3>
      {description ? <p className="max-w-prose text-body text-ink-700">{description}</p> : null}
      {details ? (
        <pre
          data-transcription=""
          className="ard-panel max-w-full overflow-x-auto text-left text-body-s whitespace-pre-wrap"
        >
          {details}
        </pre>
      ) : null}
      {children}
      {action || secondaryAction ? (
        <div className="mt-2 flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:justify-center">
          {action}
          {secondaryAction}
        </div>
      ) : null}
    </div>
  );
});
