import { useEffect, useState } from "react";
import type { PersistedTestCase, TestCaseStatus } from "../types";
import { deleteSavedTestCase, downloadExport, listSavedTestCases, updateSavedTestCase } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const STATUS_FILTERS: Array<TestCaseStatus | "all"> = ["all", "draft", "approved", "rejected"];

export function LibraryPanel() {
  const { user } = useAuth();
  const canApprove = user?.role === "admin";
  const canDelete = user?.role === "admin";

  const [testCases, setTestCases] = useState<PersistedTestCase[]>([]);
  const [statusFilter, setStatusFilter] = useState<TestCaseStatus | "all">("all");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const status = statusFilter === "all" ? undefined : statusFilter;
      setTestCases(await listSavedTestCases(status));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load library.");
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  async function setStatus(tc: PersistedTestCase, status: TestCaseStatus) {
    try {
      await updateSavedTestCase(tc.db_id, { status });
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed.");
    }
  }

  async function saveTitleEdit(tc: PersistedTestCase) {
    if (draftTitle.trim() && draftTitle !== tc.title) {
      try {
        await updateSavedTestCase(tc.db_id, { title: draftTitle.trim() });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Update failed.");
      }
    }
    setEditingId(null);
    refresh();
  }

  async function remove(tc: PersistedTestCase) {
    try {
      await deleteSavedTestCase(tc.db_id);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed.");
    }
  }

  async function handleExport(format: "csv" | "json") {
    try {
      await downloadExport(format, statusFilter === "all" ? undefined : statusFilter);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed.");
    }
  }

  return (
    <div className="library-panel">
      <div className="table-header-row">
        <h2>Test case library ({testCases.length})</h2>
        <div className="library-actions">
          <button type="button" onClick={() => handleExport("csv")}>
            Export CSV
          </button>
          <button type="button" onClick={() => handleExport("json")}>
            Export JSON
          </button>
        </div>
      </div>

      <div className="status-filter-row">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            type="button"
            className={statusFilter === s ? "tab-active" : ""}
            onClick={() => setStatusFilter(s)}
          >
            {s}
          </button>
        ))}
      </div>

      {error && <div className="error-banner">{error}</div>}

      {testCases.length === 0 ? (
        <p className="empty-state">
          Nothing saved yet. Generate test cases above, then use "Save to library" to bring
          them here for review, editing, and approval.
        </p>
      ) : (
        <table className="test-case-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Title</th>
              <th>Type</th>
              <th>Status</th>
              <th>Citation</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {testCases.map((tc) => (
              <tr key={tc.db_id}>
                <td>{tc.id}</td>
                <td>
                  {editingId === tc.db_id ? (
                    <input
                      type="text"
                      value={draftTitle}
                      onChange={(e) => setDraftTitle(e.target.value)}
                      onBlur={() => saveTitleEdit(tc)}
                      onKeyDown={(e) => e.key === "Enter" && saveTitleEdit(tc)}
                      autoFocus
                    />
                  ) : (
                    <span
                      className="editable-title"
                      onClick={() => {
                        setEditingId(tc.db_id);
                        setDraftTitle(tc.title);
                      }}
                      title="Click to edit"
                    >
                      {tc.title}
                    </span>
                  )}
                </td>
                <td>
                  <span className={`badge badge-${tc.type}`}>{tc.type}</span>
                </td>
                <td>
                  <span className={`status-pill status-${tc.status}`}>{tc.status}</span>
                </td>
                <td className="citation-cell">
                  <span className="citation-tag">{tc.requirement_reference}</span>
                </td>
                <td className="action-cell">
                  {tc.status !== "approved" && (
                    <button
                      type="button"
                      className="small-button approve"
                      onClick={() => setStatus(tc, "approved")}
                      disabled={!canApprove}
                      title={canApprove ? undefined : "Only admins can approve"}
                    >
                      Approve
                    </button>
                  )}
                  {tc.status !== "rejected" && (
                    <button type="button" className="small-button reject" onClick={() => setStatus(tc, "rejected")}>
                      Reject
                    </button>
                  )}
                  <button
                    type="button"
                    className="small-button delete"
                    onClick={() => remove(tc)}
                    disabled={!canDelete}
                    title={canDelete ? undefined : "Only admins can delete"}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
