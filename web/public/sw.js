// BabyCue service worker: the app opens instantly and offline (it then says it cannot reach the PC).
// Live video, status, frame uploads, the certificate and the database are never cached.
const CACHE = 'babycue-shell-v1';
const LIVE = ['/view', '/status', '/frame', '/ingest', '/ca.crt', '/baby', '/detections', '/push/key', '/push/subscribe', '/push/unsubscribe', '/push/test'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(['/', '/manifest.webmanifest', '/icon-192.png'])));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

// Background alarm from the home PC (Web Push). It arrives even with BabyCue closed; the phone plays its own
// notification sound and vibrates (browsers do not let a web app choose that sound). A BabyCue page that is still
// running, even hidden, is told to sound its alarm too. An app on screen already shows the alert, so it gets no
// notification, except for a test.
self.addEventListener('push', (event) => {
  let alert = { title: 'BabyCue alert', body: 'Please check on the baby.', level: 'warn', test: false };
  try {
    alert = { ...alert, ...event.data.json() };
  } catch {
    // Not JSON: show the generic alert rather than nothing.
  }
  const crit = alert.level === 'crit';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) client.postMessage({ type: 'babycue-alarm', level: alert.level, test: alert.test });
      if (!alert.test && clients.some((c) => c.visibilityState === 'visible')) return undefined;
      return self.registration.showNotification(alert.title, {
        body: alert.body,
        tag: 'babycue-alert', // a newer alert replaces the older one...
        renotify: true, // ...and still sounds and vibrates again
        requireInteraction: crit, // a critical alert stays until it is tapped
        silent: false,
        vibrate: crit ? [600, 200, 600, 200, 600, 200, 600] : [300, 150, 300],
        icon: '/icon-192.png',
        badge: '/icon-192.png',
        data: { url: '/?open=live' },
      });
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      const open = clients.find((c) => 'focus' in c);
      return open ? open.focus() : self.clients.openWindow(event.notification.data?.url ?? '/?open=live');
    }),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (LIVE.some((p) => url.pathname === p || url.pathname.startsWith(p + '?'))) return;

  // Pages: network first so a new version shows up, the cached app when the PC is off.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          void caches.open(CACHE).then((cache) => cache.put('/', copy));
          return response;
        })
        .catch(() => caches.match('/')),
    );
    return;
  }

  // Files: cached copy first, refreshed in the background (hashed files never change).
  event.respondWith(
    caches.match(request).then((cached) => {
      const fresh = fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            void caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || fresh;
    }),
  );
});
