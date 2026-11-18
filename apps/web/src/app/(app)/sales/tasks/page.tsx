"use client";

import { useState } from "react";

import { ExportCsvButton } from "@/components/sales/export-button";
import { TaskRow } from "@/components/sales/task-row";
import { cn } from "@/components/ui/cn";
import { RequireOrganization } from "@/components/require-organization";
import { Alert, EmptyState, PageHeader } from "@/components/ui/surface";
import { api } from "@/lib/api";
import { browserTimeZone, taskQuery, TASK_VIEWS, type TaskTab } from "@/lib/sales";
import { useMembers } from "@/lib/use-members";
import { useApi } from "@/lib/use-api";

export default function TasksPage() {
  return (
    <>
      <PageHeader
        title="Follow-ups"
        description="Tasks are created by people. Suggestions appear on an opportunity and are never created automatically."
        actions={<ExportCsvButton entity="tasks" filename="sales-tasks.csv" />}
      />
      <RequireOrganization>
        <Tasks />
      </RequireOrganization>
    </>
  );
}

function Tasks() {
  const tz = browserTimeZone();
  const { nameOf } = useMembers();
  const [tab, setTab] = useState<TaskTab>("overdue");
  const summary = useApi(() => api.GET("/api/v1/sales/tasks/summary", { params: { query: { tz } } }), [tz]);
  const list = useApi(
    () => api.GET("/api/v1/sales/tasks", { params: { query: { ...taskQuery(tab), tz, limit: 100 } } }),
    [tab, tz],
  );
  const counts: Partial<Record<TaskTab, number>> = {
    overdue: summary.data?.overdue,
    today: summary.data?.today,
    upcoming: summary.data?.upcoming,
    completed: summary.data?.completed_last_7_days,
    mine: summary.data?.mine_open,
  };

  function changed() {
    list.reload();
    summary.reload();
  }

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Follow-up views" className="flex gap-1 overflow-x-auto border-b border-line">
        {TASK_VIEWS.map((t) => (
          <button
            key={t.value}
            role="tab"
            type="button"
            aria-selected={tab === t.value}
            onClick={() => setTab(t.value)}
            className={cn(
              "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium",
              tab === t.value ? "border-accent text-white" : "border-transparent text-slate-400 hover:text-slate-100",
            )}
          >
            {t.label}
            {counts[t.value] !== undefined ? <span className="ml-1.5 text-xs text-slate-400">({counts[t.value]})</span> : null}
          </button>
        ))}
      </div>
      <p className="text-xs text-slate-500">Today and upcoming use your time zone ({tz}). “Completed” counts the last 7 days.</p>
      {list.error && !list.data ? <Alert>{list.error}</Alert> : null}
      {list.loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {list.data && list.data.items.length === 0 ? <EmptyState title="Nothing here">No tasks in this view.</EmptyState> : null}
      {list.data && list.data.items.length > 0 ? (
        <ul role="tabpanel" aria-label="Tasks" className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-navy-900/70">
          {list.data.items.map((t) => (
            <TaskRow key={t.id} task={t} assigneeName={nameOf(t.assigned_user_id)} showDeal onChanged={changed} />
          ))}
        </ul>
      ) : null}
      {list.data && list.data.total > list.data.items.length ? (
        <p className="text-xs text-slate-400">
          Showing {list.data.items.length} of {list.data.total}.
        </p>
      ) : null}
    </div>
  );
}
