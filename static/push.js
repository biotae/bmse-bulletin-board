const VAPID_PUBLIC_KEY = 'BCU75ug49OdmAf0y7N0SpmG4yV3SHg2YZAirezppL0WTvagMfwEyQeX-YQ1vspt4lqpxxiqLPZO5cY3N_ddL61Q';

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map(c => c.charCodeAt(0)));
}

async function subscribePush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;

  const reg = await navigator.serviceWorker.ready;
  const existing = await reg.pushManager.getSubscription();
  if (existing) return; // 이미 구독 중

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return;

  const subscription = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
  });

  await fetch('/push/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(subscription),
  });
}

async function unsubscribePush() {
  if (!('serviceWorker' in navigator)) return;
  const reg = await navigator.serviceWorker.ready;
  const subscription = await reg.pushManager.getSubscription();
  if (!subscription) return;

  await fetch('/push/unsubscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  });
  await subscription.unsubscribe();
}

async function showPushBanner() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
  if (Notification.permission !== 'default') return; // 이미 허용/거부됨

  const banner = document.createElement('div');
  banner.id = 'push-banner';
  banner.style.cssText = `
    position:fixed; bottom:20px; left:50%; transform:translateX(-50%);
    background:#333; color:#fff; padding:12px 20px; border-radius:8px;
    display:flex; align-items:center; gap:12px; z-index:9999;
    box-shadow:0 4px 12px rgba(0,0,0,0.3); font-size:14px;
  `;
  banner.innerHTML = `
    <span>🔔 새 게시글 알림을 받으시겠습니까?</span>
    <button id="push-allow" style="background:#db2416;color:#fff;border:none;padding:6px 14px;border-radius:4px;cursor:pointer;">허용</button>
    <button id="push-deny" style="background:transparent;color:#aaa;border:none;padding:6px;cursor:pointer;">✕</button>
  `;
  document.body.appendChild(banner);

  document.getElementById('push-allow').onclick = async () => {
    banner.remove();
    await subscribePush();
  };
  document.getElementById('push-deny').onclick = () => banner.remove();
}

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/sw.js').then(() => {
    if (document.body.dataset.loggedIn === 'true') {
      showPushBanner();
    }
  });
}
