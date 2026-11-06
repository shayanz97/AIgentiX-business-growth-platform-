"use client";

import { useState, type FormEvent } from "react";

import { Button, ButtonLink } from "@/components/ui/button";
import { TextAreaField, TextField } from "@/components/ui/field";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage, type Project } from "@/lib/api";
import { fieldErrors, projectSchema, type FieldErrors } from "@/lib/validation";

type Values = { name: string; description: string; target_url: string };

export function ProjectForm({ onCreated }: { onCreated: (project: Project) => void }) {
  const [errors, setErrors] = useState<FieldErrors<Values>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const parsed = projectSchema.safeParse({
      name: form.get("name") ?? "",
      description: form.get("description") ?? "",
      target_url: form.get("target_url") ?? "",
    });
    setFormError(null);
    if (!parsed.success) {
      setErrors(fieldErrors(parsed.error));
      return;
    }
    setErrors({});
    setPending(true);
    try {
      const { name, description, target_url } = parsed.data;
      const { data, error } = await api.POST("/api/v1/projects", {
        body: { name, description, target_url: target_url || null },
      });
      if (!data) {
        setFormError(errorMessage(error, "Could not create the project."));
        return;
      }
      onCreated(data);
    } catch {
      setFormError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-6">
      {formError ? <Alert>{formError}</Alert> : null}
      <TextField label="Project name" name="name" required maxLength={200} error={errors.name} placeholder="e.g. Acme Robotics expansion" />
      <TextField
        label="Company website"
        name="target_url"
        type="url"
        inputMode="url"
        placeholder="https://example.com"
        error={errors.target_url}
        hint="Optional. Automated research of this site arrives in a later release."
      />
      <TextAreaField label="Notes" name="description" maxLength={5000} error={errors.description} />
      <div className="flex gap-3">
        <Button type="submit" disabled={pending}>
          {pending ? "Creating…" : "Create project"}
        </Button>
        <ButtonLink href="/projects" variant="ghost">
          Cancel
        </ButtonLink>
      </div>
    </form>
  );
}
