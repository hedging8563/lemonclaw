import { signal } from '@preact/signals';

export const sidebarTab = signal<'sessions' | 'activity' | 'operatorQueue' | 'triggers'>('sessions');
export const showInspector = signal(false);
export const mobileMenuOpen = signal(false);
export const showSettings = signal(false);
export const selectedInspectorBlock = signal<{type: 'thinking' | 'tool', id: string, data: any} | null>(null);
