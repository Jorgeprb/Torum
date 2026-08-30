import { useEffect } from "react";

import { Shell } from "./components/layout/Shell";
import { LoginPage } from "./features/auth/LoginPage";
import { useAuthStore } from "./stores/authStore";

export default function App() {
  const { initialize, refreshSession, status, token, user } = useAuthStore();

  useEffect(() => {
    void initialize();
  }, [initialize]);

  useEffect(() => {
    if (status !== "authenticated") return;

    const refreshIfNeeded = () => {
      if (document.visibilityState === "visible") void refreshSession();
    };
    const timer = window.setInterval(refreshIfNeeded, 30 * 60 * 1000);
    document.addEventListener("visibilitychange", refreshIfNeeded);
    window.addEventListener("focus", refreshIfNeeded);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshIfNeeded);
      window.removeEventListener("focus", refreshIfNeeded);
    };
  }, [refreshSession, status]);

  if (status === "booting") {
    return <div className="boot-screen">Torum</div>;
  }

  if (!token || !user) {
    return <LoginPage />;
  }

  return <Shell user={user} />;
}
