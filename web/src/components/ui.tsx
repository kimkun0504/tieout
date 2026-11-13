import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Severity } from "../lib/types";

type Variant = "primary" | "secondary" | "quiet" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-action text-white hover:bg-action-hover disabled:bg-ink-3",
  secondary: "border border-rule bg-surface text-ink hover:border-ink-3 disabled:text-ink-3",
  quiet: "text-action hover:underline disabled:text-ink-3",
  danger: "border border-rule bg-surface text-err hover:border-err",
};

export function Button({
  variant = "secondary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const pad = variant === "quiet" ? "px-0" : "px-3 py-1.5";
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex items-center gap-1.5 rounded text-sm font-medium transition-colors disabled:cursor-not-allowed ${pad} ${VARIANTS[variant]} ${className}`}
    />
  );
}

const SEVERITY_STYLE: Record<Severity, string> = {
  error: "bg-err",
  warning: "bg-warn",
  info: "bg-ink-3",
};

export function SeverityMark({ severity, muted = false }: { severity: Severity; muted?: boolean }) {
  return (
    <span
      role="img"
      aria-label={severity}
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-sm ${muted ? "bg-rule" : SEVERITY_STYLE[severity]}`}
    />
  );
}

export function Panel({ title, actions, children, className = "" }: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-md border border-rule bg-surface ${className}`}>
      {title !== undefined && (
        <div className="flex items-center gap-3 border-b border-rule-soft px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          <div className="ml-auto flex items-center gap-2">{actions}</div>
        </div>
      )}
      {children}
    </section>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded border border-err/30 bg-err-soft px-3 py-2 text-sm text-err">
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-4 py-6 text-sm text-ink-3">{children}</p>;
}
