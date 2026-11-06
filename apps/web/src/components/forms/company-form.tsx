"use client";

import { useState, type FormEvent } from "react";

import { ProjectSelect } from "@/components/research/project-select";
import { Button, ButtonLink } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage, type Company } from "@/lib/api";
import { companyCreateSchema, fieldErrors, type FieldErrors } from "@/lib/validation";

type Values = { website: string; name: string };

export function CompanyForm({
  initialProjectId = "",
  onCreated,
}: {
  initialProjectId?: string;
  onCreated: (company: Company, created: boolean) => void;
}) {
  const [projectId, setProjectId] = useState(initialProjectId);
  const [errors, setErrors] = useState<FieldErrors<Values>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const parsed = companyCreateSchema.safeParse({ website: form.get("website") ?? "", name: form.get("name") ?? "" });
    setFormError(null);
    if (!parsed.success) {
      setErrors(fieldErrors(parsed.error));
      return;
    }
    setErrors({});
    setPending(true);
    try {
      const { website, name } = parsed.data;
      const { data, error } = await api.POST("/api/v1/companies", {
        body: { website_url: website, name: name || null, project_id: projectId || null },
      });
      if (!data) {
        setFormError(errorMessage(error, "Could not add the company."));
        return;
      }
      onCreated(data.company, data.created);
    } catch {
      setFormError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-6">
      {formError ? <Alert>{formError}</Alert> : null}
      <TextField
        label="Company website"
        name="website"
        inputMode="url"
        autoComplete="off"
        required
        placeholder="example.com or https://example.com"
        error={errors.website}
        hint="Public websites only. If the company is already in your workspace it will not be duplicated."
      />
      <TextField label="Company name" name="name" maxLength={200} error={errors.name} hint="Optional. Detected from the website when left empty." />
      <ProjectSelect value={projectId} onChange={setProjectId} />
      <div className="flex gap-3">
        <Button type="submit" disabled={pending}>
          {pending ? "Adding…" : "Add company"}
        </Button>
        <ButtonLink href="/companies" variant="ghost">
          Cancel
        </ButtonLink>
      </div>
    </form>
  );
}
