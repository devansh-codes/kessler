import { h } from "../ui";

export function render(root: HTMLElement): void {
  root.append(h("div", { class: "wrap section" }, h("p", { class: "eyebrow" }, "Kessler"), h("h1", {}, "Coming online"), h("p", { class: "lede", style: "margin-top:12px" }, "This view is being built.")));
}
