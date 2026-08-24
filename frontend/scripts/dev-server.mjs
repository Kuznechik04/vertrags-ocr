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

  const candidate = path.normalize(normalized).replace(/^\/+/, "");
  const projectPath = path.resolve(rootDir, candidate);
  const distPath = path.resolve(serveRoot, candidate);

  if (projectPath.startsWith(path.resolve(rootDir, "node_modules")) && existsSync(projectPath)) {
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
