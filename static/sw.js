const CACHE_NAME = 'darfin-static-v1';
const STATIC_ASSETS = [
  '/manifest.json',
  '/favicon.ico',
  '/static/darfin_logo.png',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <meta name="theme-color" content="#060d1f">
  <title>Darfin Storage - Offline</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      min-height: 100dvh;
      background: #060d1f;
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
      text-align: center;
    }
    .card {
      max-width: 360px;
      width: 100%;
      background: rgba(15, 23, 42, 0.9);
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 22px;
      padding: 32px 24px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
    }
    .icon { font-size: 2.6rem; margin-bottom: 12px; }
    h1 { font-size: 1.2rem; margin-bottom: 8px; }
    p { font-size: 0.88rem; color: #94a3b8; line-height: 1.5; margin-bottom: 20px; }
    button {
      width: 100%;
      padding: 12px 18px;
      border-radius: 12px;
      border: none;
      background: linear-gradient(135deg, #0284c7, #38bdf8);
      color: #030712;
      font-weight: 700;
      font-size: 0.92rem;
      cursor: pointer;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">📡</div>
    <h1>Koneksi Terputus</h1>
    <p>Tidak dapat terhubung ke Darfin Storage. Periksa internet Anda lalu coba muat ulang.</p>
    <button onclick="window.location.reload()">Coba Lagi</button>
  </div>
</body>
</html>`;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never cache private API, auth, dropzone, or share routes
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/auth/') ||
    url.pathname.startsWith('/dropzone/') ||
    url.pathname.startsWith('/share/') ||
    url.pathname.startsWith('/.well-known/')
  ) {
    return;
  }

  // Navigation requests: network-first with branded offline fallback
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => new Response(OFFLINE_HTML, {
        status: 503,
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      }))
    );
    return;
  }

  // Public static assets & icons: cache-first with background refresh
  if (
    url.pathname.startsWith('/static/') ||
    url.pathname === '/manifest.json' ||
    url.pathname === '/favicon.ico' ||
    url.pathname === '/favicon.png'
  ) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const networkFetch = fetch(request).then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)).catch(() => {});
          }
          return resp;
        }).catch(() => cached);
        return cached || networkFetch;
      })
    );
  }
});
