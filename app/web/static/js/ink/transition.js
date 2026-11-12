/**
 * Ink theme transition: orchestration.
 *
 * Ported to plain JavaScript from "Ink Bleed" (src/ui/inkTransition.ts).
 * Copyright (c) 2026 Codemure. MIT License (see THIRD_PARTY_NOTICES.md).
 *
 *  1. keeps fresh snapshots of both themes on the GPU (re-captured when the page changes)
 *  2. on toggle: covers the page with the "from" image, flips the live page underneath,
 *     spreads the ink from the click point, then fades the overlay onto the flipped page
 *  3. if toggled mid-spread: freezes the current frame and spreads the next ink over it
 *  4. falls back to a CSS colour cross-fade without WebGL2, with reduced motion, or when
 *     snapshots are not ready yet
 *
 * Changes for this app: snapshots are invalidated by any content change or scroll (chat
 * answers arrive constantly), and captures wait for the page to be idle.
 */

import { bumpContentVersion, capturePage, layoutKey, renderScale } from "./capture.js";
import { InkRenderer, inkParams } from "./renderer.js";
import { ThemeIcon } from "./themeIcon.js";

const EASE = "power3.out";
const FADE_OUT = 0.15;
const CSS_FADE_S = 0.45;
const IDLE_CAPTURE_MS = 1200; // wait for the page (and chart animations) to settle
export const SPREAD = { growth: 0.7, cleanupFrom: 0.45, cleanupReach: 0.4, cleanupPow: 2 };

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const root = document.documentElement;

export const getTheme = () => (root.dataset.theme === "dark" ? "dark" : "light");
export const otherTheme = (t) => (t === "dark" ? "light" : "dark");

export class InkTransition {
  /** @param onApply called with the new theme right after the live page flips. */
  constructor(canvas, toggleButton, { onApply } = {}) {
    this.toggleButton = toggleButton;
    this.onApply = onApply ?? (() => {});
    this.icon = toggleButton ? new ThemeIcon(toggleButton) : null;
    this.icon?.set(getTheme());
    this.state = { progress: 0, time: 0 };
    this.tween = null;
    this.fade = null;
    this.frame = null;
    this.cssFadeTimer = 0;
    this.captureGen = 0;
    this.capturing = false;
    this.captureQueued = false;
    this.captureTimer = 0;

    const gsapReady = Boolean(window.gsap);
    this.renderer = gsapReady ? InkRenderer.create(canvas) : null;
    root.dataset.ink = this.renderer ? "webgl" : "css";
    if (!this.renderer) return;

    this.renderer.resize(renderScale());
    this.renderer.watchContext(() => this.cancel(), () => this.scheduleCapture(0));
    window.addEventListener("resize", () => {
      this.renderer?.resize(renderScale());
      if (this.frame) this.draw();
      this.scheduleCapture(IDLE_CAPTURE_MS);
    });
    this.watchContent();
    reducedMotion.addEventListener("change", () => this.scheduleCapture(0));
    void document.fonts.ready.then(() => this.scheduleCapture(IDLE_CAPTURE_MS));
  }

  /**
   * Invalidate snapshots when the page content changes or anything scrolls.
   * Changes made by the capture itself are ignored: html2canvas temporarily adds an iframe and
   * font-measuring elements to the page, which would otherwise make every snapshot stale the
   * moment it is taken (an endless capture loop).
   */
  watchContent() {
    const ignoredTarget = (node) =>
      node instanceof Element && (node.closest("[data-ink-live]") || node.classList.contains("ink-canvas"));
    const byCapture = (r) =>
      [...r.addedNodes, ...r.removedNodes].some((n) => n instanceof Element && n.classList.contains("html2canvas-container"));
    const changed = () => {
      bumpContentVersion();
      this.scheduleCapture(IDLE_CAPTURE_MS);
    };
    new MutationObserver((records) => {
      if (this.capturing) return; // everything that changes during a capture is html2canvas's own scaffolding
      if (records.some((r) => !ignoredTarget(r.target) && !byCapture(r))) changed();
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["class", "hidden", "open", "value"] });
    document.addEventListener("scroll", changed, { capture: true, passive: true });
  }

  /** Toggle the theme, spreading from `point` (viewport CSS px) or from the toggle button. */
  toggle(point) {
    const gsap = window.gsap;
    const to = otherTheme(getTheme());
    const renderer = this.renderer;
    const scale = renderScale();
    const key = layoutKey(scale);
    const interrupting = this.frame !== null;

    const canAnimate =
      renderer !== null &&
      !renderer.isLost &&
      !reducedMotion.matches &&
      renderer.hasValid(to, key) &&
      (interrupting || renderer.hasValid(getTheme(), key));

    if (!canAnimate) {
      this.cancel();
      this.crossFade(to);
      if (renderer && !reducedMotion.matches) this.scheduleCapture(IDLE_CAPTURE_MS);
      return;
    }

    // Interrupted: freeze exactly what is on screen and spread the new ink over it.
    let from = getTheme();
    if (interrupting) {
      this.tween?.kill();
      this.fade?.kill();
      this.tween = this.fade = null;
      renderer.resize(scale);
      const frozen = this.currentFrame();
      from = frozen && renderer.freeze(frozen) ? "composite" : getTheme();
    }

    const center = point ?? this.toggleCenter();
    const maxDist = farthestCorner(center);
    this.frame = { from, to, center, maxDist, seed: randomSeed() };
    this.state.progress = 0;
    this.state.time = 0;

    const chromeFrom = this.icon?.readChrome();
    renderer.resize(scale);
    this.draw();
    // Same task: the overlay (showing "from") and the flipped page reach the screen together.
    gsap.set(renderer.canvas, { opacity: 1 });
    renderer.canvas.classList.add("is-active");
    this.apply(to);

    const duration = inkParams.duration;
    this.icon?.morphTo(to, {
      duration,
      ease: EASE,
      chromeFrom,
      chromeDelay: this.inkArrival(center, maxDist, this.toggleCenter()) * duration,
    });
    this.tween = gsap.to(this.state, {
      progress: 1,
      duration,
      ease: EASE,
      onUpdate: () => {
        this.state.time = this.tween?.time() ?? 0;
        this.draw();
      },
      onComplete: () => this.finish(),
    });
  }

  apply(theme) {
    root.dataset.theme = theme;
    this.toggleButton?.setAttribute("aria-pressed", String(theme === "dark"));
    this.onApply(theme);
  }

  currentFrame() {
    if (!this.frame) return null;
    const { progress, time } = this.state;
    const { maxDist } = this.frame;
    const linear = Math.min(1, time / inkParams.duration);
    const ramp = Math.max(0, (linear - SPREAD.cleanupFrom) / (1 - SPREAD.cleanupFrom));
    const cleanup =
      ramp ** SPREAD.cleanupPow * maxDist * SPREAD.cleanupReach + Math.max(0, (linear - 0.97) / 0.03) * maxDist;
    return { ...this.frame, progress, time, radius: progress * maxDist * SPREAD.growth, cleanup };
  }

  draw() {
    const frame = this.currentFrame();
    if (this.renderer && frame) this.renderer.draw(frame);
  }

  finish() {
    const canvas = this.renderer?.canvas;
    this.tween = null;
    if (!canvas) return;
    this.fade = window.gsap.to(canvas, { opacity: 0, duration: FADE_OUT, ease: "none", onComplete: () => this.hide() });
  }

  hide() {
    this.fade = null;
    this.frame = null;
    this.renderer?.canvas.classList.remove("is-active");
    if (this.captureQueued) this.scheduleCapture(0);
  }

  cancel() {
    if (!this.frame) return;
    this.tween?.kill();
    this.fade?.kill();
    this.tween = null;
    this.hide();
  }

  /** Plain CSS colour transition (no WebGL2, reduced motion, or snapshots not ready yet). */
  crossFade(to) {
    root.classList.add("theme-fade");
    root.style.setProperty("--theme-fade", `${CSS_FADE_S}s`);
    this.apply(to);
    if (reducedMotion.matches) this.icon?.set(to);
    else this.icon?.morphTo(to, { duration: CSS_FADE_S * 1.6, ease: "power2.inOut" });
    window.clearTimeout(this.cssFadeTimer);
    this.cssFadeTimer = window.setTimeout(() => {
      root.classList.remove("theme-fade");
      if (this.captureQueued) this.scheduleCapture(0);
    }, CSS_FADE_S * 1000 + 50);
  }

  /** Fraction of the duration at which the ink front reaches `target`. */
  inkArrival(center, maxDist, target) {
    const dist = Math.hypot(target.x - center.x, target.y - center.y);
    if (dist < 28) return 0;
    const p = Math.min(1, dist / (maxDist * SPREAD.growth * 1.15));
    return Math.min(0.85, 1 - Math.cbrt(1 - p));
  }

  toggleCenter() {
    const r = this.toggleButton?.getBoundingClientRect();
    if (!r) return { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }

  // ---- capture scheduling -------------------------------------------------------------------
  scheduleCapture(delay) {
    window.clearTimeout(this.captureTimer);
    this.captureTimer = window.setTimeout(() => {
      // Capturing blocks the main thread briefly: do it when the browser is idle.
      if ("requestIdleCallback" in window) window.requestIdleCallback(() => void this.captureAll(), { timeout: 2000 });
      else void this.captureAll();
    }, delay);
  }

  async captureAll() {
    const renderer = this.renderer;
    if (!renderer || renderer.isLost || reducedMotion.matches || document.hidden) return;
    if (this.capturing || this.frame || root.classList.contains("theme-fade") || root.dataset.busy === "1") {
      this.captureQueued = true;
      return;
    }
    const scale = renderScale();
    const key = layoutKey(scale);
    const current = getTheme();
    const themes = [current, otherTheme(current)].filter((t) => !renderer.hasValid(t, key));
    this.captureQueued = false;
    if (themes.length === 0) return;

    const gen = ++this.captureGen;
    this.capturing = true;
    try {
      for (const theme of themes) {
        const snap = await capturePage(theme, scale, renderer.maxTextureSize);
        if (gen !== this.captureGen) return;
        if (snap.key !== layoutKey(renderScale())) {
          this.captureQueued = true; // page changed while capturing: snapshot already stale
          break;
        }
        renderer.upload(snap);
      }
    } catch (err) {
      console.warn("[ink] capture failed; using the colour fade instead", err);
    } finally {
      this.capturing = false;
    }
    if (this.captureQueued) this.scheduleCapture(IDLE_CAPTURE_MS);
  }
}

function farthestCorner(p) {
  const w = root.clientWidth;
  const h = root.clientHeight;
  return Math.max(Math.hypot(p.x, p.y), Math.hypot(w - p.x, p.y), Math.hypot(p.x, h - p.y), Math.hypot(w - p.x, h - p.y)) + 4;
}

function randomSeed() {
  return { x: Math.random() * 64 - 32, y: Math.random() * 64 - 32, angle: Math.random() * Math.PI * 2 };
}
