/* GeoSpark UI — Shared JavaScript */

const API = window.location.origin;

/* --- Visitor session ---
 * A random id kept in this browser. The server uses it to give each visitor a private
 * sandbox for the Memory and Context demos. If storage is blocked, a per-page id is used. */
const SESSION_ID = (() => {
  const fresh = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now());
  try {
    let id = localStorage.getItem('geospark-session');
    if (!id || !/^[A-Za-z0-9-]{16,64}$/.test(id)) {
      id = fresh();
      localStorage.setItem('geospark-session', id);
    }
    return id;
  } catch (e) {
    return fresh();
  }
})();

/* --- API Client --- */
const geo = {
  async get(path) {
    const resp = await fetch(`${API}${path}`, { headers: { 'X-GeoSpark-Session': SESSION_ID } });
    if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
    return resp.json();
  },

  async post(path, body) {
    const resp = await fetch(`${API}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-GeoSpark-Session': SESSION_ID },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
    return resp.json();
  },
};

/* --- UI Helpers --- */
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function showLoading(el, msg = 'Processing...') {
  el.innerHTML = `<div class="loading-overlay"><span class="spinner"></span>${msg}</div>`;
  el.classList.remove('hidden', 'error', 'success');
}

function showResult(el, data) {
  el.innerHTML = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  el.classList.remove('hidden', 'error');
  el.classList.add('success');
}

function showError(el, rawMsg) {
  let msg = typeof rawMsg === 'string' ? rawMsg : JSON.stringify(rawMsg);
  // Add helpful suggestions for common errors
  let suggestion = '';
  if (msg.includes('502') || msg.includes('Ollama'))
    suggestion = 'The LLM service may be busy. Try again in a few seconds.';
  else if (msg.includes('504') || msg.includes('timed out'))
    suggestion = 'The request timed out. Try a simpler query or shorter radius.';
  else if (msg.includes('geocode') || msg.includes('No results'))
    suggestion = 'Try adding a city or country name to your search.';
  else if (msg.includes('API_KEY') || msg.includes('unconfigured'))
    suggestion = 'This channel requires a free API key. See the status page for details.';

  el.innerHTML = `<strong>Error:</strong> ${escapeHtml(msg)}` +
    (suggestion ? `<br><span class="text-sm" style="color:var(--color-text-secondary)">Tip: ${suggestion}</span>` : '');
  el.classList.remove('hidden', 'success');
  el.classList.add('error');
}

function metricRow(label, value) {
  return `<div class="metric"><span class="label">${label}</span><span class="value">${value ?? '—'}</span></div>`;
}

function resultCard(metrics) {
  return `<div class="result-card">${metrics.map(([l, v]) => metricRow(l, v)).join('')}</div>`;
}

function jsonToggle(data, id) {
  const jsonStr = JSON.stringify(data, null, 2);
  return `
    <button type="button" class="json-toggle" aria-expanded="false" aria-controls="${id}"
      onclick="const p=document.getElementById('${id}');p.classList.toggle('hidden');this.setAttribute('aria-expanded', !p.classList.contains('hidden'))">
      { } Raw JSON
    </button>
    <pre class="result-box hidden" id="${id}">${escapeHtml(jsonStr)}</pre>
  `;
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* --- Map Helpers (Leaflet) --- */
let _maps = {};

function createMap(containerId, lat = 0, lon = 0, zoom = 2) {
  if (_maps[containerId]) {
    _maps[containerId].remove();
  }
  const map = L.map(containerId).setView([lat, lon], zoom);
  // OSM tile usage policy: single tile host (the a/b/c subdomains are deprecated) and a
  // visible attribution linking to the copyright page.
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(map);
  _maps[containerId] = map;
  return map;
}

function addMarker(map, lat, lon, label, variant = '') {
  const icon = L.divIcon({ className: '', html: `<div class="geo-pin ${variant}"></div>`, iconSize: [14, 14], iconAnchor: [7, 7] });
  const marker = L.marker([lat, lon], { icon }).addTo(map);
  if (label) marker.bindPopup(escapeHtml(String(label)));
  return marker;
}

/* --- Proof panel: the checkable part of every answer ---
 * Renders status, sources (with licence and method), caveats, units and the actions
 * (download GeoJSON, copy a citation). `data` is any GeoSpark response that carries
 * provenance / warnings / units / quality / status. */
const ICON_WARN = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>';

function statusBadge(status) {
  const map = { ok: ['badge-ok', 'ok'], partial: ['badge-warn', 'partial'], cannot_answer: ['badge-error', 'cannot answer'] };
  const [cls, text] = map[status] || ['badge-info', status || 'unchecked'];
  return `<span class="badge ${cls}">status: ${escapeHtml(text)}</span>`;
}

function collectCaveats(data) {
  const out = [...(data.warnings || [])];
  const q = data.quality || {};
  if (q.vertical_accuracy_m != null) out.push(`Vertical accuracy about ±${q.vertical_accuracy_m} m (DEM).`);
  if (q.cloud_cover_pct != null) out.push(`Cloud cover ${q.cloud_cover_pct}% in the source image.`);
  if (data.fallback_note) out.push(data.fallback_note);
  return [...new Set(out)];
}

function renderProof(data, opts = {}) {
  const prov = data.provenance || data.geospark?.provenance || [];
  const units = data.units || data.spatial_context?.units || {};
  const caveats = collectCaveats(data);
  const id = 'proof-' + Math.random().toString(36).slice(2, 8);
  const sources = prov.length ? `<ul class="source-list">${prov.map(p => `
      <li class="source-item">
        <span class="name">${p.url ? `<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">${escapeHtml(p.name || p.source)}</a>` : escapeHtml(p.name || p.source)}</span>
        <span class="meta">${[p.licence, p.dataset_version].filter(Boolean).map(escapeHtml).join(' · ') || escapeHtml(p.source)}</span>
        ${p.method ? `<span class="method">${escapeHtml(p.method)}</span>` : ''}
      </li>`).join('')}</ul>` : '<p class="text-sm text-muted">No sources were reported for this answer.</p>';
  const unitRows = Object.entries(units);
  const html = `
    <section class="proof" aria-label="Proof">
      <div class="proof-head"><h4>Proof</h4>${statusBadge(data.status || (prov.length ? 'ok' : undefined))}</div>
      <div class="proof-section"><h5>Sources</h5>${sources}</div>
      ${caveats.length ? `<div class="proof-section"><h5>Caveats</h5><ul class="caveats">${caveats.map(c => `<li class="caveat">${ICON_WARN}<span>${escapeHtml(c)}</span></li>`).join('')}</ul></div>` : ''}
      ${unitRows.length ? `<div class="proof-section"><h5>Units</h5><dl class="units-grid">${unitRows.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd>`).join('')}</dl></div>` : ''}
      <div class="proof-actions">
        ${opts.geojson ? `<button type="button" class="btn btn-light btn-sm" id="${id}-dl">Download GeoJSON</button>` : ''}
        ${prov.length ? `<button type="button" class="btn btn-secondary btn-sm" id="${id}-cite">Copy citation</button>` : ''}
      </div>
    </section>`;
  // Wire the buttons once the markup is in the page
  setTimeout(() => {
    const dl = document.getElementById(`${id}-dl`);
    if (dl) dl.addEventListener('click', () => downloadGeoJSON(opts.geojson, opts.filename || 'geospark-result'));
    const cite = document.getElementById(`${id}-cite`);
    if (cite) cite.addEventListener('click', async () => {
      const text = prov.map(p => [p.name || p.source, p.licence, p.attribution, p.url].filter(Boolean).join(' — ')).join('\n');
      try { await navigator.clipboard.writeText(text); cite.textContent = 'Copied'; } catch (e) { cite.textContent = 'Copy failed'; }
      setTimeout(() => { cite.textContent = 'Copy citation'; }, 1600);
    });
  }, 0);
  return html;
}

/* An RFC 7946 FeatureCollection from a GeoSpark result (or the collection itself) */
function toFeatureCollection(data) {
  if (data?.type === 'FeatureCollection') return data;
  const features = (data?.features || []).filter(f => f.geometry).map(f => ({ type: 'Feature', geometry: f.geometry, properties: f.properties || {} }));
  return { type: 'FeatureCollection', features, geospark: { provenance: data?.provenance || [], status: data?.status } };
}

function downloadGeoJSON(data, name) {
  const blob = new Blob([JSON.stringify(toFeatureCollection(data), null, 2)], { type: 'application/geo+json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${name}.geojson`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
}

/* A clear "cannot answer" instead of a red stack trace */
function refusalHtml(title, detail) {
  return `<div class="refusal" role="status">${ICON_WARN}<div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p></div></div>`;
}

function errorDetail(message) {
  const m = String(message).match(/^\d{3}: ([\s\S]*)$/);
  if (!m) return String(message);
  try { const j = JSON.parse(m[1]); return typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch (e) { return m[1]; }
}

function fmt(n, digits = 2) {
  return n == null || Number.isNaN(Number(n)) ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fitBounds(map, points) {
  if (points.length === 0) return;
  if (points.length === 1) {
    map.flyTo([points[0][0], points[0][1]], 13, { duration: 1.2 });
    return;
  }
  const bounds = L.latLngBounds(points.map(p => [p[0], p[1]]));
  map.flyToBounds(bounds, { padding: [40, 40], duration: 1.2 });
}

/* --- Tab Management --- */
function initTabs(container) {
  const tabs = container.querySelectorAll('.tab');
  const panels = container.querySelectorAll('.tab-panel');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      panels.forEach(p => p.classList.add('hidden'));
      tab.classList.add('active');
      const panel = container.querySelector(`#${tab.dataset.tab}`);
      if (panel) panel.classList.remove('hidden');
    });
  });
}

/* --- Nav Active State --- */
document.addEventListener('DOMContentLoaded', () => {
  const path = window.location.pathname;
  $$('.nav-links a').forEach(a => {
    const href = a.getAttribute('href');
    if (href === path || (href === '/' && path === '/')) {
      a.classList.add('active');
    }
  });

  // Load version in nav
  geo.get('/health').then(data => {
    const vEl = $('.nav-version');
    if (vEl) vEl.textContent = `v${data.version}`;
  }).catch(() => {});
});
