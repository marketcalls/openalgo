import React from 'react'; // Add this line
import { LucideIcon } from 'lucide-react';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  className?: string;
}

export const EmptyState = ({ icon: Icon, title, description, className = "" }: EmptyStateProps) => (
  <div className={`flex flex-col items-center justify-center text-center py-8 ${className}`}>
    <Icon className="h-12 w-12 text-muted-foreground mb-3" />
    <h3 className="font-semibold mb-1">{title}</h3>
    <p className="text-sm text-muted-foreground">
      {description}
    </p>
  </div>
);