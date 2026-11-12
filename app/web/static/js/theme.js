/**
 * Light/dark theme toggle.
 *
 * Default follows the OS. Clicking the toggle forces the opposite of what is showing and saves
 * the choice in localStorage ("ayd-theme"). Listeners (charts) are told so they can redraw.
 */

import { icon } from "./icons.js";

const KEY = "ayd-theme";
const listeners = new Set();

/** The theme currently showing: "light" or "dark". */
export function currentTheme() {
  const forced = document.documentElement.dataset.theme;
  if (forced) return forced;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Read a CSS variable from the active theme. */
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Run `fn` whenever the theme changes. */
export const onThemeChange = (fn) => listeners.add(fn);

function apply(theme, button) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* storage unavailable: theme still applies for this visit */
  }
  button.innerHTML = icon(theme === "dark" ? "sun" : "moon");
  listeners.forEach((fn) => fn(theme));
}

export function initTheme(button) {
  button.innerHTML = icon(currentTheme() === "dark" ? "sun" : "moon");
  button.addEventListener("click", () => apply(currentTheme() === "dark" ? "light" : "dark", button));
  // Follow OS changes while the user hasn't forced a theme.
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!document.documentElement.dataset.theme) listeners.forEach((fn) => fn(currentTheme()));
  });
}
