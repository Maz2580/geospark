/* GeoSpark — liquid-metal logo.
 *
 * Fills the logo's shape with a flowing liquid-metal animation (WebGL). Usage:
 *
 *   <span class="logo" data-liquid-logo><img src="/assets/logo.svg" alt="GeoSpark"></span>
 *
 * The <img> is the fallback and stays in the page for screen readers: without WebGL, with
 * reduced motion (one still frame), or if the GPU context is lost, people see the plain logo.
 * The animation pauses when the logo is off screen or the tab is hidden, and speeds up on hover.
 *
 * The shader is adapted from Liquid Logo by Alan Ang (MIT, https://github.com/collidingScopes/liquid-logo),
 * itself based on XorDev's "Plasma". Changes here: the mask's own texel size for edge detection
 * (the original used the canvas size), anti-aliased edges instead of a hard cut-out, a guard against
 * divide-by-zero flicker, a colour ramp in GeoSpark's palette, no shader fetches, HiDPI sizing, and
 * pausing when not visible.
 */
(() => {
  'use strict';

  const VERTEX = 'attribute vec2 a_pos; void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }';

  const FRAGMENT = `
precision highp float;
uniform vec2 u_res;
uniform vec2 u_texel;
uniform float u_time;
uniform sampler2D u_mask;
uniform float u_iterations, u_scale, u_dotFactor, u_dotMultiplier, u_vOffset;
uniform float u_intensity, u_expFactor, u_colorShift, u_noise, u_interact, u_tint;
uniform vec3 u_colorFactors, u_rampLow, u_rampMid, u_rampHigh, u_contrast;

vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(i.z + vec4(0.0, i1.z, i2.z, 1.0))
         + i.y + vec4(0.0, i1.y, i2.y, 1.0)) + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}

float edgeAt(vec2 uv) {
  float c = texture2D(u_mask, uv).a;
  float d = abs(c - texture2D(u_mask, uv - vec2(u_texel.x, 0.0)).a)
          + abs(c - texture2D(u_mask, uv + vec2(u_texel.x, 0.0)).a)
          + abs(c - texture2D(u_mask, uv - vec2(0.0, u_texel.y)).a)
          + abs(c - texture2D(u_mask, uv + vec2(0.0, u_texel.y)).a);
  return smoothstep(0.0, 0.2, d);
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_res;
  vec2 maskUV = vec2(uv.x, 1.0 - uv.y);
  float coverage = texture2D(u_mask, maskUV).a;
  if (coverage < 0.004) { gl_FragColor = vec4(0.0); return; }

  float edge = edgeAt(maskUV) * u_interact;
  vec2 p = (gl_FragCoord.xy * 2.0 - u_res) / u_res.y;
  float lx = abs(u_dotFactor - dot(p, p)) * u_dotMultiplier;
  vec2 v = p * (1.0 - lx) / u_scale;
  v += vec2(sin(edge * 10.0), cos(edge * 8.0)) * edge * 20.0;
  float flow = snoise(vec3(p * 2.0, u_time * 0.15)) * u_noise;
  v += vec2(flow, flow * 0.7);

  vec4 o = vec4(0.0);
  for (float i = 0.0; i < 16.0; i++) {
    if (i >= u_iterations) break;
    float k = i + 1.0;
    vec2 offset = cos(v.yx * k + vec2(0.0, k) + u_time) / k + u_vOffset;
    if (edge > 0.1) offset *= 1.0 + edge * 4.0;
    v += offset;
    o += (sin(vec4(v.x, v.y, v.y, v.x)) + 1.0) * abs(v.x - v.y) * u_intensity;
  }
  o = mix(o, o.wxyz, u_colorShift);

  // tanh(gradient / o), guarded so o == 0 can't produce NaN flicker
  vec4 ratio = exp(p.y * vec4(u_colorFactors, 0.0)) * exp(-u_expFactor * lx) / max(o, vec4(1e-4));
  vec4 e = exp(2.0 * min(ratio, vec4(20.0)));
  vec3 col = clamp(((e - 1.0) / (e + 1.0)).rgb, 0.0, 1.0);

  // Map brightness onto the brand ramp, then add a metallic rim along the shape's edges
  float lum = dot(col, vec3(0.299, 0.587, 0.114));
  lum = pow(smoothstep(u_contrast.x, u_contrast.y, lum), u_contrast.z);  // keep dark troughs, not a white wash
  vec3 ramp = lum < 0.5 ? mix(u_rampLow, u_rampMid, lum * 2.0) : mix(u_rampMid, u_rampHigh, lum * 2.0 - 1.0);
  col = mix(col, ramp, u_tint);
  col += pow(edge * 1.2, 4.0) * vec3(0.6, 0.75, 0.8);

  float alpha = smoothstep(0.0, 0.55, coverage);
  gl_FragColor = vec4(clamp(col, 0.0, 1.0) * alpha, alpha);  // premultiplied
}`;

  // "Chrome" preset from Liquid Logo, retuned for a small mark
  const PARAMS = {
    speed: 0.45, iterations: 12, scale: 2.4, dotFactor: 0.05, dotMultiplier: 0.25, vOffset: 5.1,
    intensity: 0.12, expFactor: 0.25, colorFactors: [1.1, 0.7, 0.9], colorShift: 0.6, noise: 0.6,
    interact: 0.4, tint: 0.92, contrast: [0.5, 1.0, 1.7],
    rampLow: [0.02, 0.20, 0.19], rampMid: [0.486, 0.949, 0.784], rampHigh: [0.80, 1.0, 0.91],
  };

  const reducedMotion = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };

  function compile(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.warn('liquid-logo:', gl.getShaderInfoLog(shader));
      return null;
    }
    return shader;
  }

  function program(gl) {
    const vs = compile(gl, gl.VERTEX_SHADER, VERTEX);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
    if (!vs || !fs) return null;
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    return gl.getProgramParameter(prog, gl.LINK_STATUS) ? prog : null;
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = src;
    });
  }

  async function mount(host) {
    const fallback = host.querySelector('img');
    let P = PARAMS;
    try { P = Object.assign({}, PARAMS, JSON.parse(host.dataset.params || '{}')); } catch (e) { /* keep defaults */ }
    const src = host.dataset.src || (fallback && fallback.currentSrc) || (fallback && fallback.src);
    if (!src) return;

    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-hidden', 'true');
    const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: true, depth: false, stencil: false });
    if (!gl) return;
    const prog = program(gl);
    if (!prog) return;

    let image;
    try { image = await loadImage(src); } catch (e) { return; }
    host.appendChild(canvas);

    gl.useProgram(prog);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(prog, 'a_pos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    const u = (name) => gl.getUniformLocation(prog, name);
    gl.uniform1f(u('u_iterations'), P.iterations);
    gl.uniform1f(u('u_scale'), P.scale);
    gl.uniform1f(u('u_dotFactor'), P.dotFactor);
    gl.uniform1f(u('u_dotMultiplier'), P.dotMultiplier);
    gl.uniform1f(u('u_vOffset'), P.vOffset);
    gl.uniform1f(u('u_intensity'), P.intensity);
    gl.uniform1f(u('u_expFactor'), P.expFactor);
    gl.uniform1f(u('u_colorShift'), P.colorShift);
    gl.uniform1f(u('u_noise'), P.noise);
    gl.uniform1f(u('u_interact'), P.interact);
    gl.uniform1f(u('u_tint'), P.tint);
    gl.uniform3fv(u('u_colorFactors'), P.colorFactors);
    gl.uniform3fv(u('u_rampLow'), P.rampLow);
    gl.uniform3fv(u('u_rampMid'), P.rampMid);
    gl.uniform3fv(u('u_rampHigh'), P.rampHigh);
    gl.uniform3fv(u('u_contrast'), P.contrast);
    const uRes = u('u_res'), uTexel = u('u_texel'), uTime = u('u_time');

    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.uniform1i(u('u_mask'), 0);

    // Draw the logo into a mask the same size as the canvas, so one mask texel is one pixel
    function resize() {
      const box = host.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(16, Math.min(1024, Math.round(box.width * dpr)));
      const h = Math.max(16, Math.min(1024, Math.round(box.height * dpr)));
      if (w === canvas.width && h === canvas.height) return;
      canvas.width = w;
      canvas.height = h;
      const mask = document.createElement('canvas');
      mask.width = w;
      mask.height = h;
      mask.getContext('2d').drawImage(image, 0, 0, w, h);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, mask);
      gl.viewport(0, 0, w, h);
      gl.uniform2f(uRes, w, h);
      gl.uniform2f(uTexel, 1 / w, 1 / h);
    }

    let t = 2.0, last = 0, boost = 1, boostTarget = 1, visible = true, frame = 0, lost = false;

    function draw() {
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(uTime, t);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      host.classList.add('is-live');
    }

    function tick(now) {
      frame = 0;
      if (lost) return;
      const dt = last ? Math.min((now - last) / 1000, 0.1) : 0;
      last = now;
      boost += (boostTarget - boost) * Math.min(1, dt * 4);
      t += dt * P.speed * boost;
      draw();
      schedule();
    }

    function schedule() {
      if (frame || lost || reducedMotion.matches || !visible || document.hidden) { last = 0; return; }
      frame = requestAnimationFrame(tick);
    }

    resize();
    draw();
    schedule();

    if ('ResizeObserver' in window) new ResizeObserver(() => { resize(); draw(); }).observe(host);
    if ('IntersectionObserver' in window) {
      new IntersectionObserver((entries) => { visible = entries[0].isIntersecting; schedule(); }).observe(host);
    }
    document.addEventListener('visibilitychange', schedule);
    if (reducedMotion.addEventListener) reducedMotion.addEventListener('change', schedule);
    host.addEventListener('pointerenter', () => { boostTarget = 3; });
    host.addEventListener('pointerleave', () => { boostTarget = 1; });
    canvas.addEventListener('webglcontextlost', (e) => {
      e.preventDefault();
      lost = true;
      host.classList.remove('is-live');
    });
  }

  const style = document.createElement('style');
  style.textContent = `
[data-liquid-logo]{position:relative;display:inline-block;line-height:0}
[data-liquid-logo]>img{display:block;width:100%;height:100%;transition:opacity .5s ease}
[data-liquid-logo]>canvas{position:absolute;inset:0;width:100%;height:100%;opacity:0;transition:opacity .5s ease;pointer-events:none}
[data-liquid-logo].is-live>img{opacity:0}
[data-liquid-logo].is-live>canvas{opacity:1}`;
  document.head.appendChild(style);

  const start = () => document.querySelectorAll('[data-liquid-logo]').forEach((el) => { mount(el); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
