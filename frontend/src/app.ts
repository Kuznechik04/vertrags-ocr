/** App-Shell (Header + Routen-Outlet) und Routen-Registrierung. Ersetzt
 * App.tsx. Der Header ist persistent (überlebt Routenwechsel), nur der
 * User-Badge-Bereich wird bei Auth-Änderungen neu gerendert. */
import * as authStore from "./auth/authStore.js";
import type { AuthState } from "./auth/authStore.js";
import { requireAdmin, requireAuth } from "./auth/guards.js";
import { h, mount } from "./lib/dom.js";
import type { RouteDef } from "./lib/router.js";
import { renderDocumentListPage } from "./pages/documentListPage.js";
import { renderDocumentReviewPage } from "./pages/documentReviewPage.js";
import { renderLoginPage } from "./pages/loginPage.js";
import { renderRegisterPage } from "./pages/registerPage.js";
import { renderTemplateAdminPage } from "./pages/templateAdminPage.js";

export function renderShell(root: HTMLElement): HTMLElement {
  const badgeSlot = h("div", { class: "header-badge-slot" });
  const outlet = h("main", {});

  const shell = h(
    "div",
    { class: "app-shell" },
    h(
      "header",
      { class: "app-header" },
      h(
        "div",
        { class: "app-header-row" },
        h(
          "div",
          {},
          h("h1", {}, "Vertrags-OCR Review"),
          h("p", {}, "Verträge hochladen, erkannte Felder prüfen und korrigieren.")
        ),
        badgeSlot
      )
    ),
    outlet
  );

  function renderBadge(state: AuthState): void {
    if (!state.user) {
      mount(badgeSlot, h("div", {}));
      return;
    }
    const { user } = state;
    mount(
      badgeSlot,
      h(
        "div",
        { class: "user-badge" },
        h("span", {}, `${user.email} `, user.role === "admin" ? h("span", { class: "admin-tag" }, "Admin") : null),
        user.role === "admin" ? h("a", { href: "/admin/templates" }, "Vertragstypen") : null,
        h("button", { class: "link-btn", onclick: () => authStore.logout() }, "Abmelden")
      )
    );
  }

  authStore.subscribe(renderBadge);
  renderBadge(authStore.getState());

  root.appendChild(shell);
  return outlet;
}

export const routes: RouteDef[] = [
  { path: "/login", render: renderLoginPage },
  { path: "/register", render: renderRegisterPage },
  { path: "/", render: renderDocumentListPage, guard: requireAuth() },
  { path: "/documents/:id", render: renderDocumentReviewPage, guard: requireAuth() },
  { path: "/admin/templates", render: renderTemplateAdminPage, guard: requireAdmin() },
];

export function renderNotFound(container: HTMLElement): void {
  container.appendChild(h("a", { href: "/" }, "Zurück zur Startseite"));
}
