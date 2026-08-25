import { createServer } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import path from "node:path";

const rootDir = process.cwd();
const args = process.argv.slice(2);
const rootFlagIndex = args.indexOf("--root");
const serveRoot = rootFlagIndex >= 0 ? path.resolve(rootDir, args[rootFlagIndex + 1] ?? "dist") : path.resolve(rootDir, "dist");
const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".mjs": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
};

function resolveFile(requestPath) {
  const decoded = decodeURIComponent(requestPath);
  const normalized = decoded.split("?")[0];
  if (!normalized || normalized === "/") {
    return path.join(serveRoot, "index.html");
  }

  // URL-Pfade sind immer POSIX-Style (Forward-Slashes), unabhängig vom
  // Betriebssystem des Servers. Deshalb hier explizit mit path.posix
  // normalisieren (schützt zusätzlich vor "../"-Traversal) und erst danach
  // je Segment mit path.join zu einem echten Dateisystempfad zusammensetzen.
  // path.normalize() allein würde unter Windows Backslashes erzeugen, wonach
  // das führende Zeichen kein "/" mehr ist und candidate.replace(/^\/+/, "")
  // ins Leere liefe – der Pfad würde dann fälschlich als Windows-Laufwerks-
  // wurzel ("\dist\main.js" -> Laufwerkswurzel) statt relativ zu rootDir/
  // serveRoot aufgelöst, die Datei nicht gefunden, und der Server würde auf
  // sein SPA-Fallback (index.html mit falschem Content-Type) zurückfallen.
  const segments = path.posix.normalize(normalized).replace(/^\/+/, "").split("/").filter(Boolean);
  const candidateRel = path.join(...segments);
  const projectPath = path.join(rootDir, candidateRel);
  const distPath = path.join(serveRoot, candidateRel);

  if (projectPath.startsWith(path.join(rootDir, "node_modules")) && existsSync(projectPath)) {
    return projectPath;
  }

  if (existsSync(distPath)) {
    return distPath;
  }

  if (existsSync(projectPath)) {
    return projectPath;
  }

  return path.join(serveRoot, "index.html");
}

const port = Number(process.env.PORT ?? 5173);

const server = createServer((req, res) => {
  const requestUrl = new URL(req.url ?? "/", "http://localhost");
  const requestedPath = requestUrl.pathname;
  const filePath = resolveFile(requestedPath);

  if (!existsSync(filePath) || !statSync(filePath).isFile()) {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Not found");
    return;
  }

  const ext = path.extname(filePath).toLowerCase();
  const contentType = mimeTypes[ext] ?? "application/octet-stream";

  res.writeHead(200, { "Content-Type": contentType, "Cache-Control": "no-store" });
  createReadStream(filePath).pipe(res);
});

server.listen(port, () => {
  console.log(`Frontend-Server läuft unter http://localhost:${port}`);
});
