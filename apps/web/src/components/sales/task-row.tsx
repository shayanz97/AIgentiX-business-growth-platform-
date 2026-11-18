"use client";

import Link from "next/link";
import { useState } from "react";

import { control } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert, Badge } from "@/components/ui/surface";
import { api, errorMessage, type SalesTask } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { fromLocalInput, toLocalInput } from "@/lib/sales";

export function TaskRow({
  task,
  assigneeName,
  showDeal,
  onChanged,
}: {
  task: SalesTask;
  assigneeName: string;
  showDeal: boolean;
  onChanged: () => void;
}) {
  const [rescheduling, setRescheduling] = useState(false);
  const [due, setDue] = useState(toLocalInput(task.due_at));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = task.status === "open";

  async function update(body: { status?: "completed"; due_at?: string }, failure: string) {
    setPending(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.PATCH("/api/v1/sales/tasks/{task_id}", { params: { path: { task_id: task.id } }, body });
      if (!data) setError(errorMessage(apiError, failure));
      else {
        setRescheduling(false);
        onChanged();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  function reschedule(e: React.FormEvent) {
    e.preventDefault();
    const iso = fromLocalInput(due);
    if (!iso) return setError("Choose a due date and time.");
    void update({ due_at: iso }, "Could not reschedule the task.");
  }

  return (
    <li className="space-y-2 px-4 py-3 text-sm" data-testid="task-row">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium text-slate-100">{task.title}</p>
          <p className="text-xs text-slate-400">
            Due {formatDate(task.due_at)} · {assigneeName}
            {showDeal ? (
              <>
                {" · "}
                <Link href={`/sales/opportunities/${task.sales_opportunity_id}`} className="text-accent hover:underline">
                  {task.deal_title}
                </Link>
                {task.company_name ? ` (${task.company_name})` : ""}
              </>
            ) : null}
          </p>
          {task.description ? <p className="mt-1 whitespace-pre-wrap text-slate-300">{task.description}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {task.overdue && open ? <Badge tone="danger">Overdue</Badge> : null}
          {!open ? <Badge tone="muted">{task.status === "completed" ? "Completed" : "Cancelled"}</Badge> : null}
          {open ? (
            <>
              <Button variant="secondary" aria-label={`Complete ${task.title}`} disabled={pending} onClick={() => void update({ status: "completed" }, "Could not complete the task.")}>
                Complete
              </Button>
              <Button variant="ghost" aria-label={`Reschedule ${task.title}`} aria-expanded={rescheduling} onClick={() => setRescheduling((v) => !v)}>
                Reschedule
              </Button>
            </>
          ) : null}
        </div>
      </div>
      {rescheduling ? (
        <form onSubmit={reschedule} className="flex flex-wrap items-end gap-2" aria-label={`Reschedule ${task.title}`}>
          <label className="block text-xs text-slate-400">
            <span className="mb-1 block">New due date and time</span>
            <input type="datetime-local" className={control} value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
          <Button type="submit" disabled={pending}>
            Save date
          </Button>
        </form>
      ) : null}
      {error ? <Alert>{error}</Alert> : null}
    </li>
  );
}
