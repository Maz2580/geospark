/* GeoSpark UI — Shared JavaScript */

const API = window.location.origin;

/* --- API Client --- */
const geo = {
  async get(path) {
    const resp = await fetch(`${API}${path}`);
    if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
    return resp.json();
  },

  async post(path, body) {
    const resp = await fetch(`${API}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
    <div class="json-toggle" onclick="document.getElementById('${id}').classList.toggle('hidden')">
      &#9654; Raw JSON
    </div>
    <pre class="result-box hidden" id="${id}">${escapeHtml(jsonStr)}</pre>
  `;
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/* --- Map Helpers (Leaflet) --- */
let _maps = {};

function createMap(containerId, lat = 0, lon = 0, zoom = 2) {
  if (_maps[containerId]) {
    _maps[containerId].remove();
  }
  const map = L.map(containerId).setView([lat, lon], zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19,
  }).addTo(map);
  _maps[containerId] = map;
  return map;
}

function addMarker(map, lat, lon, label) {
  return L.marker([lat, lon]).addTo(map).bindPopup(label);
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
