"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { Alert } from "@/components/ui/surface";
import { errorMessage } from "@/lib/api";
import { fieldErrors, organizationSchema } from "@/lib/validation";

/** Single-field organization name form used for both "create" and "rename". */
export function OrganizationNameForm({
  label,
  submitLabel,
  defaultValue = "",
  onSubmit,
}: {
  label: string;
  submitLabel: string;
  defaultValue?: string;
  onSubmit: (name: string) => Promise<{ error?: unknown; ok: boolean }>;
}) {
  const [error, setError] = useState<string | undefined>();
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formEl = event.currentTarget;
    const parsed = organizationSchema.safeParse({ name: new FormData(formEl).get("name") ?? "" });
    setFormError(null);
    if (!parsed.success) {
      setError(fieldErrors(parsed.error).name);
      return;
    }
    setError(undefined);
    setPending(true);
    try {
      const result = await onSubmit(parsed.data.name);
      if (!result.ok) setFormError(errorMessage(result.error));
      else if (!defaultValue) formEl.reset();
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      {formError ? <Alert>{formError}</Alert> : null}
      <TextField label={label} name="name" defaultValue={defaultValue} error={error} required maxLength={200} />
      <Button type="submit" variant="secondary" disabled={pending}>
        {pending ? "Saving…" : submitLabel}
      </Button>
    </form>
  );
}
