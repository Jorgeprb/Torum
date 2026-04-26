import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: [
        "pwa-icon-192.png",
        "pwa-icon-512.png",
        "pwa-maskable-512.png"
      ],
      manifest: {
        id: "/",
        name: "Torum",
        short_name: "Torum",
        description: "Terminal PWA de trading para oro conectado a MT5.",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#101314",
        theme_color: "#101314",
        icons: [
          {
            src: "/pwa-icon-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any"
          },
          {
            src: "/pwa-icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any"
          },
          {
            src: "/pwa-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable"
          }
        ]
      },
      workbox: {
        navigateFallback: "/",
        globPatterns: ["**/*.{js,css,html,ico,png,svg,webmanifest}"]
      }
    })
  ],

  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    allowedHosts: [
      "pc-oficina.tail652fa7.ts.net",
      "100.124.49.118",
      "localhost",
      "127.0.0.1"
    ]
  },

  preview: {
    host: "0.0.0.0",
    port: 4173,
    strictPort: true,
    allowedHosts: [
      "pc-oficina.tail652fa7.ts.net",
      "100.124.49.118",
      "localhost",
      "127.0.0.1"
    ]
  }
});