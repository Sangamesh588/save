const CACHE_NAME = 'mediadownloader-green-v2';

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          // Purge all old caches including mediadownloader-v1
          return caches.delete(key);
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  // Always fetch latest from network for fast instant updates
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
