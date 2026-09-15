import { useState } from "react";
import { useAuth } from "../auth/AuthContext";

export function LoginForm() {
  const { login, error } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setIsSubmitting(true);
    try {
      await login(username.trim(), password);
    } catch {
      // error is already surfaced via useAuth().error
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-form" onSubmit={handleSubmit}>
        <h1>AI Quality Engineering Copilot</h1>
        <p className="subtitle">Sign in to continue.</p>

        <label htmlFor="login-username">Username</label>
        <input
          id="login-username"
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />

        <label htmlFor="login-password">Password</label>
        <input
          id="login-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        {error && <div className="error-banner">{error}</div>}

        <button type="submit" disabled={isSubmitting || !username.trim() || !password}>
          {isSubmitting ? "Signing in..." : "Sign in"}
        </button>

        <p className="hint-text">
          First time running this locally? The backend seeds a demo admin account
          (<code>admin</code> / <code>changeme123</code>) on first startup if no users exist yet —
          see the README for how to change it before deploying anywhere real.
        </p>
      </form>
    </div>
  );
}
