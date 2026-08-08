import type { ReactNode } from "react";

interface CardProps {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
}

export function Card({ title, subtitle, action, children }: CardProps) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-900 p-5">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
        </div>
        {action}
      </header>
      <div className="flex-1">{children}</div>
    </section>
  );
}
