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
    <div className="login-screen" role="main">
      <div className="login-atmosphere" aria-hidden="true">
        <div className="speed-line speed-line-one" />
        <div className="speed-line speed-line-two" />
        <div className="speed-line speed-line-three" />
        <div className="reactor-core"><span /></div>
        <div className="garage-grid" />
      </div>
      <section className="login-showcase" aria-label="Quality engineering control bay">
        <p className="eyebrow">NIGHT SHIFT / QUALITY CONTROL</p>
        <h2>Ship with<br /><em>confidence.</em></h2>
        <p className="showcase-copy">A pit wall for requirements, regressions, APIs, and every edge case hiding under the hood.</p>
        <div className="telemetry-strip"><span>REQ</span><strong>100%</strong><span>TRACE</span><strong>LIVE</strong></div>
        <div className="machine-signature"><span className="signature-dot" /><span>AI-QE / SYSTEM READY</span><span className="signature-line" /></div>
      </section>
      <form className="login-form" onSubmit={handleSubmit}>
        <div className="login-brand"><span className="brand-mark">AQ</span><span>AI QE COPILOT</span><span className="brand-status">ONLINE</span></div>
        <h1>Enter the<br /><span>control room.</span></h1>
        <p className="subtitle">Authenticate to inspect, generate, and verify.</p>

        <label htmlFor="login-username">Username</label>
        <input
          id="login-username"
          name="username"
          type="text"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />

        <label htmlFor="login-password">Password</label>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        {error && <div className="error-banner" role="alert">{error}</div>}

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
