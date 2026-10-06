import { useEffect, useState } from "react";
import { fetchAuditLog } from "../api/client";
import type { AuditEventOut } from "../types";

export function AuditLogPanel() {
  const [events, setEvents] = useState<AuditEventOut[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAuditLog()
      .then(setEvents)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load the audit log."));
  }, []);

  return <section className="audit-panel">
    <div className="panel-heading"><div><h2>Audit log</h2><p>Authentication and review actions recorded by the service.</p></div><span className="mode-pill mode-llm">Admin only</span></div>
    {error && <div className="error-banner">{error}</div>}
    {!error && events.length === 0 ? <p className="empty-state">No audit events recorded yet.</p> : <div className="test-case-table-wrapper" tabIndex={0}><table className="test-case-table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Details</th></tr></thead><tbody>{events.map((event) => <tr key={event.id}><td>{new Date(event.created_at).toLocaleString()}</td><td>{event.actor}</td><td><span className="badge badge-api">{event.action}</span></td><td>{event.target_type}{event.target_id ? ` · ${event.target_id}` : ""}</td><td><code>{JSON.stringify(event.details)}</code></td></tr>)}</tbody></table></div>}
  </section>;
}