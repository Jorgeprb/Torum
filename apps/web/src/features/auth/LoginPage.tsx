import { FormEvent, useState } from "react";
import { LockKeyhole, Terminal } from "lucide-react";

import { useAuthStore } from "../../stores/authStore";

export function LoginPage() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const { error, login, status } = useAuthStore();
  const isLoading = status === "loading";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await login(username, password);
  }

  return (
    <main className="login-screen">
      <section className="login-panel" aria-label="Acceso">
        <div className="login-brand">
          <div className="brand-mark brand-mark--large">T</div>
          <div>
            <p className="eyebrow">Torum</p>
            <h1>Acceso</h1>
          </div>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <label>
            Usuario
            <input
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="admin"
            />
          </label>
          <label>
            Contraseña
            <input
              autoComplete="current-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="••••••••"
            />
          </label>

          {error ? <div className="form-error">{error}</div> : null}

          <button className="primary-button" type="submit" disabled={isLoading}>
            {isLoading ? <Terminal size={18} /> : <LockKeyhole size={18} />}
            {isLoading ? "Validando" : "Entrar"}
          </button>
        </form>
      </section>
    </main>
  );
}
