import * as pdfjsLib from "pdfjs-dist";
// Vite-spezifischer Import: liefert die URL der gebündelten Worker-Datei,
// damit pdf.js seine Rendering-Arbeit in einem Web Worker statt im UI-Thread
// erledigen kann.
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerSrc;

export { pdfjsLib };
