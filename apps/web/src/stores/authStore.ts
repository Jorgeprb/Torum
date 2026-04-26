import { create } from "zustand";

import { getMe, login as loginRequest, type User } from "../services/api";

type AuthStatus = "booting" | "anonymous" | "loading" | "authenticated";

interface AuthState {
  status: AuthStatus;
  token: string | null;
  user: User | null;
  error: string | null;
  initialize: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const TOKEN_STORAGE_KEY = "torum.access_token";

export function getAuthToken(): string | null {
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export const useAuthStore = create<AuthState>((set) => ({
  status: "booting",
  token: null,
  user: null,
  error: null,

  initialize: async () => {
    const token = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!token) {
      set({ status: "anonymous", token: null, user: null, error: null });
      return;
    }

    try {
      const user = await getMe(token);
      set({ status: "authenticated", token, user, error: null });
    } catch {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
      set({ status: "anonymous", token: null, user: null, error: null });
    }
  },

  login: async (username: string, password: string) => {
    set({ status: "loading", error: null });
    try {
      const response = await loginRequest(username, password);
      window.localStorage.setItem(TOKEN_STORAGE_KEY, response.access_token);
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

  logout: () => {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    set({ status: "anonymous", token: null, user: null, error: null });
  }
}));
