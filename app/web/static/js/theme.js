/**
 * Light/dark theme: the toggle, the saved preference, and change notifications.
 *
 * The switch is animated as ink spreading from where you click:
 *   1. View Transitions (Chrome, Edge, Safari 18+, Firefox 144+): the browser snapshots the page
 *      at the moment of the click, so the effect is available every time, including while an
 *      answer is arriving. The new theme is revealed through a circle that grows from the click
 *      point (clip-path on ::view-transition-new(root), animated on the GPU with the Web
 *      Animations API). Nothing is pre-captured, so there is no background work between toggles.
 *   2. Older browsers: the WebGL ink-bleed effect (js/ink/), which needs pre-captured snapshots
 *      and falls back to a colour fade when they are not ready.
 *   3. "Reduce motion": a short colour fade.
 * The sun/moon icon morphs in step. The choice is saved in localStorage ("ayd-theme");
 * index.html applies it before first paint. Press T anywhere (outside text fields) to toggle.
 *
 * Exports: initTheme(button, canvas), currentTheme(), cssVar(name), onThemeChange(fn)
 */

import { InkTransition, getTheme, otherTheme } from "./ink/transition.js";
import { ThemeIcon } from "./ink/themeIcon.js";

const KEY = "ayd-theme";
const DURATION_MS = 700;
const EASING = "cubic-bezier(0.22, 0.7, 0.18, 1)"; // fast start, long soft settle
const FADE_S = 0.35;
const listeners = new Set();
const root = document.documentElement;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

export const currentTheme = getTheme;

/** Read a CSS variable from the active theme. */
export const cssVar = (name) => getComputedStyle(root).getPropertyValue(name).trim();

/** Run `fn(theme)` whenever the theme changes (charts redraw with new colours). */
export const onThemeChange = (fn) => listeners.add(fn);

function save(theme) {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* storage unavailable: the theme still applies for this visit */
  }
}

/** View Transitions with clip-path animations on its pseudo-elements. */
function supportsViewTransitionInk() {
  return (
    typeof document.startViewTransition === "function" &&
    typeof CSS !== "undefined" &&
    CSS.supports("clip-path", "circle(10px at 0 0)")
  );
}

/** Distance from `p` to the farthest viewport corner, so the ink always covers the whole page. */
function farthestCorner(p) {
  const w = window.innerWidth;
  const h = window.innerHeight;
  return Math.max(Math.hypot(p.x, p.y), Math.hypot(w - p.x, p.y), Math.hypot(p.x, h - p.y), Math.hypot(w - p.x, h - p.y));
}

class ViewTransitionInk {
  constructor(button, onApply) {
    this.button = button;
    this.onApply = onApply;
    this.icon = button ? new ThemeIcon(button) : null;
    this.icon?.set(getTheme());
    this.running = null;
    root.dataset.ink = "view-transition";
  }

  apply(theme) {
    root.dataset.theme = theme;
    this.button?.setAttribute("aria-pressed", String(theme === "dark"));
    this.onApply(theme);
  }

  center() {
    const r = this.button?.getBoundingClientRect();
    return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : { x: innerWidth / 2, y: innerHeight / 2 };
  }

  fade(to) {
    root.classList.add("theme-fade");
    root.style.setProperty("--theme-fade", `${FADE_S}s`);
    this.apply(to);
    this.icon?.set(to);
    window.setTimeout(() => root.classList.remove("theme-fade"), FADE_S * 1000 + 50);
  }

  toggle(point) {
    const to = otherTheme(getTheme());
    if (reducedMotion.matches) return this.fade(to);

    const c = point ?? this.center();
    const reach = farthestCorner(c) + 2;

    // A second click mid-transition: the browser finishes the first one instantly and starts
    // this one from the current state, so rapid toggling never gets stuck. Clicks reach the page
    // during a transition (::view-transition has pointer-events: none in components.css).
    // Other animations (the drifting question pills) would force the browser to re-render the
    // whole incoming page every frame of the reveal: hold them still until it ends.
    root.classList.add("theme-switching");
    const transition = document.startViewTransition(() => this.apply(to));
    this.running = transition;
    this.icon?.morphTo(to, { duration: DURATION_MS / 1000, ease: "power3.out" });
    transition.ready
      .then(() => {
        // clip-path circles are animated on the compositor (GPU): smooth even on large screens.
        root.animate(
          { clipPath: [`circle(0px at ${c.x}px ${c.y}px)`, `circle(${reach}px at ${c.x}px ${c.y}px)`] },
          { duration: DURATION_MS, easing: EASING, pseudoElement: "::view-transition-new(root)" },
        );
      })
      .catch(() => {
        /* transition skipped (e.g. tab hidden): the theme is already applied */
      });
    transition.finished.finally(() => {
      if (this.running !== transition) return; // a newer switch is running
      this.running = null;
      root.classList.remove("theme-switching");
    });
  }
}

export function initTheme(button, canvas) {
  const onApply = (theme) => {
    save(theme);
    button.setAttribute("aria-label", theme === "dark" ? "Light mode" : "Dark mode");
    listeners.forEach((fn) => fn(theme));
  };
  const ink = supportsViewTransitionInk()
    ? new ViewTransitionInk(button, onApply)
    : new InkTransition(canvas, button, { onApply }); // older browsers: WebGL ink with snapshots
  button.setAttribute("aria-pressed", String(getTheme() === "dark"));

  // Keyboard-activated clicks (detail === 0) spread from the button itself.
  button.addEventListener("click", (e) => ink.toggle(e.detail === 0 ? undefined : { x: e.clientX, y: e.clientY }));

  // "T" toggles, unless the user is typing.
  window.addEventListener("keydown", (e) => {
    if (e.repeat || e.metaKey || e.ctrlKey || e.altKey || e.key.toLowerCase() !== "t") return;
    if (e.target instanceof Element && e.target.closest("input, textarea, select, [contenteditable='true']")) return;
    e.preventDefault();
    ink.toggle();
  });
  return ink;
}
