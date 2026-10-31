import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The one place the version lives is src-tauri/tauri.conf.json; the screens show that same number.
const tauriConf = JSON.parse(readFileSync(new URL("./src-tauri/tauri.conf.json", import.meta.url), "utf8"));

// Tauri expects a fixed port and fails if it's taken.
export default defineConfig({
  plugins: [svelte()],
  define: { __APP_VERSION__: JSON.stringify(tauriConf.version) },
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  // Two pages: the app (index.html) and the in-game menu's see-through window (menu.html).
  build: {
    target: "es2022",
    sourcemap: false,
    rollupOptions: { input: { main: "index.html", menu: "menu.html" } },
  },
});
