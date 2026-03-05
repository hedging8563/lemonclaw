import { signal } from '@preact/signals';

export const sidebarTab = signal<'sessions' | 'activity'>('sessions');
export const showInspector = signal(window.innerWidth > 1024);
export const mobileMenuOpen = signal(false);