import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Card({ children, className = "", ...rest }: CardProps) {
  return (
    <div
      className={`rounded-lg border border-border bg-surface-1 ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({ children, className = "", ...rest }: CardProps) {
  return (
    <div className={`border-b border-border-subtle px-4 py-3 ${className}`} {...rest}>
      {children}
    </div>
  );
}

export function CardTitle({ children, className = "", ...rest }: CardProps) {
  return (
    <h2 className={`text-sm font-semibold text-text-primary ${className}`} {...rest}>
      {children}
    </h2>
  );
}

export function CardBody({ children, className = "", ...rest }: CardProps) {
  return (
    <div className={`px-4 py-3 ${className}`} {...rest}>
      {children}
    </div>
  );
}
