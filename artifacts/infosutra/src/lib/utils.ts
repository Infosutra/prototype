import { twMerge } from 'tailwind-merge';

import { clsx, type ClassValue } from 'clsx';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Soft-fill field affordance: muted fill at rest, border on hover/focus. */
export const softFieldClasses =
  'border border-transparent bg-muted/40 shadow-none transition-[color,box-shadow,background-color,border-color] hover:bg-muted/60 hover:border-muted-foreground/40 focus:bg-card focus:border-ring/55 focus:outline-none focus:ring-2 focus:ring-ring/20 focus-visible:bg-card focus-visible:border-ring/55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-50';

/** Sidebar study selector and search — dark surface variant of soft-fill fields. */
export const sidebarFieldClasses =
  'border border-transparent bg-sidebar-accent/40 text-sidebar-foreground shadow-none transition-[color,box-shadow,background-color,border-color] hover:bg-sidebar-accent/60 hover:border-sidebar-foreground/40 focus:bg-sidebar-accent/80 focus:border-sidebar-ring/55 focus:outline-none focus:ring-2 focus:ring-sidebar-ring/20 focus-visible:bg-sidebar-accent/80 focus-visible:border-sidebar-ring/55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring/20 disabled:cursor-not-allowed disabled:opacity-50';
