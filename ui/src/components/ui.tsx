import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { useEffect, useId } from "react";

function cx(...parts: (string | false | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "default" | "primary" | "danger" | "outline-danger" | "ghost";

export function Button({
  variant = "default",
  large,
  className,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; large?: boolean }) {
  const modifier = variant === "default" ? undefined : `btn--${variant}`;
  return <button type={type} className={cx("btn", modifier, large && "btn--large", className)} {...props} />;
}

export type Tone = "ok" | "warn" | "error" | "active" | "neutral";

/** Pastille d'état : la couleur ne porte jamais seule l'information, le texte la dit. */
export function Pill({
  tone = "neutral",
  emphasis,
  children,
}: {
  tone?: Tone;
  emphasis?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={cx("pill", emphasis && "pill--emphasis")}>
      {tone !== "neutral" && <span className={`dot dot--${tone}`} aria-hidden="true" />}
      {children}
    </span>
  );
}

export function Card({
  active,
  onClick,
  children,
  label,
}: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
  label?: string;
}) {
  const className = cx("card", active && "card--active");
  if (onClick) {
    return (
      <button type="button" className={className} onClick={onClick} aria-label={label}>
        {children}
      </button>
    );
  }
  return (
    <div className={className} aria-label={label}>
      {children}
    </div>
  );
}

export function Field({
  label,
  hint,
  error,
  ...input
}: { label: string; hint?: string; error?: string } & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ");
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="input"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        {...input}
      />
      {hint && (
        <span id={`${id}-hint`} className="field__hint">
          {hint}
        </span>
      )}
      {error && (
        <span id={`${id}-error`} className="field__error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

/** Barre de progression ; `ratio` absent = scénario « en continu » (sans limite de durée). */
export function Progress({ ratio, label }: { ratio?: number; label: string }) {
  if (ratio === undefined) {
    return (
      <div className="progress progress--continuous" role="img" aria-label={`${label} : en continu`}>
        <div className="progress__bar" />
      </div>
    );
  }
  const percent = Math.round(Math.min(1, Math.max(0, ratio)) * 100);
  return (
    <div
      className="progress"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
    >
      <div className="progress__bar" style={{ width: `${percent}%` }} />
    </div>
  );
}

function describedBy(id: string, hint?: string, error?: string): string | undefined {
  return [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
}

export function SelectField({
  label,
  hint,
  error,
  children,
  ...select
}: { label: string; hint?: string; error?: string } & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId();
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className="input"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        {...select}
      >
        {children}
      </select>
      {hint && (
        <span id={`${id}-hint`} className="field__hint">
          {hint}
        </span>
      )}
      {error && (
        <span id={`${id}-error`} className="field__error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function CheckField({
  label,
  hint,
  ...input
}: { label: string; hint?: string } & Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const id = useId();
  return (
    <div className="field field--check">
      <input id={id} type="checkbox" aria-describedby={hint ? `${id}-hint` : undefined} {...input} />
      <label htmlFor={id}>{label}</label>
      {hint && (
        <span id={`${id}-hint`} className="field__hint">
          {hint}
        </span>
      )}
    </div>
  );
}

/** Fenêtre modale : Échap la ferme, le titre la nomme pour les lecteurs d'écran. */
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const titleId = useId();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h2 id={titleId} className="modal__title">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
