import React from 'react';
import { cn } from '@/lib/utils';

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ title, description, icon, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center p-12 text-center', className)}>
      {icon && <div className="mb-4 text-foreground/20">{icon}</div>}
      <h3 className="font-headline text-lg font-medium text-foreground/60">{title}</h3>
      {description && <p className="mt-1.5 text-sm font-body text-foreground/40 max-w-xs">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
