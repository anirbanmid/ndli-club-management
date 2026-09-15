/* =========================================================================
   NDLI Club Management App — Offline Sync & Mobile PWA Integration Engine
   Provides IndexedDB offline transaction queue, auto-sync, GPS tagger, & PWA prompt
   ========================================================================= */

const DB_NAME = 'NDLI_Offline_DB';
const DB_VERSION = 1;
const STORE_NAME = 'pending_queue';

let offlineDb = null;
let deferredInstallPrompt = null;

// Initialize IndexedDB
function initOfflineDB() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) {
      console.warn('[OfflineSync] IndexedDB not supported on this client.');
      resolve(null);
      return;
    }
    const req = window.indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = e => {
      offlineDb = e.target.result;
      resolve(offlineDb);
      checkPendingQueueBadge();
    };
    req.onerror = e => {
      console.error('[OfflineSync] IndexedDB error:', e);
      resolve(null);
    };
  });
}

// Queue an action offline
async function queueOfflineAction(endpoint, method, payload) {
  if (!offlineDb) await initOfflineDB();
  return new Promise((resolve, reject) => {
    if (!offlineDb) {
      try {
        const queue = JSON.parse(localStorage.getItem('ndli_offline_queue') || '[]');
        queue.push({ endpoint, method, payload, timestamp: new Date().toISOString() });
        localStorage.setItem('ndli_offline_queue', JSON.stringify(queue));
        showOfflineToast('Saved to local device. Will sync when reconnected.');
        resolve(true);
      } catch (err) {
        reject(err);
      }
      return;
    }

    const tx = offlineDb.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const item = {
      endpoint,
      method,
      payload,
      timestamp: new Date().toISOString(),
      user: sessionStorage.getItem('ndli_token') || 'anonymous'
    };
    const req = store.add(item);
    req.onsuccess = () => {
      showOfflineToast('📡 Offline Mode: Saved locally on device. Auto-syncing when internet returns.');
      checkPendingQueueBadge();
      resolve(true);
    };
    req.onerror = err => reject(err);
  });
}

// Sync all pending transactions when back online
async function syncOfflineQueue() {
  if (!navigator.onLine) return;
  if (!offlineDb) await initOfflineDB();

  let items = [];
  if (offlineDb) {
    items = await new Promise(resolve => {
      const tx = offlineDb.transaction(STORE_NAME, 'readonly');
      const store = tx.objectStore(STORE_NAME);
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => resolve([]);
    });
  }

  try {
    const lsItems = JSON.parse(localStorage.getItem('ndli_offline_queue') || '[]');
    if (lsItems.length > 0) {
      items = items.concat(lsItems);
      localStorage.removeItem('ndli_offline_queue');
    }
  } catch (e) {}

  if (!items || items.length === 0) {
    checkPendingQueueBadge();
    return;
  }

  showOfflineToast('🔄 Synchronizing ' + items.length + ' offline items with NDLI Master Database...');
  let syncedCount = 0;

  for (const item of items) {
    try {
      const res = await apiRequest(item.endpoint, item.method, item.payload);
      if (res && res.ok) {
        syncedCount++;
        if (item.id && offlineDb) {
          const dtx = offlineDb.transaction(STORE_NAME, 'readwrite');
          dtx.objectStore(STORE_NAME).delete(item.id);
        }
      }
    } catch (err) {
      console.warn('[OfflineSync] Item sync retry deferred:', err);
    }
  }

  if (syncedCount > 0) {
    showOfflineToast('✅ Successfully synchronized ' + syncedCount + ' offline record(s) to Master DB!', 'success');
  }
  checkPendingQueueBadge();
}

// Visual badge showing pending items count
function checkPendingQueueBadge() {
  if (!offlineDb) return;
  try {
    const tx = offlineDb.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const countReq = store.count();
    countReq.onsuccess = () => {
      const count = countReq.result || 0;
      let badge = document.getElementById('offline-queue-badge');
      if (count > 0) {
        if (!badge) {
          badge = document.createElement('div');
          badge.id = 'offline-queue-badge';
          badge.style.cssText = 'position:fixed;bottom:20px;left:20px;background:#D97706;color:#FFF;padding:8px 14px;border-radius:24px;font-size:0.8rem;font-weight:700;box-shadow:0 4px 16px rgba(0,0,0,0.3);z-index:99999;display:flex;align-items:center;gap:6px;cursor:pointer;';
          badge.onclick = () => syncOfflineQueue();
          document.body.appendChild(badge);
        }
        badge.innerHTML = '<span>📡</span> ' + count + ' Offline Item' + (count > 1 ? 's' : '') + ' (Click to Sync)';
      } else if (badge) {
        badge.remove();
      }
    };
  } catch (e) {}
}

// Toast notification display
function showOfflineToast(msg, type) {
  let toast = document.getElementById('offline-sync-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'offline-sync-toast';
    toast.style.cssText = 'position:fixed;bottom:24px;right:24px;max-width:360px;padding:12px 18px;border-radius:10px;font-size:0.85rem;font-weight:600;z-index:999999;box-shadow:0 10px 30px rgba(0,0,0,0.35);transition:all 0.3s ease;display:flex;align-items:center;gap:8px;';
    document.body.appendChild(toast);
  }
  if (type === 'success') {
    toast.style.background = '#065F46';
    toast.style.color = '#FFFFFF';
    toast.style.border = '1px solid #34D399';
  } else {
    toast.style.background = '#103125';
    toast.style.color = '#FDE68A';
    toast.style.border = '1px solid #D97706';
  }
  toast.innerHTML = msg;
  toast.style.opacity = '1';
  toast.style.transform = 'translateY(0)';
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(12px)';
  }, 4500);
}

// Mobile GPS Geolocation Tagging Helper for Field Visits
window.captureCampusGPS = function(targetInputId) {
  if (!navigator.geolocation) {
    alert('Geolocation is not supported by this device.');
    return;
  }
  const btn = event ? event.target : null;
  const origText = btn ? btn.innerHTML : '';
  if (btn) btn.innerHTML = '<span>⏳</span> Locating...';

  navigator.geolocation.getCurrentPosition(
    pos => {
      const lat = pos.coords.latitude.toFixed(5);
      const lng = pos.coords.longitude.toFixed(5);
      const gpsStr = ' [GPS: ' + lat + '° N, ' + lng + '° E]';
      const input = document.getElementById(targetInputId || 'notes') || document.querySelector('textarea[name="notes"], #notes');
      if (input) {
        input.value = (input.value || '') + gpsStr;
        showOfflineToast('📍 Campus GPS Attached: ' + lat + '°, ' + lng + '°', 'success');
      }
      if (btn) btn.innerHTML = '<span>📍</span> GPS Attached!';
      setTimeout(() => { if (btn) btn.innerHTML = origText; }, 2000);
    },
    err => {
      alert('Could not retrieve GPS coordinates: ' + err.message);
      if (btn) btn.innerHTML = origText;
    },
    { enableHighAccuracy: true, timeout: 8000 }
  );
};

// PWA Install Prompt Handler
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  deferredInstallPrompt = e;
  renderInstallAppButton();
});

function renderInstallAppButton() {
  if (document.getElementById('btn-pwa-install')) return;
  const navLinks = document.querySelector('.nav-links');
  if (navLinks) {
    const btn = document.createElement('button');
    btn.id = 'btn-pwa-install';
    btn.className = 'btn btn-sm btn-amber';
    btn.style.cssText = 'padding: 0.22rem 0.65rem; font-size: 0.75rem; font-weight: 700; display: inline-flex; align-items: center; gap: 4px;';
    btn.innerHTML = '<span>📲</span> Install App';
    btn.onclick = () => {
      if (deferredInstallPrompt) {
        deferredInstallPrompt.prompt();
        deferredInstallPrompt.userChoice.then(res => {
          if (res.outcome === 'accepted') {
            btn.remove();
          }
          deferredInstallPrompt = null;
        });
      }
    };
    navLinks.insertBefore(btn, navLinks.firstChild);
  }
}

// Lifecycle listeners
window.addEventListener('online', () => {
  showOfflineToast('🌐 Internet connection restored! Synchronizing records...', 'success');
  syncOfflineQueue();
});

window.addEventListener('offline', () => {
  showOfflineToast('📡 Disconnected: Switched to Offline-First local storage mode.');
});

// Register Service Worker
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/js/sw.js')
      .then(reg => console.log('[PWA] Service Worker registered:', reg.scope))
      .catch(err => console.warn('[PWA] Service Worker registration skipped:', err));
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initOfflineDB();
});
