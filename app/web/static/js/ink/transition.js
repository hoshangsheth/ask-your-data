/**
 * Ink theme transition: orchestration.
 *
 * Ported to plain JavaScript from "Ink Bleed" (src/ui/inkTransition.ts): same shader, same
 * timing (1.4 s spread, power3.out, 150 ms fade), same sun/moon morph and button hand-off.
 * Copyright (c) 2026 Codemure. MIT License (see THIRD_PARTY_NOTICES.md).
 *
 * Adapted for a live app, where content changes constantly (answers arrive, panels scroll):
 *  1. Only ONE snapshot is needed: the page in the *other* theme. The live page stays in the old
 *     theme during the spread and is the "from" layer; the overlay draws the snapshot with
 *     alpha = ink coverage on top (pixel-identical to the original two-snapshot blend). When the
 *     ink has covered everything, the page flips underneath and the overlay fades away.
 *  2. The snapshot is pre-captured whenever the page is idle and re-captured after any change.
 *     Constantly moving content (the drifting question pills) is marked data-ink-live like the
 *     toggle: left out of the snapshot, kept live above the overlay during the spread, and given
 *     the new colours when the ink reaches it, so it never makes the snapshot stale.
 *     If it is stale at the moment of the click, it is captured right then and the ink starts
 *     as soon as it is ready: the switch never silently degrades to a plain toggle.
 *  3. A click during a spread finishes the current switch instantly, then starts the next one.
 *  4. Without WebGL2 (or with "reduce motion") a short colour cross-fade is used instead.
 */

import { bumpContentVersion, capturePage, layoutKey, renderScale } from "./capture.js";
import { InkRenderer, inkParams } from "./renderer.js";
import { ThemeIcon } from "./themeIcon.js";

const EASE = "power3.out";
const FADE_OUT = 0.15;
const CSS_FADE_S = 0.45;
const IDLE_CAPTURE_MS = 1500; // wait for the page (and chart animations) to settle
const CLICK_WAIT_MS = 900; // longest a click waits for a fresh snapshot before using the colour fade
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
    this.preparing = false; // capturing on demand after a click
    this.cssFadeTimer = 0;
    this.captureTimer = 0;
    this.capture = null; // in-flight capture: { theme, key, promise }
    this.lastCaptureMs = 0; // how long the last snapshot took (slow pages are captured less often)

    const gsapReady = Boolean(window.gsap);
    this.renderer = gsapReady ? InkRenderer.create(canvas) : null;
    root.dataset.ink = this.renderer ? "webgl" : "css";
    if (!this.renderer) return;

    this.renderer.resize(renderScale());
    this.renderer.watchContext(() => this.complete(), () => this.scheduleCapture(0));
    window.addEventListener("resize", () => {
      this.renderer?.resize(renderScale());
      if (this.frame) this.draw();
      this.scheduleCapture(IDLE_CAPTURE_MS);
    });
    this.watchContent();
    reducedMotion.addEventListener("change", () => this.scheduleCapture(0));
    // Captures pause while the tab is in the background; prepare one as soon as it is back, so the
    // first click after a break doesn't have to wait for it.
    document.addEventListener("visibilitychange", () => !document.hidden && this.scheduleCapture(400));
    void document.fonts.ready.then(() => this.scheduleCapture(IDLE_CAPTURE_MS));
  }

  /**
   * Any content change or scroll makes the snapshot stale (a new capture is scheduled for when
   * the page is idle). Changes made by html2canvas itself (its clone iframe and measuring
   * elements) and by the overlay/toggle are ignored.
   */
  watchContent() {
    // Only changes inside the app count (html2canvas works in temporary nodes outside it).
    const appRoot = document.querySelector(".app");
    const ignored = (node) =>
      !(node instanceof Node) ||
      !appRoot?.contains(node) ||
      (node instanceof Element && (node.closest("[data-ink-live]") || node.classList.contains("ink-canvas")));
    // html2canvas adds and removes its own nodes directly on <body> (clone iframe, font-measuring
    // elements); the app never does, so body-level child changes are never real content changes.
    const byCapture = (r) =>
      (r.type === "childList" && r.target === document.body) ||
      [...r.addedNodes, ...r.removedNodes].some((n) => n instanceof Element && n.classList.contains("html2canvas-container"));
    const changed = () => {
      bumpContentVersion();
      this.scheduleCapture(IDLE_CAPTURE_MS);
    };
    new MutationObserver((records) => {
      if (this.capture) {
        // While capturing, only html2canvas scaffolding changes are expected; real changes still count.
        if (records.some((r) => !ignored(r.target) && !byCapture(r) && !r.target.closest?.(".html2canvas-container"))) changed();
        return;
      }
      if (records.some((r) => !ignored(r.target) && !byCapture(r))) changed();
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["class", "hidden", "open", "value"] });
    document.addEventListener("scroll", changed, { capture: true, passive: true });
  }

  /** Toggle the theme, spreading from `point` (viewport CSS px) or from the toggle button. */
  async toggle(point) {
    if (this.preparing) return; // a click is already waiting for its snapshot
    if (this.frame) this.complete(); // finish the running spread instantly, then start this one
    const to = otherTheme(getTheme());
    const renderer = this.renderer;
    if (!renderer || renderer.isLost || reducedMotion.matches) {
      this.crossFade(to);
      return;
    }

    const center = point ?? this.toggleCenter();
    root.classList.add("theme-switching"); // live elements (pills) rise above the overlay
    if (!renderer.hasValid(to, layoutKey(renderScale()))) {
      // Stale or missing snapshot: take it now (the icon starts turning immediately).
      this.preparing = true;
      this.toggleButton?.classList.add("is-preparing");
      // Never keep the click waiting long: if the snapshot isn't ready in time, use the colour fade
      // now (the capture carries on in the background for the next click).
      let ready = false;
      try {
        ready = await Promise.race([
          this.captureTheme(to).then(() => true),
          new Promise((resolve) => window.setTimeout(() => resolve(false), CLICK_WAIT_MS)),
        ]);
      } catch (err) {
        console.warn("[ink] capture failed; using the colour fade", err);
      } finally {
        this.preparing = false;
        this.toggleButton?.classList.remove("is-preparing");
      }
      if (!ready || !renderer.textures.get(to)) {
        root.classList.remove("theme-switching");
        this.crossFade(to);
        return;
      }
      // Even if the page changed during the capture, the snapshot is at most a moment old:
      // spread it (better than giving up on the animation).
    }
    this.start(to, center);
  }

  start(to, center) {
    const gsap = window.gsap;
    const renderer = this.renderer;
    const maxDist = farthestCorner(center);
    this.frame = { to, center, maxDist, seed: randomSeed() };
    this.state.progress = 0;
    this.state.time = 0;

    renderer.resize(renderScale());
    this.draw();
    gsap.set(renderer.canvas, { opacity: 1 });
    renderer.canvas.classList.add("is-active");

    const duration = inkParams.duration;
    this.icon?.morphTo(to, {
      duration,
      ease: EASE,
      chromeFrom: this.icon.readChrome(),
      chromeTo: this.icon.chromeFor(to),
      chromeDelay: this.inkArrival(center, maxDist, this.toggleCenter()) * duration,
    });
    // Live elements other than the toggle (the drifting pills, left out of the snapshot and
    // drawn above the overlay) take the new theme's colours when the ink front reaches them.
    this.liveTimers = [...document.querySelectorAll("[data-ink-live]:not(#theme-toggle)")].map((el) => {
      const r = el.getBoundingClientRect();
      const at = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      return window.setTimeout(() => (el.dataset.inkTheme = to), this.inkArrival(center, maxDist, at) * duration * 1000);
    });
    this.toggleButton?.setAttribute("aria-pressed", String(to === "dark"));
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

  /** The ink covers the page: flip the live page underneath, then fade the overlay away. */
  finish() {
    const canvas = this.renderer?.canvas;
    const to = this.frame?.to;
    this.tween = null;
    if (to) this.apply(to);
    this.releaseLive(); // the page itself now has the new theme
    this.icon?.settle();
    if (!canvas) return;
    this.fade = window.gsap.to(canvas, { opacity: 0, duration: FADE_OUT, ease: "none", onComplete: () => this.hide() });
  }

  /** Live elements go back to following the page theme. */
  releaseLive() {
    (this.liveTimers ?? []).forEach((t) => window.clearTimeout(t));
    this.liveTimers = [];
    document.querySelectorAll("[data-ink-theme]").forEach((el) => delete el.dataset.inkTheme);
  }

  hide() {
    this.fade = null;
    this.frame = null;
    this.releaseLive();
    this.renderer?.canvas.classList.remove("is-active");
    root.classList.remove("theme-switching"); // moving content resumes
    this.scheduleCapture(250); // the other theme is now the old one: re-capture it soon
  }

  /** Jump to the end of a running spread (a new click, or the GPU context was lost). */
  complete() {
    if (!this.frame) return;
    this.tween?.kill();
    this.fade?.kill();
    const to = this.frame.to;
    this.tween = null;
    if (getTheme() !== to) this.apply(to);
    this.icon?.set(to);
    this.hide();
  }

  /** Plain CSS colour transition (no WebGL2 or reduced motion). */
  crossFade(to) {
    root.classList.add("theme-fade");
    root.style.setProperty("--theme-fade", `${CSS_FADE_S}s`);
    this.apply(to);
    if (reducedMotion.matches) this.icon?.set(to);
    else this.icon?.morphTo(to, { duration: CSS_FADE_S * 1.6, ease: "power2.inOut" });
    window.clearTimeout(this.cssFadeTimer);
    this.cssFadeTimer = window.setTimeout(() => {
      root.classList.remove("theme-fade");
      this.scheduleCapture(0);
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

  // ---- snapshots -----------------------------------------------------------------------------
  scheduleCapture(delay) {
    // A page that takes long to snapshot (a long chat) is captured less eagerly, so the work
    // doesn't keep interrupting scrolling and typing.
    if (delay > 0) delay = Math.max(delay, Math.min(6000, this.lastCaptureMs * 4));
    window.clearTimeout(this.captureTimer);
    this.captureTimer = window.setTimeout(() => {
      // Capturing blocks the main thread briefly: do it when the browser is idle.
      const run = () => {
        if (this.frame || this.preparing || root.classList.contains("theme-fade") || document.hidden) return;
        void this.captureTheme(otherTheme(getTheme())).catch(() => {});
      };
      if ("requestIdleCallback" in window) window.requestIdleCallback(run, { timeout: 5000 });
      else run();
    }, delay);
  }

  /** Capture `theme` unless a valid snapshot exists; shares an in-flight capture of the same state. */
  captureTheme(theme) {
    const renderer = this.renderer;
    if (!renderer || renderer.isLost) return Promise.resolve();
    const key = layoutKey(renderScale());
    if (renderer.hasValid(theme, key)) return Promise.resolve();
    if (this.capture && this.capture.theme === theme && this.capture.key === key) return this.capture.promise;
    const promise = (async () => {
      const snap = await capturePage(theme, renderScale(), renderer.maxTextureSize);
      this.lastCaptureMs = snap.ms;
      renderer.upload(snap); // tagged with the key at capture start; a later change makes it stale again
    })().finally(() => {
      if (this.capture?.promise === promise) this.capture = null;
    });
    this.capture = { theme, key, promise };
    return promise;
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
