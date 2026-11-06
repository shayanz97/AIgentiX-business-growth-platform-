"use client";

import { useId } from "react";

import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";

/** Optional "add to project" select shared by the single-company form and the CSV import. */
export function ProjectSelect({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const id = useId();
  const { data } = useApi(() => api.GET("/api/v1/projects", { params: { query: { limit: 100 } } }), []);
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-slate-200">
        Project (optional)
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="block w-full rounded-md border border-line bg-navy-900 px-3 py-2 text-sm text-slate-100 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
      >
        <option value="">No project</option>
        {data?.items.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </div>
  );
}
