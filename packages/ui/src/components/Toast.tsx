import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { cx } from '../lib/cx';
import { IconCross } from '../icons/set';

export type ToastVariant = 'default' | 'success' | 'warn' | 'danger';

export interface ToastOptions {
  /** The message. Required — a toast with no text says nothing. */
  title: ReactNode;
  description?: ReactNode;
  variant?: ToastVariant;
  /** ms before it leaves; 0 keeps it until dismissed. */
  duration?: number;
  action?: { label: string; onClick: () => void };
  /** Overrides the provider's dismiss label for this one toast. */
  dismissLabel?: string;
}

export interface ToastRecord extends ToastOptions {
  id: string;
}

interface ToastApi {
  toast: (options: ToastOptions) => string;
  dismiss: (id: string) => void;
  dismissAll: () => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

export interface ToastProviderProps {
  children: ReactNode;
  /** Accessible name of the live region — the app supplies the string. */
  regionLabel: string;
  /** Default accessible name of every dismiss control. */
  dismissLabel: string;
  /** Default lifetime, ms. */
  defaultDuration?: number;
  /** Cap on simultaneous toasts; the oldest leaves first. */
  max?: number;
}

const DOT: Record<ToastVariant, string> = {
  default: 'bg-primary-500',
  success: 'bg-success-500',
  warn: 'bg-warn-500',
  danger: 'bg-danger-500',
};

let counter = 0;

/**
 * Toasts. The live region is polite and always mounted, so the first message
 * of a session is announced too. The toast is the one place ink becomes the
 * background (DESIGN.md §6).
 */
export function ToastProvider({
  children,
  regionLabel,
  dismissLabel,
  defaultDuration = 6000,
  max = 3,
}: ToastProviderProps) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const dismissAll = useCallback(() => {
    timers.current.forEach((timer) => clearTimeout(timer));
    timers.current.clear();
    setToasts([]);
  }, []);

  const toast = useCallback(
    (options: ToastOptions) => {
      counter += 1;
      const id = `ard-toast-${counter}`;
      setToasts((current) => [...current, { ...options, id }].slice(-max));
      const duration = options.duration ?? defaultDuration;
      if (duration > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), duration),
        );
      }
      return id;
    },
    [defaultDuration, dismiss, max],
  );

  const timersRef = timers;
  useEffect(
    () => () => {
      timersRef.current.forEach((timer) => clearTimeout(timer));
      timersRef.current.clear();
    },
    [timersRef],
  );

  const api = useMemo<ToastApi>(() => ({ toast, dismiss, dismissAll }), [toast, dismiss, dismissAll]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        role="region"
        aria-label={regionLabel}
        aria-live="polite"
        aria-atomic="false"
        className={cx(
          'pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4',
          'pb-[max(1rem,env(safe-area-inset-bottom))]',
          'sm:inset-x-auto sm:right-4 sm:bottom-4 sm:items-end',
        )}
      >
        {toasts.map((t) => (
          <Toast key={t.id} toast={t} onDismiss={dismiss} dismissLabel={t.dismissLabel ?? dismissLabel} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export interface ToastProps {
  toast: ToastRecord;
  onDismiss: (id: string) => void;
  dismissLabel: string;
}

/** One toast. Exported so a story or a test can render it standalone. */
export function Toast({ toast, onDismiss, dismissLabel }: ToastProps) {
  const variant = toast.variant ?? 'default';
  return (
    <div
      className={cx('anim-toast ard-toast pointer-events-auto w-full max-w-sm')}
      data-variant={variant}
    >
      <span aria-hidden="true" className={cx('h-2.5 w-2.5 shrink-0 rounded-pill', DOT[variant])} />
      <div className="flex-1 text-body-s">
        <p className="font-bold text-canvas">{toast.title}</p>
        {toast.description ? <p className="text-canvas/80">{toast.description}</p> : null}
      </div>
      {toast.action ? (
        <button
          type="button"
          onClick={() => {
            toast.action?.onClick();
            onDismiss(toast.id);
          }}
          className="min-h-11 rounded-md px-3 font-display font-semibold text-canvas underline underline-offset-2"
        >
          {toast.action.label}
        </button>
      ) : null}
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label={dismissLabel}
        className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-canvas"
      >
        <IconCross size={18} />
      </button>
    </div>
  );
}
