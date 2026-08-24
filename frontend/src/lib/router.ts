/** Minimaler History-API-Router (kein Hash-Routing) als Ersatz für
 * react-router-dom. `scripts/dev-server.mjs` liefert für unbekannte Pfade
 * bereits `index.html` aus (SPA-Fallback), das trägt Deep-Links wie
 * `/documents/abc123` auch bei hartem Reload. */
import { clear, h } from "./dom.js";

export interface RouteContext {
  params: Record<string, string>;
}

export type Teardown = () => void;
export type RouteRender = (container: HTMLElement, ctx: RouteContext) => void | Teardown;

/** Sentinel, den ein Guard statt eines Redirect-Pfads zurückgeben kann,
 * während z.B. der Login-Status noch lädt – der Router zeigt dann kurz
 * "Lade …" statt vorschnell zu redirecten. */
export const PENDING = "@@pending" as const;

export type GuardResult = true | string | typeof PENDING;
export type Guard = (ctx: RouteContext) => GuardResult;

export interface RouteDef {
  path: string;
  render: RouteRender;
  guard?: Guard;
}

let routes: RouteDef[] = [];
let notFoundRender: RouteRender | null = null;
let outlet: HTMLElement | null = null;
let currentTeardown: Teardown | null = null;
let started = false;

function splitPath(path: string): string[] {
  return path.split("/").filter(Boolean);
}

function matchRoute(pathname: string): { route: RouteDef; params: Record<string, string> } | null {
  const segments = splitPath(pathname);
  for (const route of routes) {
    const routeSegments = splitPath(route.path);
    if (routeSegments.length !== segments.length) continue;
    const params: Record<string, string> = {};
    let matched = true;
    for (let i = 0; i < routeSegments.length; i++) {
      const rs = routeSegments[i];
      const s = segments[i];
      if (rs.startsWith(":")) {
        params[rs.slice(1)] = decodeURIComponent(s);
      } else if (rs !== s) {
        matched = false;
        break;
      }
    }
    if (matched) return { route, params };
  }
  return null;
}

function teardownCurrent(): void {
  if (currentTeardown) {
    currentTeardown();
    currentTeardown = null;
  }
}

export function resolve(): void {
  if (!outlet) return;
  const pathname = location.pathname;
  const match = matchRoute(pathname);

  if (!match) {
    teardownCurrent();
    clear(outlet);
    if (notFoundRender) {
      const teardown = notFoundRender(outlet, { params: {} });
      currentTeardown = typeof teardown === "function" ? teardown : null;
    }
    return;
  }

  const ctx: RouteContext = { params: match.params };

  if (match.route.guard) {
    const result = match.route.guard(ctx);
    if (result === PENDING) {
      teardownCurrent();
      clear(outlet);
      outlet.appendChild(h("div", { class: "page" }, "Lade …"));
      return;
    }
    if (result !== true) {
      navigate(result, { replace: true });
      return;
    }
  }

  teardownCurrent();
  clear(outlet);
  const teardown = match.route.render(outlet, ctx);
  currentTeardown = typeof teardown === "function" ? teardown : null;
}

/** Vom Auth-Store (o.ä.) aufrufen, wenn sich state geändert hat, der die
 * aktuelle Route betrifft (z.B. Logout auf einer geschützten Seite). */
export function revalidate(): void {
  resolve();
}

export function navigate(path: string, opts?: { replace?: boolean }): void {
  if (opts?.replace) {
    history.replaceState(null, "", path);
  } else {
    history.pushState(null, "", path);
  }
  resolve();
}

function handleClick(e: MouseEvent): void {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const target = e.target as HTMLElement | null;
  const anchor = target?.closest("a");
  if (!anchor) return;
  if (anchor.target && anchor.target !== "_self") return;
  if (anchor.hasAttribute("download")) return;
  const href = anchor.getAttribute("href");
  if (!href || !href.startsWith("/")) return;
  e.preventDefault();
  navigate(href);
}

export function initRouter(container: HTMLElement, defs: RouteDef[], notFound?: RouteRender): void {
  outlet = container;
  routes = defs;
  notFoundRender = notFound ?? null;
  if (!started) {
    window.addEventListener("popstate", resolve);
    document.body.addEventListener("click", handleClick);
    started = true;
  }
  resolve();
}
