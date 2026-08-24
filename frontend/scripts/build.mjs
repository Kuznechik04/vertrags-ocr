import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const rootDir = process.cwd();
const distDir = path.join(rootDir, "dist");
mkdirSync(distDir, { recursive: true });

// Backend-URL, die das Frontend im Browser für API-Calls nutzt. Per Default
// lokales Backend auf Port 8000 (passt für `npm run dev` und `docker compose`,
// wo der Backend-Port ebenfalls auf den Host gemappt ist). Für andere
// Deployments beim Build überschreiben: API_BASE_URL=https://api.example.com npm run build
const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

const sourceHtml = path.join(rootDir, "index.html");
const targetHtml = path.join(distDir, "index.html");
if (existsSync(sourceHtml)) {
  const html = readFileSync(sourceHtml, "utf8").replace(
    /apiBaseUrl:\s*"[^"]*"/,
    `apiBaseUrl: ${JSON.stringify(apiBaseUrl)}`,
  );
  writeFileSync(targetHtml, html);
}

for (const file of ["index.css", "App.css"]) {
  const sourceFile = path.join(rootDir, "src", file);
  const targetFile = path.join(distDir, file);
  if (existsSync(sourceFile)) {
    copyFileSync(sourceFile, targetFile);
  }
}
