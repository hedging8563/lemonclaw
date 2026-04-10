import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { apiFetchMock } = vi.hoisted(() => ({
  apiFetchMock: vi.fn(),
}));

vi.mock('../src/api/client', () => ({
  apiFetch: apiFetchMock,
}));

let auth: typeof import('../src/stores/auth');

describe('auth store', () => {
  beforeEach(async () => {
    vi.resetModules();
    const windowTarget = new EventTarget();
    vi.stubGlobal('window', windowTarget);
    apiFetchMock.mockReset();
    auth = await import('../src/stores/auth');
    auth.isAuthenticated.value = false;
    auth.authRequired.value = false;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('marks auth as required when the app receives an auth-required event', () => {
    auth.isAuthenticated.value = true;

    window.dispatchEvent(new Event('auth-required'));

    expect(auth.isAuthenticated.value).toBe(false);
    expect(auth.authRequired.value).toBe(true);
  });

  it('refreshes the auth state after logout', async () => {
    auth.isAuthenticated.value = true;
    auth.authRequired.value = true;
    apiFetchMock
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: false, json: async () => ({ ok: false, auth_required: true }) });

    await auth.logout();

    expect(apiFetchMock).toHaveBeenNthCalledWith(1, '/api/auth', { method: 'DELETE' });
    expect(apiFetchMock).toHaveBeenNthCalledWith(2, '/api/auth/check');
    expect(auth.isAuthenticated.value).toBe(false);
    expect(auth.authRequired.value).toBe(true);
  });
});
