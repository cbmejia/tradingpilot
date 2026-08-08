import type { ReactNode } from "react";

interface CardProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export function Card({ title, subtitle, children }: CardProps) {
  return (
    <section className="card">
      <header className="card-header">
        <h2>{title}</h2>
        {subtitle && <p className="card-subtitle">{subtitle}</p>}
      </header>
      <div className="card-body">{children}</div>
    </section>
  );
}
