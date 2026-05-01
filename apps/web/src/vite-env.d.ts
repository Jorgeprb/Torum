/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_WS_BASE_URL?: string;
  readonly VITE_PUBLIC_HOST?: string;
  readonly VITE_TAILSCALE_MODE?: string;
  readonly VITE_APP_MODE?: string;
  readonly VITE_CHART_BROKER_TIME_ZONE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
