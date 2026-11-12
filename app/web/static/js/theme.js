/**
 * Light/dark theme: the toggle, the saved preference, and change notifications.
 *
 * The switch is the "Ink Bleed" transition (js/ink/, ported from Codemure's MIT-licensed
 * project): ink spreads from where you click, with curling tendrils, paper-fibre edges, droplets
 * and a pigment rim, while the sun morphs into a moon. See js/ink/transition.js for how it stays
 * reliable on a page whose content keeps changing. Without WebGL2, or with "reduce motion", it
 * falls back to a short colour fade.
 *
 * The choice is saved in localStorage ("ayd-theme"); index.html applies it before first paint.
 * Press T anywhere (outside text fields) to toggle.
 *
 * Exports: initTheme(button, canvas), currentTheme(), cssVar(name), onThemeChange(fn)
 */

import { InkTransition, getTheme } from "./ink/transition.js";

const KEY = "ayd-theme";
const listeners = new Set();

export const currentTheme = getTheme;

/** Read a CSS variable from the active theme. */
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Run `fn(theme)` whenever the theme changes (charts redraw with new colours). */
export const onThemeChange = (fn) => listeners.add(fn);

function save(theme) {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* storage unavailable: the theme still applies for this visit */
  }
}

export function initTheme(button, canvas) {
  const ink = new InkTransition(canvas, button, {
    onApply: (theme) => {
      save(theme);
      button.setAttribute("aria-label", theme === "dark" ? "Light mode" : "Dark mode");
      listeners.forEach((fn) => fn(theme));
    },
  });
  button.setAttribute("aria-pressed", String(getTheme() === "dark"));

  // Keyboard-activated clicks (detail === 0) spread from the button itself.
  button.addEventListener("click", (e) => void ink.toggle(e.detail === 0 ? undefined : { x: e.clientX, y: e.clientY }));

  // "T" toggles, unless the user is typing.
  window.addEventListener("keydown", (e) => {
    if (e.repeat || e.metaKey || e.ctrlKey || e.altKey || e.key.toLowerCase() !== "t") return;
    if (e.target instanceof Element && e.target.closest("input, textarea, select, [contenteditable='true']")) return;
    e.preventDefault();
    void ink.toggle();
  });
  return ink;
}
