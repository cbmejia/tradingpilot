// Every panel that can show a FAILED stage (capture, market data,
// analysis, evaluation) renders its failure through this one component
// -- never a blank section, never a placeholder, never a broken-image
// icon. The real message from the API is always shown.

interface ErrorNoticeProps {
  title: string;
  message: string | null;
}

export function ErrorNotice({ title, message }: ErrorNoticeProps) {
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3">
      <p className="text-sm font-semibold text-red-400">{title}</p>
      <p className="mt-1 text-sm text-red-300/90">
        {message ?? "No error message was provided."}
      </p>
    </div>
  );
}
