import { useId, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { cn } from "./cn";

const control =
  "block w-full rounded-md border bg-navy-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 " +
  "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30";

type FieldProps = { label: string; error?: string; hint?: string };

export function TextField({ label, error, hint, className, ...props }: FieldProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-slate-200">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(control, error ? "border-red-400" : "border-line")}
        {...props}
      />
      <FieldMessage id={id} error={error} hint={hint} />
    </div>
  );
}

export function TextAreaField({
  label,
  error,
  hint,
  className,
  ...props
}: FieldProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-slate-200">
        {label}
      </label>
      <textarea
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(control, "min-h-28", error ? "border-red-400" : "border-line")}
        {...props}
      />
      <FieldMessage id={id} error={error} hint={hint} />
    </div>
  );
}

function FieldMessage({ id, error, hint }: { id: string; error?: string; hint?: string }) {
  if (error)
    return (
      <p id={`${id}-error`} className="mt-1.5 text-xs text-red-300">
        {error}
      </p>
    );
  if (hint)
    return (
      <p id={`${id}-hint`} className="mt-1.5 text-xs text-slate-400">
        {hint}
      </p>
    );
  return null;
}
