import * as authStore from "../auth/authStore.js";
import { h } from "../lib/dom.js";
import { navigate } from "../lib/router.js";

export function renderRegisterPage(container: HTMLElement): void {
  let email = "";
  let password = "";
  let error: string | null = null;
  let submitting = false;

  const errorSlot = h("div", {});
  const submitBtn = h("button", { class: "primary-btn", type: "submit" }, "Registrieren");

  function updateUI(): void {
    errorSlot.replaceChildren();
    if (error) errorSlot.appendChild(h("div", { class: "error-banner" }, error));
    submitBtn.disabled = submitting;
    submitBtn.textContent = submitting ? "Registriere …" : "Registrieren";
  }

  async function handleSubmit(e: Event): Promise<void> {
    e.preventDefault();
    error = null;
    if (password.length < 8) {
      error = "Das Passwort muss mindestens 8 Zeichen lang sein.";
      updateUI();
      return;
    }
    submitting = true;
    updateUI();
    try {
      await authStore.register(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      error = err instanceof Error ? err.message : "Registrierung fehlgeschlagen";
    } finally {
      submitting = false;
      updateUI();
    }
  }

  const form = h(
    "form",
    { class: "auth-form", onsubmit: handleSubmit },
    h("h2", {}, "Konto erstellen"),
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
        minLength: 8,
        oninput: (e: Event) => {
          password = (e.target as HTMLInputElement).value;
        },
      })
    ),
    submitBtn,
    h("p", { class: "auth-switch" }, "Bereits ein Konto? ", h("a", { href: "/login" }, "Anmelden"))
  );

  container.appendChild(h("div", { class: "auth-page" }, form));
}
