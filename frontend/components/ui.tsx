"use client";

// CADENCE shared visual primitives. Everything is built from raw divs styled
// to the six-token system — no Tremor component styling, no border-radius, no
// shadows. The one moment of motion lives here: <Kpi> counts up on mount.

import { useEffect, useRef, useState } from "react";

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/* -------------------------------------------------------------------------- */
/* Eyebrow — 10px ALL CAPS tracked label                                      */
/* -------------------------------------------------------------------------- */
export function Eyebrow({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <span className={`eyebrow ${className}`}>{children}</span>;
}

/* -------------------------------------------------------------------------- */
/* Panel — a discrete --surface card framed by a 1px --edge border. Generous  */
/* header + body padding so content breathes. `loading` paints the           */
/* GitHub-style sweep bar across the top; `action` slots a control top-right. */
/* -------------------------------------------------------------------------- */
export function Panel({
  children,
  loading = false,
  className = "",
  eyebrow,
  title,
  subtitle,
  action,
  bodyClassName = "px-6 py-6",
}: {
  children: React.ReactNode;
  loading?: boolean;
  className?: string;
  // Optional small uppercase kicker shown above the defined title.
  eyebrow?: string;
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  bodyClassName?: string;
}) {
  const hasHeader = eyebrow || title || subtitle || action;
  return (
    <section className={`relative overflow-hidden rounded-lg border border-edge bg-surface ${className}`}>
      {loading && <div className="loadbar" aria-hidden />}
      {hasHeader && (
        <header className="flex items-start justify-between gap-4 border-b border-edge px-6 py-5">
          <div className="flex min-w-0 flex-col gap-1.5">
            {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
            {title && (
              <h3 className="flex items-center gap-2.5 text-title font-medium text-ink">
                <span
                  aria-hidden
                  className="inline-block h-3.5 w-px shrink-0"
                  style={{ background: "var(--signal)" }}
                />
                {title}
              </h3>
            )}
            {subtitle && <p className="text-body text-muted">{subtitle}</p>}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Section — a labeled group of panels with a heading + breathing room.       */
/* -------------------------------------------------------------------------- */
export function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h2 className="font-mono text-callout font-light text-ink">{title}</h2>
        {description && <p className="text-body text-muted">{description}</p>}
      </div>
      {children}
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* CountUp — requestAnimationFrame counter, 600ms ease-out, lands with a       */
/* single --signal pulse. The signature interaction.                          */
/* -------------------------------------------------------------------------- */
function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

function useCountUp(target: number, durationMs = 600): { value: number; done: boolean } {
  const [value, setValue] = useState(0);
  const [done, setDone] = useState(false);
  const raf = useRef<number>();

  useEffect(() => {
    setDone(false);
    let start: number | null = null;
    const tick = (ts: number) => {
      if (start === null) start = ts;
      const elapsed = ts - start;
      const t = Math.min(1, elapsed / durationMs);
      setValue(target * easeOutCubic(t));
      if (t < 1) {
        raf.current = requestAnimationFrame(tick);
      } else {
        setValue(target);
        setDone(true);
      }
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
    // Re-run when the target changes (e.g. range switch).
  }, [target, durationMs]);

  return { value, done };
}

/** A single number that counts up from 0 and pulses --signal as it lands. */
export function CountUp({
  value,
  decimals = 0,
  className = "",
}: {
  value: number;
  decimals?: number;
  className?: string;
}) {
  const { value: v, done } = useCountUp(value);
  const shown = decimals > 0 ? v.toFixed(decimals) : Math.round(v).toLocaleString();
  return (
    <span key={value} className={`${done ? "kpi-pulse" : ""} ${className}`}>
      {shown}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Kpi — eyebrow label, 48px DM Mono count-up number, signed delta chip.      */
/* -------------------------------------------------------------------------- */
export function Kpi({
  label,
  value,
  unit,
  deltaPct,
  decimals = 0,
  // For metrics where down is good (e.g. cycle time), a negative raw delta is
  // an improvement — flip which color/sign reads as "good".
  invertDelta = false,
  placeholder = false,
}: {
  label: string;
  value: number;
  unit?: string;
  deltaPct?: number | null;
  decimals?: number;
  invertDelta?: boolean;
  placeholder?: boolean;
}) {
  const hasDelta = deltaPct !== undefined && deltaPct !== null;
  const good = hasDelta ? (invertDelta ? deltaPct! < 0 : deltaPct! > 0) : true;
  const sign = hasDelta && deltaPct! > 0 ? "+" : "";

  return (
    <div className="relative flex flex-col gap-4 overflow-hidden rounded-lg border border-edge bg-surface px-6 py-7">
      <div className="flex items-center gap-2.5">
        <span
          aria-hidden
          className="inline-block h-3 w-px shrink-0"
          style={{ background: "var(--signal)" }}
        />
        <Eyebrow>{label}</Eyebrow>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-kpi font-light text-ink">
          {placeholder ? "--" : <CountUp value={value} decimals={decimals} />}
        </span>
        {unit && !placeholder && (
          <span className="font-mono text-body text-muted">{unit}</span>
        )}
      </div>
      <div className="h-4">
        {hasDelta && (
          <span
            className="font-mono text-body"
            style={{ color: good ? "var(--signal)" : "var(--negative)" }}
          >
            {sign}
            {deltaPct}%
            <span className="ml-1.5 text-muted">wow</span>
          </span>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* States                                                                     */
/* -------------------------------------------------------------------------- */
export function EmptyState({ message = "No data for this range." }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16">
      <span className="font-mono text-[48px] font-light leading-none text-muted">--</span>
      <span className="text-body text-muted">{message}</span>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16">
      <span className="font-mono text-[48px] font-light leading-none" style={{ color: "var(--negative)" }}>
        --
      </span>
      <span className="text-body text-muted">{message}</span>
    </div>
  );
}

/** Full-panel loading placeholder: just the sweep bar over an empty surface. */
export function LoadingPanel({ height = "h-72" }: { height?: string }) {
  return (
    <div className={`relative bg-surface ${height}`}>
      <div className="loadbar" aria-hidden />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Modal — centered --surface panel over a --void scrim. Closes on backdrop  */
/* click or Escape. No animation library — a plain fade via the .modal-in    */
/* class defined in globals.css.                                             */
/* -------------------------------------------------------------------------- */
export function Modal({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4 py-8"
      style={{ background: "rgba(0,0,0,0.6)" }}
      onClick={onClose}
    >
      <div
        className="modal-in flex max-h-full w-full max-w-lg flex-col border border-edge bg-surface"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b border-edge px-6 py-5">
          <div className="flex min-w-0 flex-col gap-1.5">
            <h3 className="flex items-center gap-2.5 text-title font-medium text-ink">
              <span
                aria-hidden
                className="inline-block h-3.5 w-px shrink-0"
                style={{ background: "var(--signal)" }}
              />
              {title}
            </h3>
            {subtitle && <p className="text-body text-muted">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 border border-edge px-2 py-1 text-body text-muted hover:text-ink"
          >
            ✕
          </button>
        </header>
        <div className="overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Recharts tooltip — --surface bg, 1px --edge border, no shadow, mono nums.  */
/* -------------------------------------------------------------------------- */
export function ChartTooltip({
  active,
  payload,
  label,
  valueSuffix = "",
}: {
  active?: boolean;
  payload?: { name: string; value: number; color: string; dataKey: string }[];
  label?: string;
  valueSuffix?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="border border-edge bg-surface px-3 py-2">
      {label != null && <div className="eyebrow mb-1.5">{label}</div>}
      <div className="flex flex-col gap-1">
        {payload.map((p) => (
          <div key={p.dataKey} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-body text-muted">
              <span
                className="inline-block h-2 w-2"
                style={{ background: p.color }}
                aria-hidden
              />
              {p.name}
            </span>
            <span className="font-mono text-body text-ink">
              {p.value == null ? "--" : p.value}
              {valueSuffix}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
