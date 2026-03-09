import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    allowedHosts: ["forcepslike-nerissa-shoeless.ngrok-free.dev"],
    proxy: {
      "/chat": "http://127.0.0.1:8001",
      "/sessions": "http://127.0.0.1:8001",
      "/audio": "http://127.0.0.1:8001",
      "/download": "http://127.0.0.1:8001",
      "/health": "http://127.0.0.1:8001",
      "/audio-registry": "http://127.0.0.1:8001",
      "/tts": "http://127.0.0.1:8001",
    },
  },
});
