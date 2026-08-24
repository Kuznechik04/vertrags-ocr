import { renderNotFound, renderShell, routes } from "./app.js";
import * as authStore from "./auth/authStore.js";
import { initRouter, revalidate } from "./lib/router.js";

const root = document.getElementById("root");
if (!root) throw new Error("#root nicht gefunden");

authStore.init();
const outlet = renderShell(root);
authStore.subscribe(() => revalidate());
initRouter(outlet, routes, renderNotFound);
