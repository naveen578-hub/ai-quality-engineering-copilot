import { useEffect, useState } from "react";
import type { Role, UserOut } from "../types";
import { createUser, listUsers } from "../api/client";

const ROLES: Role[] = ["viewer", "tester", "admin"];

export function UsersPanel() {
  const [users, setUsers] = useState<UserOut[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("tester");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function refresh() {
    try {
      setUsers(await listUsers());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || password.length < 8) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await createUser({ username: username.trim(), password, role });
      setUsername("");
      setPassword("");
      setRole("tester");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="users-panel">
      <h2>Users</h2>

      <table className="test-case-table">
        <thead>
          <tr>
            <th>Username</th>
            <th>Role</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.username}</td>
              <td>
                <span className={`status-pill status-${u.role === "admin" ? "approved" : "draft"}`}>{u.role}</span>
              </td>
              <td className="doc-meta">{new Date(u.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <form className="requirement-input" onSubmit={handleSubmit} style={{ marginTop: "1.5rem" }}>
        <h2 style={{ fontSize: "0.95rem", margin: "0 0 0.75rem" }}>Create a user</h2>
        <div className="field-row">
          <label htmlFor="new-username">Username</label>
          <input id="new-username" type="text" value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="field-row">
          <label htmlFor="new-password">Password</label>
          <input
            id="new-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="min. 8 characters"
          />
        </div>
        <fieldset className="type-checkboxes">
          <legend>Role</legend>
          {ROLES.map((r) => (
            <label key={r} className="checkbox-label">
              <input type="radio" name="role" checked={role === r} onChange={() => setRole(r)} />
              {r}
            </label>
          ))}
        </fieldset>

        {error && <div className="error-banner">{error}</div>}

        <button type="submit" disabled={isSubmitting || !username.trim() || password.length < 8}>
          {isSubmitting ? "Creating..." : "Create user"}
        </button>
      </form>
    </div>
  );
}
