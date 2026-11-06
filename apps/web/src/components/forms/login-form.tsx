"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage } from "@/lib/api";
import { fieldErrors, loginSchema, type FieldErrors } from "@/lib/validation";

type Values = { email: string; password: string };

export function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const [errors, setErrors] = useState<FieldErrors<Values>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const parsed = loginSchema.safeParse({ email: form.get("email"), password: form.get("password") });
    setFormError(null);
    if (!parsed.success) {
      setErrors(fieldErrors(parsed.error));
      return;
    }
    setErrors({});
    setPending(true);
    try {
      const { error, response } = await api.POST("/api/v1/auth/login", { body: parsed.data });
      if (error || !response.ok) {
        setFormError(response.status === 401 ? "Invalid e-mail or password." : errorMessage(error));
        return;
      }
      onSuccess();
    } catch {
      setFormError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      {formError ? <Alert>{formError}</Alert> : null}
      <TextField label="E-mail" name="email" type="email" autoComplete="email" required error={errors.email} />
      <TextField
        label="Password"
        name="password"
        type="password"
        autoComplete="current-password"
        required
        error={errors.password}
      />
      <Button type="submit" className="w-full" disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
