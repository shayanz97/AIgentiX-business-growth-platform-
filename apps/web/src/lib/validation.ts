import { z } from "zod";

// Client-side validation mirrors the backend constraints for fast feedback.
// The backend remains the source of truth and re-validates everything.

export const loginSchema = z.object({
  email: z.email("Enter a valid e-mail address"),
  password: z.string().min(1, "Enter your password"),
});

export const projectSchema = z.object({
  name: z.string().trim().min(1, "Project name is required").max(200, "Keep the name under 200 characters"),
  description: z.string().trim().max(5000, "Keep the description under 5000 characters"),
  target_url: z
    .string()
    .trim()
    .max(2048)
    .refine((v) => v === "" || /^https?:\/\/[^\s]+\.[^\s]+/i.test(v), "Enter a full URL starting with https://"),
});

export const organizationSchema = z.object({
  name: z.string().trim().min(2, "Use at least 2 characters").max(200),
});

export type FieldErrors<T> = Partial<Record<keyof T, string>>;

export function fieldErrors<T>(error: z.ZodError<T>): FieldErrors<T> {
  const out: FieldErrors<T> = {};
  for (const issue of error.issues) {
    const key = issue.path[0] as keyof T | undefined;
    if (key !== undefined && out[key] === undefined) out[key] = issue.message;
  }
  return out;
}
