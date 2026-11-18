"use client";

import { useState } from "react";

import { TaskRow } from "@/components/sales/task-row";
import { control, labelText } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage, type Member, type TaskSuggestion } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { browserTimeZone, fromLocalInput, toLocalInput } from "@/lib/sales";
import { useApi } from "@/lib/use-api";

/** Follow-up tasks of one deal, plus suggestions that only become tasks when a person clicks "Create task". */
export function DealTasksPanel({
  dealId,
  members,
  nameOf,
  closed,
  onChanged,
}: {
  dealId: string;
  members: Member[];
  nameOf: (id: string | null | undefined) => string;
  closed: boolean;
  onChanged: () => void;
}) {
  const tz = browserTimeZone();
  const tasks = useApi(
    () => api.GET("/api/v1/sales/tasks", { params: { query: { sales_opportunity_id: dealId, view: "all", tz, limit: 100 } } }),
    [dealId, tz],
  );
  const suggestions = useApi(() => api.GET("/api/v1/sales/opportunities/{deal_id}/task-suggestions", { params: { path: { deal_id: dealId } } }), [dealId]);
  const [error, setError] = useState<string | null>(null);

  function changed() {
    tasks.reload();
    suggestions.reload();
    onChanged();
  }

  async function createFromSuggestion(s: TaskSuggestion) {
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/sales/tasks", {
        body: { sales_opportunity_id: dealId, title: s.title, description: s.reason, due_at: s.suggested_due_at, suggestion_key: s.key },
      });
      if (!data) setError(errorMessage(apiError, "Could not create the task."));
      else changed();
    } catch {
      setError("Cannot reach the server. Please try again.");
    }
  }

  const items = tasks.data?.items ?? [];

  return (
    <section aria-labelledby="deal-tasks" className="space-y-3">
      <h2 id="deal-tasks" className="text-lg font-medium text-white">
        Follow-up tasks
      </h2>
      {error ? <Alert>{error}</Alert> : null}
      {tasks.error && !tasks.data ? <Alert>{tasks.error}</Alert> : null}
      {tasks.data && items.length === 0 ? <p className="text-sm text-slate-400">No tasks for this opportunity yet.</p> : null}
      {items.length > 0 ? (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-navy-900/70" aria-label="Opportunity tasks">
          {items.map((t) => (
            <TaskRow key={t.id} task={t} assigneeName={nameOf(t.assigned_user_id)} showDeal={false} onChanged={changed} />
          ))}
        </ul>
      ) : null}

      {!closed ? <CreateTaskForm dealId={dealId} members={members} onCreated={changed} /> : null}

      {suggestions.data && suggestions.data.length > 0 && !closed ? (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-slate-200">Suggested follow-ups</h3>
          <p className="text-xs text-slate-400">Suggestions come from rules on recorded facts. Nothing is created until you choose to.</p>
          <ul className="space-y-2" aria-label="Task suggestions">
            {suggestions.data.map((s) => (
              <li key={s.key} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-navy-900/70 px-4 py-3 text-sm">
                <div className="min-w-0">
                  <p className="font-medium text-slate-100">{s.title}</p>
                  <p className="text-xs text-slate-400">
                    {s.reason} · suggested for {formatDate(s.suggested_due_at)}
                  </p>
                </div>
                <Button variant="secondary" aria-label={`Create task: ${s.title}`} onClick={() => void createFromSuggestion(s)}>
                  Create task
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function CreateTaskForm({ dealId, members, onCreated }: { dealId: string; members: Member[]; onCreated: () => void }) {
  const [title, setTitle] = useState("");
  const [due, setDue] = useState(() => toLocalInput(new Date(Date.now() + 24 * 3600 * 1000)));
  const [assignee, setAssignee] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const iso = fromLocalInput(due);
    if (!title.trim()) return setError("Enter a task title.");
    if (!iso) return setError("Choose a due date and time.");
    setPending(true);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/sales/tasks", {
        body: { sales_opportunity_id: dealId, title: title.trim(), due_at: iso, assigned_user_id: assignee || null },
      });
      if (!data) setError(errorMessage(apiError, "Could not create the task."));
      else {
        setTitle("");
        onCreated();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Create follow-up task" className="grid gap-3 rounded-lg border border-line bg-navy-900/70 p-4 sm:grid-cols-2">
      <label className="block sm:col-span-2">
        <span className={labelText}>Task</span>
        <input className={control} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Due</span>
        <input type="datetime-local" className={control} value={due} onChange={(e) => setDue(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Assignee</span>
        <select className={control} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
          <option value="">Unassigned</option>
          {members.map((m) => (
            <option key={m.user.id} value={m.user.id}>
              {m.user.full_name || m.user.email}
            </option>
          ))}
        </select>
      </label>
      <div className="space-y-2 sm:col-span-2">
        {error ? <Alert>{error}</Alert> : null}
        <Button type="submit" disabled={pending}>
          {pending ? "Creating…" : "Create task"}
        </Button>
      </div>
    </form>
  );
}
