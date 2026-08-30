import { create } from "zustand";

import {
  bootstrapPersistentSession,
  getMe,
  login as loginRequest,
  revokePersistentSession,
  type User,
} from "../services/api";
import {
  AUTH_ACCESS_TOKEN_UPDATED_EVENT,
  AUTH_SESSION_INVALID_EVENT,
  clearAuthenticatedSession,
  ensureFreshStoredAccessToken,
  getAuthToken,
  getCachedAuthUser,
  getPersistentSessionToken,
  setCachedAuthUser,
  setPersistentSessionToken,
  storeAuthenticatedSession,
} from "../services/authSession";

type AuthStatus = "booting" | "anonymous" | "loading" | "authenticated";

interface AuthState {
  status: AuthStatus;
  token: string | null;
  user: User | null;
  error: string | null;
  initialize: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  refreshSession: () => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: "booting",
  token: null,
  user: null,
  error: null,

  initialize: async () => {
    const accessToken = getAuthToken();
    const persistentToken = getPersistentSessionToken();
    const cachedUser = getCachedAuthUser<User>();
    if (!accessToken && !persistentToken) {
      set({ status: "anonymous", token: null, user: null, error: null });
      return;
    }

    try {
      await ensureFreshStoredAccessToken(60 * 60);
      const user = await getMe();

      // Seamless upgrade from the old access-token-only login: while the old
      // JWT is still valid, create the persistent server session once.
      if (!getPersistentSessionToken()) {
        const session = await bootstrapPersistentSession();
        setPersistentSessionToken(session.session_token);
      }

      setCachedAuthUser(user);
      set({ status: "authenticated", token: getAuthToken(), user, error: null });
    } catch (error) {
      const stillHasPersistentSession = Boolean(getPersistentSessionToken());
      if (stillHasPersistentSession) {
        // Offline/backend outages must never destroy the persistent credential.
        // Normally cachedUser is always present; if browser storage was partly
        // cleared, keep the session token so a reload can recover once the API
        // is reachable again.
        if (cachedUser) {
          set({ status: "authenticated", token: getAuthToken(), user: cachedUser, error: null });
        } else {
          set({ status: "anonymous", token: getAuthToken(), user: null, error: null });
        }
        return;
      }
      clearAuthenticatedSession();
      set({ status: "anonymous", token: null, user: null, error: null });
    }
  },

  login: async (username: string, password: string) => {
    set({ status: "loading", error: null });
    try {
      const response = await loginRequest(username, password);
      storeAuthenticatedSession(response.access_token, response.session_token, response.user);
      set({
        status: "authenticated",
        token: response.access_token,
        user: response.user,
        error: null
      });
    } catch (error) {
      set({
        status: "anonymous",
        token: null,
        user: null,
        error: error instanceof Error ? error.message : "No se pudo iniciar sesion"
      });
    }
  },

  refreshSession: async () => {
    try {
      await ensureFreshStoredAccessToken(2 * 60 * 60);
      set({ token: getAuthToken() });
    } catch {
      // Connectivity failures must not log the user out. A genuinely revoked
      // session emits AUTH_SESSION_INVALID_EVENT from authSession.ts.
    }
  },

  logout: () => {
    const sessionToken = getPersistentSessionToken();
    clearAuthenticatedSession();
    set({ status: "anonymous", token: null, user: null, error: null });
    if (sessionToken) void revokePersistentSession(sessionToken).catch(() => undefined);
  }
}));

if (typeof window !== "undefined") {
  window.addEventListener(AUTH_ACCESS_TOKEN_UPDATED_EVENT, () => {
    useAuthStore.setState({ token: getAuthToken() });
  });
  window.addEventListener(AUTH_SESSION_INVALID_EVENT, () => {
    useAuthStore.setState({ status: "anonymous", token: null, user: null, error: null });
  });
  window.addEventListener("storage", () => {
    const token = getAuthToken();
    const sessionToken = getPersistentSessionToken();
    const user = getCachedAuthUser<User>();
    if (!token && !sessionToken) {
      useAuthStore.setState({ status: "anonymous", token: null, user: null, error: null });
      return;
    }
    if (user) useAuthStore.setState({ status: "authenticated", token, user, error: null });
  });
}
