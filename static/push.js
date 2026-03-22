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

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/sw.js').then(reg => {
    // 로그인 상태이면 자동으로 구독 시도
    if (document.body.dataset.loggedIn === 'true') {
      subscribePush();
    }
  });
}
