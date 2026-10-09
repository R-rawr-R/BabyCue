/** Background alarms: sign this phone up for the server's Web Push alerts, which arrive with BabyCue closed. */
import { isIos, isStandalone } from '../device';
import { PUSH_KEY_PATH, PUSH_SUBSCRIBE_PATH, PUSH_TEST_PATH, PUSH_UNSUBSCRIBE_PATH } from './wireProtocol';

export type PushState =
  /** This browser cannot receive push at all, or the page is not trusted (certificate not installed). */
  | 'unsupported'
  /** iPhone/iPad: only an app added to the Home Screen can receive push. */
  | 'needs-install'
  /** The user blocked notifications for BabyCue in the browser settings. */
  | 'blocked'
  | 'off'
  | 'on';

function pushPossible(): boolean {
  // A service worker needs a trusted certificate: on a page reached past a certificate warning there is none.
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window && window.isSecureContext;
}

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!pushPossible()) return null;
  // `ready` never settles when no worker was registered (e.g. a dev build), so give up after a moment.
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise<null>((resolve) => setTimeout(() => resolve(null), 3000)),
  ]);
}

export async function pushState(): Promise<PushState> {
  if (isIos() && !isStandalone()) return 'needs-install';
  const reg = await registration();
  if (!reg) return 'unsupported';
  if (Notification.permission === 'denied') return 'blocked';
  const subscription = await reg.pushManager.getSubscription();
  return subscription && Notification.permission === 'granted' ? 'on' : 'off';
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob(base64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function post(path: string, body: unknown): Promise<void> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  if (!response.ok) {
    const reply = (await response.json().catch(() => null)) as { error?: unknown } | null;
    throw new Error(typeof reply?.error === 'string' ? reply.error : `The server answered ${response.status}`);
  }
}

/** Must run inside a tap: asks for notification permission, subscribes, and tells the server. */
export async function enablePush(): Promise<PushState> {
  const reg = await registration();
  if (!reg) return pushState();
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return permission === 'denied' ? 'blocked' : 'off';
  const keyResponse = await fetch(PUSH_KEY_PATH, { cache: 'no-store' });
  const key = (await keyResponse.json().catch(() => null)) as { publicKey?: unknown; error?: unknown } | null;
  if (!keyResponse.ok || typeof key?.publicKey !== 'string') {
    throw new Error(typeof key?.error === 'string' ? key.error : 'The home PC did not send its alarm key');
  }
  let subscription = await reg.pushManager.getSubscription();
  // A subscription made for another server's key would never receive our alarms.
  const current = subscription?.options.applicationServerKey;
  if (subscription && current && !sameKey(new Uint8Array(current), keyBytes(key.publicKey))) {
    await subscription.unsubscribe();
    subscription = null;
  }
  subscription ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key.publicKey) });
  await post(PUSH_SUBSCRIBE_PATH, subscription.toJSON());
  return 'on';
}

export async function disablePush(): Promise<PushState> {
  const reg = await registration();
  const subscription = await reg?.pushManager.getSubscription();
  if (subscription) {
    await post(PUSH_UNSUBSCRIBE_PATH, { endpoint: subscription.endpoint }).catch(() => undefined);
    await subscription.unsubscribe();
  }
  return pushState();
}

/** Asks the PC to send a test alarm to this phone only. */
export async function sendTestPush(): Promise<void> {
  const subscription = await (await registration())?.pushManager.getSubscription();
  if (!subscription) throw new Error('Background alarms are not on for this phone');
  await post(PUSH_TEST_PATH, { endpoint: subscription.endpoint });
}

function sameKey(a: Uint8Array, b: Uint8Array): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}
