/**
 * Ink theme transition: the sun <-> moon toggle icon.
 *
 * Ported to plain JavaScript from "Ink Bleed" (src/ui/themeIcon.ts).
 * Copyright (c) 2026 Codemure. MIT License (see THIRD_PARTY_NOTICES.md).
 *
 * The toggle sits above the ink overlay (it is hidden in snapshots), so it animates on its own,
 * in step with the ink: the sun body morphs into a crescent, rays retract one by one, and the
 * button keeps its old colours until the ink reaches it. Needs GSAP + MorphSVGPlugin (globals,
 * loaded in index.html).
 */

const SUN = "M12 7a5 5 0 1 1 0 10a5 5 0 1 1 0-10z";
const MOON = "M20.5 13.2A8.5 8.5 0 1 1 10.8 3.5a7.2 7.2 0 0 0 9.7 9.7z";

const POSE = {
  light: { body: SUN, rays: { scale: 1, opacity: 1, rotation: 0 }, icon: 0 },
  dark: { body: MOON, rays: { scale: 0.2, opacity: 0, rotation: -60 }, icon: -25 },
};

export class ThemeIcon {
  constructor(button) {
    this.gsap = window.gsap;
    if (this.gsap && window.MorphSVGPlugin) this.gsap.registerPlugin(window.MorphSVGPlugin);
    this.button = button;
    this.icon = button.querySelector("svg");
    this.body = button.querySelector(".theme-toggle__body");
    this.rays = Array.from(button.querySelectorAll(".theme-toggle__rays line"));
    this.timeline = null;
  }

  kill() {
    this.timeline?.kill();
    this.timeline = null;
  }

  /** Current chrome colours as rendered (call before flipping the theme). */
  readChrome() {
    const cs = getComputedStyle(this.button);
    return { backgroundColor: cs.backgroundColor, borderColor: cs.borderTopColor, color: cs.color };
  }

  /** Jump to a theme's pose without animating. */
  set(theme) {
    const gsap = this.gsap;
    this.kill();
    if (!gsap) {
      this.body?.setAttribute("d", POSE[theme].body);
      return;
    }
    const pose = POSE[theme];
    if (this.body) gsap.set(this.body, window.MorphSVGPlugin ? { morphSVG: pose.body } : { attr: { d: pose.body } });
    gsap.set(this.rays, { ...pose.rays, svgOrigin: "12 12" });
    if (this.icon) gsap.set(this.icon, { rotation: pose.icon, transformOrigin: "50% 50%" });
    gsap.set(this.button, { clearProps: "backgroundColor,borderColor,color" });
  }

  /** Animate to a theme's pose. opts: { duration, ease, chromeFrom?, chromeDelay? } */
  morphTo(theme, opts) {
    const gsap = this.gsap;
    if (!gsap || !window.MorphSVGPlugin) {
      this.set(theme);
      return;
    }
    this.kill();
    const pose = POSE[theme];
    const tl = gsap.timeline({ defaults: { duration: opts.duration, ease: opts.ease } });
    if (this.body) tl.to(this.body, { morphSVG: { shape: pose.body, shapeIndex: "auto" } }, 0);
    tl.to(this.rays, { ...pose.rays, svgOrigin: "12 12", stagger: opts.duration * 0.035 }, 0);
    if (this.icon) tl.to(this.icon, { rotation: pose.icon, transformOrigin: "50% 50%" }, 0);

    if (opts.chromeFrom) {
      // Hold the old colours (the live page already has the new theme) until the ink arrives.
      Object.assign(this.button.style, opts.chromeFrom);
      tl.to(
        this.button,
        {
          backgroundColor: () => this.targetChrome().backgroundColor,
          borderColor: () => this.targetChrome().borderColor,
          color: () => this.targetChrome().color,
          duration: Math.min(0.18, opts.duration * 0.15),
          ease: "power1.out",
          onComplete: () => gsap.set(this.button, { clearProps: "backgroundColor,borderColor,color" }),
        },
        opts.chromeDelay ?? 0,
      );
    } else {
      gsap.set(this.button, { clearProps: "backgroundColor,borderColor,color" });
    }
    this.timeline = tl;
  }

  /** Stylesheet colours for the current (already flipped) theme. */
  targetChrome() {
    const saved = this.button.getAttribute("style") ?? "";
    this.button.style.removeProperty("background-color");
    this.button.style.removeProperty("border-color");
    this.button.style.removeProperty("color");
    const target = this.readChrome();
    this.button.setAttribute("style", saved);
    return target;
  }
}
