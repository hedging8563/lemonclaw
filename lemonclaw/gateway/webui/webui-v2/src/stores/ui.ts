import { signal } from '@preact/signals';

export const sidebarTab = signal<'sessions' | 'activity'>('sessions');
export const showInspector = signal(window.innerWidth > 1024);