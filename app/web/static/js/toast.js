/**
 * Small status message at the bottom of the screen.
 *
 * toast("Copied")                          short confirmation
 * toast("Upload failed: ...", {error: true})  error style, shown longer
 */

let timer = 0;

export function toast(message, { error = false } = {}) {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.classList.toggle("is-error", error);
  t.classList.add("show");
  clearTimeout(timer);
  timer = setTimeout(() => t.classList.remove("show"), error ? 6000 : 2200);
}
