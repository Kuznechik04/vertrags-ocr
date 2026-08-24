/** Minimaler Ersatz für JSX: baut echte DOM-Knoten statt React-Elemente.
 *
 * Event-Props werden 1:1 als native Event-Namen erwartet (`onclick`,
 * `oninput`, `onchange`, `onmousedown`, …) – kein Camel-Case-Mapping, um
 * Verwechslungen zwischen React-`onChange` (≈ natives `input`) und dem
 * nativen `change`-Event zu vermeiden. Für live aktualisierte Textfelder
 * immer `oninput` verwenden, `onchange` nur für `<select>`/Checkboxen. */

export type Child = Node | string | number | null | undefined | boolean | Child[];

export interface Props {
  class?: string;
  style?: Partial<CSSStyleDeclaration>;
  ref?: (el: HTMLElement) => void;
  [key: string]: unknown;
}

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props?: Props | null,
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);

  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value == null) continue;
      if (key === "class") {
        el.className = String(value);
      } else if (key === "style") {
        Object.assign(el.style, value as Partial<CSSStyleDeclaration>);
      } else if (key === "ref") {
        (value as (el: HTMLElement) => void)(el);
      } else if (key.startsWith("on") && typeof value === "function") {
        el.addEventListener(key.slice(2), value as EventListener);
      } else if (key in el) {
        // Echte DOM-Properties direkt setzen (value, disabled, checked,
        // href, src, colSpan, draggable, …) – so bleiben z.B. kontrollierte
        // <input>/<select>/<textarea>-Werte im Sync mit dem State.
        (el as unknown as Record<string, unknown>)[key] = value;
      } else {
        el.setAttribute(key, String(value));
      }
    }
  }

  appendChildren(el, children);
  return el;
}

function appendChildren(el: HTMLElement, children: Child[]): void {
  for (const child of children) {
    if (child == null || child === false || child === true) continue;
    if (Array.isArray(child)) {
      appendChildren(el, child);
    } else if (child instanceof Node) {
      el.appendChild(child);
    } else {
      el.appendChild(document.createTextNode(String(child)));
    }
  }
}

/** Baut aus optionalen/bedingten Teilen eine Klassenliste, z.B.
 * `cls("field-row", isActive && "active", isValidated && "validated")`. */
export function cls(...parts: (string | false | null | undefined)[]): string {
  return parts.filter((p): p is string => Boolean(p)).join(" ");
}

export function clear(el: HTMLElement): void {
  el.replaceChildren();
}

export function mount(container: HTMLElement, node: Node): void {
  clear(container);
  container.appendChild(node);
}
