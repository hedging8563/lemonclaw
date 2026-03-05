import { signal } from '@preact/signals';
import { apiFetch } from '../api/client';

export const isAuthenticated = signal(false);
export const authRequired = signal(false);

export async function checkAuth() {
  try {
    const res = await apiFetch('/api/auth/check');
    const data = await res.json();
    isAuthenticated.value = data.ok;
    authRequired.value = data.auth_required;
    return data;
  } catch (err) {
    isAuthenticated.value = false;
    authRequired.value = true;
    return { ok: false, auth_required: true };
  }
}

export async function login(token: string) {
  const res = await apiFetch('/api/auth', {
    method: 'POST',
    body: JSON.stringify({ token })
  });
  if (res.ok) {
    isAuthenticated.value = true;
  }
}

export async function logout() {
  await apiFetch('/api/auth', { method: 'DELETE' });
  isAuthenticated.value = false;
}

// Listen to global auth-required event from apiFetch
window.addEventListener('auth-required', () => {
  isAuthenticated.value = false;
});