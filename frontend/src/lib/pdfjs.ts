import * as pdfjsLib from "pdfjs-dist";

// Ohne Vite/Esbuild werden Worker-Dateien über einen statischen Pfad aus
// node_modules direkt vom HTTP-Server ausgeliefert.
pdfjsLib.GlobalWorkerOptions.workerSrc = "/node_modules/pdfjs-dist/build/pdf.worker.min.mjs";

export { pdfjsLib };
