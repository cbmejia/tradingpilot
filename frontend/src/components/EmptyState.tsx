interface EmptyStateProps {
  message: string;
}

export function EmptyState({ message }: EmptyStateProps) {
  return <p className="text-sm leading-relaxed text-slate-500">{message}</p>;
}
