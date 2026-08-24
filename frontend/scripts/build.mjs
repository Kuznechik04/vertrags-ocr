import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";

const rootDir = process.cwd();
const distDir = path.join(rootDir, "dist");
mkdirSync(distDir, { recursive: true });

const sourceHtml = path.join(rootDir, "index.html");
const targetHtml = path.join(distDir, "index.html");
if (existsSync(sourceHtml)) {
  copyFileSync(sourceHtml, targetHtml);
}

for (const file of ["index.css", "App.css"]) {
  const sourceFile = path.join(rootDir, "src", file);
  const targetFile = path.join(distDir, file);
  if (existsSync(sourceFile)) {
    copyFileSync(sourceFile, targetFile);
  }
}
