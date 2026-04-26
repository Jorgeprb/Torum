import { useEffect } from "react";

import { Shell } from "./components/layout/Shell";
import { LoginPage } from "./features/auth/LoginPage";
import { useAuthStore } from "./stores/authStore";

export default function App() {
  const { initialize, status, token, user } = useAuthStore();

  useEffect(() => {
    void initialize();
  }, [initialize]);

  if (status === "booting") {
    return <div className="boot-screen">Torum</div>;
  }

  if (!token || !user) {
    return <LoginPage />;
  }

  return <Shell user={user} />;
}
