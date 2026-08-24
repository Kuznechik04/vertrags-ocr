import * as authStore from "../auth/authStore.js";
import { cls, h } from "../lib/dom.js";
import { navigate } from "../lib/router.js";

export function renderLoginPage(container: HTMLElement): void {
  let email = "";
  let password = "";
  let error: string | null = null;
  let submitting = false;

  const errorSlot = h("div", {});
  const submitBtn = h("button", { class: "primary-btn", type: "submit" }, "Anmelden");

  function updateUI(): void {
    errorSlot.replaceChildren();
    if (error) errorSlot.appendChild(h("div", { class: "error-banner" }, error));
    submitBtn.disabled = submitting;
    submitBtn.textContent = submitting ? "Anmelden …" : "Anmelden";
  }

  async function handleSubmit(e: Event): Promise<void> {
    e.preventDefault();
    error = null;
    submitting = true;
    updateUI();
    try {
      await authStore.login(email, password);
      const from = new URLSearchParams(location.search).get("from") ?? "/";
      navigate(from, { replace: true });
    } catch (err) {
      error = err instanceof Error ? err.message : "Anmeldung fehlgeschlagen";
    } finally {
      submitting = false;
      updateUI();
    }
  }

  const form = h(
    "form",
    { class: cls("auth-form"), onsubmit: handleSubmit },
    h("h2", {}, "Anmelden"),
    errorSlot,
    h(
      "label",
      {},
      "E-Mail",
      h("input", {
        type: "email",
        required: true,
        oninput: (e: Event) => {
          email = (e.target as HTMLInputElement).value;
        },
      })
    ),
    h(
      "label",
      {},
      "Passwort",
      h("input", {
        type: "password",
        required: true,
        oninput: (e: Event) => {
          password = (e.target as HTMLInputElement).value;
        },
      })
    ),
    submitBtn,
    h("p", { class: "auth-switch" }, "Noch kein Konto? ", h("a", { href: "/register" }, "Registrieren"))
  );

  container.appendChild(h("div", { class: "auth-page" }, form));
}
