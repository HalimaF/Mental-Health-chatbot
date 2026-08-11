/* Dil-e-Azaad service worker.
 *
 * The previous version answered EVERY request cache-first. On a shared phone
 * that will serve one person's cached /chat or /api/history to the next person
 * who opens the app -- an unacceptable failure for this product. It also called
 * cache.addAll() on icon paths that did not exist, so install rejected and the
 * worker never activated at all.
 *
 * This version has one job: keep the crisis numbers reachable offline. It
 * precaches a static, impersonal offline page and the app's own static assets,
 * and it refuses to touch anything that could contain someone's data.
 */

const VERSION = 'dil-e-azaad-v2';
const PRECACHE = [
  '/static/offline.html',
  '/static/manifest.json',
  '/static/dil-e-azaad-logo.svg',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
];

// Anything that is, or could become, personal. Never read from or written to
// the cache under any circumstances.
const NEVER_CACHE = [
  '/api/',
  '/chat',
  '/guest',
  '/history',
  '/insights',
  '/streak',
  '/account',
  '/safety-plan',
  '/login',
  '/register',
  '/logout',
  '/healthz',
];

function isPrivate(url) {
  return NEVER_CACHE.some(function (p) {
    return url.pathname === p || url.pathname.startsWith(p + '/') || url.pathname.startsWith(p);
  });
}

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(VERSION).then(function (cache) {
      // Individually, so one missing asset cannot fail the whole install the
      // way addAll() did.
      return Promise.all(
        PRECACHE.map(function (url) {
          return cache.add(url).catch(function () { /* non-fatal */ });
        })
      );
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names.filter(function (n) { return n !== VERSION; })
             .map(function (n) { return caches.delete(n); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (isPrivate(url)) return;                    // straight to the network, always

  // Static assets: cache-first, they are fingerprint-free but immutable enough.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then(function (hit) {
        return hit || fetch(req).then(function (res) {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(VERSION).then(function (c) { c.put(req, copy); });
          }
          return res;
        });
      })
    );
    return;
  }

  // Page navigations: always try the network so content is never stale. Only
  // if the network fails does the offline page appear.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(function () {
        return caches.match('/static/offline.html');
      })
    );
  }
});
