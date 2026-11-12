/**
 * Ink theme transition: WebGL2 renderer.
 *
 * Ported to plain JavaScript from "Ink Bleed" (src/gl/renderer.ts).
 * Copyright (c) 2026 Codemure. MIT License (see THIRD_PARTY_NOTICES.md).
 *
 * Owns the overlay canvas, the WebGL2 context, one snapshot texture per theme, and two
 * "composite" textures (ping-pong) that freeze whatever is on screen when a transition is
 * interrupted, so the next ink can spread over it.
 *
 * Frame shape passed to draw(): { from: "light"|"dark"|"composite", to: "light"|"dark",
 *   center: {x, y}, radius, cleanup, maxDist, time, seed: {x, y, angle} }  (CSS px / seconds)
 */

import { createNoiseTexture } from "./noise.js";
import { createProgram } from "./program.js";
import { FULLSCREEN_VERT, INK_FRAG } from "./shaders.js";

/** Look of the ink. duration = seconds for the spread (before a 150 ms fade). */
export const inkParams = { duration: 1.4, tendril: 1, noiseScale: 1, softness: 1.4, drift: 1 };

/** Pigment pooled at the frontier, keyed by the theme being revealed (matches tokens.css --bg). */
const RIM_COLOR = {
  dark: [0.03, 0.035, 0.08], // ink: a touch denser than the dark background
  light: [1.0, 1.0, 1.0], // bleach: a touch brighter than the light background
};

export class InkRenderer {
  /** Returns null when WebGL2 is unavailable. */
  static create(canvas) {
    const gl = canvas.getContext("webgl2", {
      alpha: false, // opaque: CSS opacity fades it onto the live page
      antialias: false,
      depth: false,
      stencil: false,
      premultipliedAlpha: false,
      preserveDrawingBuffer: false,
      powerPreference: "high-performance",
    });
    if (!gl) return null;
    try {
      return new InkRenderer(canvas, gl);
    } catch (err) {
      console.error(err);
      return null;
    }
  }

  constructor(canvas, gl) {
    this.canvas = canvas;
    this.gl = gl;
    this.maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);
    this.textures = new Map(); // theme -> { texture, width, height, scale, key }
    this.composites = [];
    this.activeComposite = -1;
    this.canvasScale = 1;
    this.lost = false;
    this.init();
  }

  init() {
    const gl = this.gl;
    this.program = createProgram(gl, FULLSCREEN_VERT, INK_FRAG);
    this.vao = gl.createVertexArray();
    this.noise = createNoiseTexture(gl);
    this.composites = [];
    this.activeComposite = -1;
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
  }

  /** Context loss/restore hooks; onRestored should re-upload snapshots. */
  watchContext(onLost, onRestored) {
    this.canvas.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      this.lost = true;
      this.textures.clear();
      this.composites = [];
      this.activeComposite = -1;
      onLost();
    });
    this.canvas.addEventListener("webglcontextrestored", () => {
      this.lost = false;
      this.init();
      onRestored();
    });
  }

  get isLost() {
    return this.lost;
  }

  /** Size the backing store to the overlay's CSS box at the given device-pixel ratio. */
  resize(scale) {
    const rect = this.canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width * scale));
    const h = Math.max(1, Math.round(rect.height * scale));
    if (this.canvas.width !== w) this.canvas.width = w;
    if (this.canvas.height !== h) this.canvas.height = h;
    this.canvasScale = rect.width > 0 ? w / rect.width : scale;
  }

  /** Store a page snapshot ({ theme, canvas, scale, key }) as a texture. */
  upload(snapshot) {
    if (this.lost) return;
    const gl = this.gl;
    let entry = this.textures.get(snapshot.theme);
    if (!entry) {
      entry = { texture: this.createTexture(), width: 0, height: 0, scale: 0, key: "" };
      this.textures.set(snapshot.theme, entry);
    }
    gl.bindTexture(gl.TEXTURE_2D, entry.texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, snapshot.canvas);
    entry.width = snapshot.canvas.width;
    entry.height = snapshot.canvas.height;
    entry.scale = snapshot.scale;
    entry.key = snapshot.key;
  }

  /** True when a snapshot for `theme` exists and matches the current page state. */
  hasValid(theme, key) {
    return !this.lost && this.textures.get(theme)?.key === key;
  }

  /** Render `frame` into an offscreen texture usable later as from: "composite". */
  freeze(frame) {
    if (this.lost) return false;
    const gl = this.gl;
    const index = this.activeComposite === 0 ? 1 : 0;
    const target = this.ensureComposite(index);
    gl.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer);
    const ok = this.render(frame);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (!ok) return false;
    target.scrollX = window.scrollX;
    target.scrollY = window.scrollY;
    this.activeComposite = index;
    return true;
  }

  draw(frame) {
    if (!this.lost) this.render(frame);
  }

  // ---- internals ----------------------------------------------------------------------------
  createTexture() {
    const gl = this.gl;
    const texture = gl.createTexture();
    if (!texture) throw new Error("createTexture failed");
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return texture;
  }

  ensureComposite(index) {
    const gl = this.gl;
    const { width, height } = this.canvas;
    let c = this.composites[index];
    if (!c) {
      const framebuffer = gl.createFramebuffer();
      if (!framebuffer) throw new Error("createFramebuffer failed");
      c = { texture: this.createTexture(), framebuffer, width: 0, height: 0, scrollX: 0, scrollY: 0 };
      this.composites[index] = c;
    }
    if (c.width !== width || c.height !== height) {
      gl.bindTexture(gl.TEXTURE_2D, c.texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.bindFramebuffer(gl.FRAMEBUFFER, c.framebuffer);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, c.texture, 0);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      c.width = width;
      c.height = height;
    }
    return c;
  }

  /** How to read a source texture: size, scale ratio, scroll offset, y-flip. */
  sampler(source) {
    if (source === "composite") {
      const c = this.composites[this.activeComposite];
      if (!c) return null;
      return {
        texture: c.texture, width: c.width, height: c.height, ratio: 1,
        offsetX: Math.round((window.scrollX - c.scrollX) * this.canvasScale),
        offsetY: Math.round((window.scrollY - c.scrollY) * this.canvasScale),
        flipY: true,
      };
    }
    const t = this.textures.get(source);
    if (!t) return null;
    return {
      texture: t.texture, width: t.width, height: t.height, ratio: t.scale / this.canvasScale,
      offsetX: Math.floor(window.scrollX * t.scale + 0.5),
      offsetY: Math.floor(window.scrollY * t.scale + 0.5),
      flipY: false,
    };
  }

  render(frame) {
    const from = this.sampler(frame.from);
    const to = this.sampler(frame.to);
    if (!from || !to) return false;

    const gl = this.gl;
    const { program, uniform } = this.program;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.useProgram(program);
    gl.bindVertexArray(this.vao);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, from.texture);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, to.texture);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, this.noise);

    gl.uniform1i(uniform("uFrom"), 0);
    gl.uniform1i(uniform("uTo"), 1);
    gl.uniform1i(uniform("uNoise"), 2);
    gl.uniform2f(uniform("uFromSize"), from.width, from.height);
    gl.uniform2f(uniform("uToSize"), to.width, to.height);
    gl.uniform4f(uniform("uFromMap"), from.ratio, from.offsetX, from.offsetY, from.flipY ? 1 : 0);
    gl.uniform4f(uniform("uToMap"), to.ratio, to.offsetX, to.offsetY, to.flipY ? 1 : 0);
    gl.uniform1f(uniform("uCanvasScale"), this.canvasScale);
    gl.uniform2f(uniform("uRes"), this.canvas.width, this.canvas.height);
    gl.uniform2f(uniform("uCenter"), frame.center.x, frame.center.y);
    gl.uniform1f(uniform("uRadius"), frame.radius);
    gl.uniform1f(uniform("uCleanup"), frame.cleanup);
    gl.uniform1f(uniform("uTime"), frame.time);
    gl.uniform1f(uniform("uRef"), Math.max(this.canvas.width, this.canvas.height) / this.canvasScale);
    gl.uniform2f(uniform("uSeed"), frame.seed.x, frame.seed.y);
    const cos = Math.cos(frame.seed.angle);
    const sin = Math.sin(frame.seed.angle);
    gl.uniformMatrix2fv(uniform("uSeedRot"), false, [cos, sin, -sin, cos]);

    gl.uniform1f(uniform("uTendril"), inkParams.tendril);
    gl.uniform1f(uniform("uNoiseScale"), inkParams.noiseScale);
    gl.uniform1f(uniform("uSoftness"), inkParams.softness);
    gl.uniform1f(uniform("uDrift"), inkParams.drift);
    gl.uniform3fv(uniform("uRimColor"), RIM_COLOR[frame.to]);

    gl.drawArrays(gl.TRIANGLES, 0, 3);
    return true;
  }
}
