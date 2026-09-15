/* =========================================================================
   NDLI Club Management App — Service Worker (v3.0)
   Provides offline app shell caching and background sync capabilities
   ========================================================================= */

const CACHE_NAME = 'ndli-club-v3.0';
const STATIC_ASSETS = [
  '/',
  '/employee',
  '/admin',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/js/offline_sync.js',
  '/static/manifest.json',
  '/static/img/ndli_club_logo.png',
  '/static/img/app_icon_192.png',
  '/static/img/app_icon_512.png',
  '/static/img/app_icon.svg',
  '/static/img/osticket_logo.svg'
];

// Install: Pre-cache core app shell
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log('[SW] Pre-caching offline app shell...');
      return cache.addAll(STATIC_ASSETS).catch(err => {
        console.warn('[SW] Cache addAll partial skip:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// Activate: Clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.map(key => {
          if (key !== CACHE_NAME) {
            console.log('[SW] Removing deprecated cache:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: Network-first for APIs, Stale-while-revalidate for static shell
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Skip non-GET requests (POSTs are queued by offline_sync.js)
  if (req.method !== 'GET') return;

  // For REST APIs: Network-first with fallback
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => {
        return caches.match(req).then(cached => {
          if (cached) return cached;
          return new Response(JSON.stringify({ ok: false, offline: true, message: 'Offline mode active. Using cached records.' }), {
            headers: { 'Content-Type': 'application/json' }
          });
        });
      })
    );
    return;
  }

  // For static assets & pages: Cache-first with background network update
  event.respondWith(
    caches.match(req).then(cached => {
      const fetchPromise = fetch(req).then(networkResponse => {
        if (networkResponse && networkResponse.status === 200) {
          const resClone = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(req, resClone));
        }
        return networkResponse;
      }).catch(() => cached);

      return cached || fetchPromise;
    })
  );
});
