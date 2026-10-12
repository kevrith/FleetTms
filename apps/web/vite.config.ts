import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/** Fills in public/sw.js with this build's file list and a fresh cache name, so the app shell can be saved for offline use. */
function offlineShell(): Plugin {
  return {
    name: "offline-shell",
    apply: "build",
    writeBundle(options, bundle) {
      const file = join(options.dir ?? "dist", "sw.js");
      const built = Object.keys(bundle)
        .filter((name) => !name.endsWith(".map") && name !== "index.html")
        .map((name) => `/${name}`);
      const shell = [
        "/",
        "/manifest.webmanifest",
        "/logo.png",
        "/icon-192.png",
        "/favicon.ico",
        ...built,
      ];
      const sw = readFileSync(file, "utf8")
        .replace('["__PRECACHE__"]', JSON.stringify(shell))
        .replace("__BUILD__", Date.now().toString(36));
      writeFileSync(file, sw);
    },
  };
}

export default defineConfig({ plugins: [react(), offlineShell()], server: { port: 5180 } });
