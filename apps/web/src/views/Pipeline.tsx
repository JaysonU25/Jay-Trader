import { DataTable } from "@/components/DataTable";
import { ErrorState, Loading } from "@/components/States";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime } from "@/lib/format";
import { useStatus } from "@/lib/queries";

export function Pipeline() {
  const runs = useStatus();

  if (runs.isLoading) return <Loading label="Loading pipeline history" />;
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />;

  return (
    <>
      <h1>Pipeline</h1>
      <div className="card">
        <DataTable
          caption="Most recent ingest run per source"
          columns={[
            { key: "source", header: "Source" },
            { key: "job", header: "Job" },
            { key: "status", header: "Status" },
            { key: "rows", header: "Rows", align: "right" },
            { key: "calls", header: "Calls", align: "right" },
            { key: "started", header: "Started" },
            { key: "error", header: "Error" },
          ]}
          rows={(runs.data ?? []).map((run) => ({
            source: run.source,
            job: run.job,
            status: <StatusBadge status={run.status} />,
            rows: run.rows_upserted.toLocaleString(),
            calls: run.api_calls_used,
            started: formatDateTime(run.started_at),
            error: run.error,
          }))}
        />
      </div>
    </>
  );
}
