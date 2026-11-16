/**
 * Ink theme transition: page snapshots for each theme.
 *
 * Ported to plain JavaScript from "Ink Bleed" (src/capture/capture.ts), with one addition for
 * this app: a content "version" in the layout key. The original only re-captured when the page
 * size changed; here the content changes all the time (chat answers, scrolled panels), so any
 * DOM change or scroll bumps the version and invalidates the snapshots.
 * Copyright (c) 2026 Codemure. MIT License (see THIRD_PARTY_NOTICES.md).
 *
 * html2canvas renders a *clone* of the page with the target theme applied (onclone), so the live
 * page never flickers while snapshots are taken. It is loaded lazily from a CDN.
 */

const HTML2CANVAS_URL = "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js";

/** Page background per theme (must match --bg in css/tokens.css). */
const BACKGROUND = { light: "#f6f7fb", dark: "#0c0e1a" };

let contentVersion = 0;
let html2canvasPromise = null;

/** Mark the page content as changed; existing snapshots become stale. */
export function bumpContentVersion() {
  contentVersion += 1;
}

/** Device-pixel ratio for snapshots and the overlay (capped: capture cost grows with pixels). */
export function renderScale() {
  const cap = window.matchMedia("(pointer: coarse)").matches ? 1.25 : 1.5;
  return Math.min(window.devicePixelRatio || 1, cap);
}

function documentSize() {
  const el = document.documentElement;
  return { width: el.clientWidth, height: Math.max(el.scrollHeight, el.clientHeight) };
}

/** Identifies the page state a snapshot is valid for: size, scale and content version. */
export function layoutKey(scale) {
  const { width, height } = documentSize();
  return `${width}x${height}@${scale}#${contentVersion}`;
}

function loadHtml2canvas() {
  if (window.html2canvas) return Promise.resolve(window.html2canvas);
  html2canvasPromise ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = HTML2CANVAS_URL;
    s.async = true;
    s.onload = () => resolve(window.html2canvas);
    s.onerror = () => reject(new Error("could not load html2canvas"));
    document.head.appendChild(s);
  });
  return html2canvasPromise;
}

/**
 * Remember every scrolled element (the chat thread, the views) so the clone can show the same
 * scroll positions. Marks them with data-ink-scroll; returns the positions by index.
 */
function markScrolled() {
  const positions = [];
  document.querySelectorAll("body *").forEach((el) => {
    if (el.scrollTop > 0 || el.scrollLeft > 0) {
      el.dataset.inkScroll = String(positions.length);
      positions.push([el.scrollLeft, el.scrollTop]);
    }
  });
  return positions;
}

/** Apply recorded scroll positions in the cloned document, instantly (no smooth scrolling). */
function restoreScroll(doc, positions) {
  const style = doc.createElement("style");
  style.textContent = "*, *::before, *::after { scroll-behavior: auto !important; }";
  doc.head.appendChild(style);
  doc.querySelectorAll("[data-ink-scroll]").forEach((el) => {
    const [left, top] = positions[Number(el.dataset.inkScroll)] ?? [0, 0];
    el.scrollLeft = left;
    el.scrollTop = top;
  });
}

/**
 * Mark what the snapshot doesn't need to draw, so html2canvas (which styles and paints every
 * element it is given) has far less work on a long chat:
 *   - chat messages and dashboard cards scrolled out of view become empty boxes of the same size
 *     (the layout, and so every scroll position, stays exactly the same);
 *   - views that aren't shown, closed dialogs and hidden tab panels are dropped (they take no space).
 * Returns the placeholder sizes by index.
 */
function markSkippable() {
  const sizes = [];
  const vh = window.innerHeight;
  document.querySelectorAll(".thread-inner > *, .chart-grid > *, .saved-grid > *, .kpi-grid > *").forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.height > 0 && (r.bottom < -40 || r.top > vh + 40)) {
      el.dataset.inkSkip = String(sizes.length);
      sizes.push([r.width, r.height]);
    }
  });
  return sizes;
}

/**
 * Used while html2canvas copies the page (copying and measuring every element is most of its
 * cost): skip hidden things entirely, and the *contents* of off-screen blocks, which are copied
 * empty and given their real size in sizeSkipped(), so nothing on screen moves.
 */
function skipWhileCopying(el) {
  if (el.matches?.(".view:not(.is-active), dialog:not([open]), [hidden]")) return true;
  // Contents of off-screen blocks, and of live elements (pills, the toggle) the snapshot hides anyway.
  return Boolean(el.parentElement?.closest("[data-ink-skip], [data-ink-live]"));
}

function sizeSkipped(doc, sizes) {
  doc.querySelectorAll("[data-ink-skip]").forEach((el) => {
    const [w, h] = sizes[Number(el.dataset.inkSkip)] ?? [0, 0];
    el.style.cssText += `;width:${w}px;height:${h}px;min-height:${h}px;flex:none;box-sizing:border-box`;
  });
}

/** Snapshot the page as it would look in `theme`. Returns { theme, canvas, scale, key, ms }. */
export async function capturePage(theme, scale, maxTextureSize) {
  const t0 = performance.now();
  const key = layoutKey(scale);
  const { width, height } = documentSize();
  const safeScale = Math.min(scale, maxTextureSize / width, maxTextureSize / height);
  const html2canvas = await loadHtml2canvas();
  const positions = markScrolled();
  const sizes = markSkippable();
  try {
    return await render(html2canvas, theme, safeScale, width, height, positions, sizes, key, t0);
  } finally {
    document.querySelectorAll("[data-ink-scroll]").forEach((el) => delete el.dataset.inkScroll);
    document.querySelectorAll("[data-ink-skip]").forEach((el) => delete el.dataset.inkSkip);
  }
}

async function render(html2canvas, theme, safeScale, width, height, positions, sizes, key, t0) {
  const canvas = await html2canvas(document.body, {
    scale: safeScale,
    backgroundColor: BACKGROUND[theme],
    x: 0,
    y: 0,
    width,
    height,
    scrollX: 0,
    scrollY: 0,
    windowWidth: width,
    windowHeight: document.documentElement.clientHeight,
    logging: false,
    useCORS: true,
    ignoreElements: skipWhileCopying,
    onclone: (doc) => {
      doc.documentElement.dataset.theme = theme;
      sizeSkipped(doc, sizes); // before the scroll positions: those need the final layout
      restoreScroll(doc, positions);
      // The live toggle is drawn above the overlay, so leave a hole for it in the snapshot.
      doc.querySelectorAll("[data-ink-live]").forEach((el) => {
        el.style.visibility = "hidden";
      });
    },
  });
  return { theme, canvas, scale: safeScale, key, ms: performance.now() - t0 };
}
