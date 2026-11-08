"use client";

// Lattice field (spec §4): two faint 2D lattices drifting against each other so a moiré pattern
// emerges; the pointer acts as a "measurement" that collapses the fringes nearby. Plain WebGL,
// no library. Budget: <= 30 fps, paused while the tab is hidden, opacity <= 12 %.
// Falls back to a static SVG lattice without WebGL or under prefers-reduced-motion.

import { useEffect, useRef, useState } from "react";

const MAX_ALPHA = 0.12;
const FRAME_MS = 1000 / 30;

const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`;
const FRAG = `
precision mediump float;
uniform vec2 res; uniform float t; uniform float density; uniform float dpr; uniform vec2 mouse;
uniform vec3 tint; uniform float maxAlpha;
mat2 rot(float a){ float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }
float dots(vec2 p, float cell){
  vec2 f = fract(p / cell) - 0.5;
  return smoothstep(0.16, 0.06, length(f));
}
void main(){
  vec2 uv = gl_FragCoord.xy;
  float cell = 34.0 * dpr / density; // 34 CSS px at density 1
  vec2 a = rot(0.0 + t * 0.010) * (uv + vec2(t * 6.0, 0.0));
  vec2 b = rot(0.12 - t * 0.006) * (uv - vec2(0.0, t * 5.0));
  float m = dots(a, cell) * dots(b, cell * 1.03) + 0.35 * (dots(a, cell) + dots(b, cell * 1.03));
  float d = length(uv - mouse);
  float collapse = 1.0 - 0.85 * exp(-(d * d) / (2.0 * 140.0 * 140.0));
  float v = clamp(m * collapse, 0.0, 1.0) * maxAlpha;
  gl_FragColor = vec4(tint * v, v);
}`;

function cssRgb(name: string): [number, number, number] {
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return [0.2, 0.9, 0.8];
  const raw = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  ctx.fillStyle = "#36e2c8";
  ctx.fillStyle = raw || "#36e2c8";
  ctx.fillRect(0, 0, 1, 1);
  const [r = 0, g = 0, b = 0] = ctx.getImageData(0, 0, 1, 1).data;
  return [r / 255, g / 255, b / 255];
}

function num(name: string, fallback: number): number {
  const n = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue(`--${name}`));
  return Number.isNaN(n) ? fallback : n;
}

/** Static lattice for reduced motion or a missing WebGL context. */
function SvgLattice() {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      style={{ position: "fixed", inset: 0, width: "100%", height: "100%", zIndex: -1, pointerEvents: "none" }}
    >
      <defs>
        <pattern id="lat-a" width="34" height="34" patternUnits="userSpaceOnUse">
          <circle cx="17" cy="17" r="1.6" fill="var(--q)" />
        </pattern>
        <pattern id="lat-b" width="35" height="35" patternUnits="userSpaceOnUse" patternTransform="rotate(7)">
          <circle cx="17" cy="17" r="1.6" fill="var(--q)" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#lat-a)" opacity="0.06" />
      <rect width="100%" height="100%" fill="url(#lat-b)" opacity="0.06" />
    </svg>
  );
}

export function LatticeField() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const gl = el.getContext("webgl", { alpha: true, antialias: false, premultipliedAlpha: true });
    if (reduced.matches || !gl) {
      setFallback(true);
      return;
    }
    const compile = (type: number, src: string) => {
      const s = gl.createShader(type);
      if (!s) return null;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
    };
    const vs = compile(gl.VERTEX_SHADER, VERT);
    const fs = compile(gl.FRAGMENT_SHADER, FRAG);
    const prog = gl.createProgram();
    if (!vs || !fs || !prog) {
      setFallback(true);
      return;
    }
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      setFallback(true);
      return;
    }
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = (n: string) => gl.getUniformLocation(prog, n);
    const uRes = u("res");
    const uT = u("t");
    const uDensity = u("density");
    const uDpr = u("dpr");
    const uMouse = u("mouse");
    const uTint = u("tint");
    const uAlpha = u("maxAlpha");

    const dpr = Math.min(window.devicePixelRatio || 1, 1) * 0.5; // a soft background: half resolution is enough
    const resize = () => {
      el.width = Math.ceil(window.innerWidth * dpr);
      el.height = Math.ceil(window.innerHeight * dpr);
      gl.viewport(0, 0, el.width, el.height);
    };
    resize();
    window.addEventListener("resize", resize);

    let mouse: [number, number] = [-9999, -9999];
    const onMove = (e: PointerEvent) => {
      mouse = [e.clientX * dpr, (window.innerHeight - e.clientY) * dpr];
    };
    window.addEventListener("pointermove", onMove, { passive: true });

    let raf = 0;
    let last = 0;
    let clock = 0;
    let tint = cssRgb("q");
    let frames = 0;
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (now - last < FRAME_MS) return;
      clock += (((now - last) / 1000) * num("bg-speed", 1)) / Math.max(num("motion-scale", 1), 0.1);
      last = now;
      if (frames++ % 30 === 0) tint = cssRgb("q"); // follows the tweak panel
      gl.uniform2f(uRes, el.width, el.height);
      gl.uniform1f(uT, clock);
      gl.uniform1f(uDensity, num("bg-density", 1));
      gl.uniform1f(uDpr, dpr);
      gl.uniform2f(uMouse, mouse[0], mouse[1]);
      gl.uniform3f(uTint, tint[0], tint[1], tint[2]);
      gl.uniform1f(uAlpha, MAX_ALPHA);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
    const start = () => {
      if (!raf) {
        last = performance.now();
        raf = requestAnimationFrame(draw);
      }
    };
    const stop = () => {
      cancelAnimationFrame(raf);
      raf = 0;
    };
    const onVisibility = () => (document.hidden ? stop() : start());
    const onReduced = () => {
      if (reduced.matches) {
        stop();
        setFallback(true);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    reduced.addEventListener("change", onReduced);
    // Start once the page has loaded and gone idle, so the shader never competes with hydration.
    const startLater = () => {
      const idle = (window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }).requestIdleCallback;
      starter = window.setTimeout(() => (idle ? idle(start, { timeout: 3000 }) : start()), 1500);
    };
    let starter = 0;
    if (document.readyState === "complete") startLater();
    else window.addEventListener("load", startLater, { once: true });

    return () => {
      window.clearTimeout(starter);
      window.removeEventListener("load", startLater);
      stop();
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("visibilitychange", onVisibility);
      reduced.removeEventListener("change", onReduced);
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }, []);

  if (fallback) return <SvgLattice />;
  return (
    <canvas
      ref={canvas}
      aria-hidden="true"
      style={{ position: "fixed", inset: 0, width: "100%", height: "100%", zIndex: -1, pointerEvents: "none" }}
    />
  );
}
