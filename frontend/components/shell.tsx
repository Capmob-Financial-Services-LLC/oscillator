"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState, useCallback } from "react";

import type { Range } from "@/lib/types";
import { todayUTC } from "@/lib/dates";
import { DateScrubber } from "@/components/date-scrubber";
import { Segmented } from "@/components/segmented";

const RANGES: Range[] = ["day", "week", "month", "all"];

interface RangeCtx {
  range: Range;
  setRange: (r: Range) => void;
  anchor: string; // YYYY-MM-DD — the day/week/month the dashboard is focused on
  setAnchor: (d: string) => void;
  refreshKey: number;
  refresh: () => void;
}
const RangeContext = createContext<RangeCtx>({
  range: "week",
  setRange: () => {},
  anchor: todayUTC(),
  setAnchor: () => {},
  refreshKey: 0,
  refresh: () => {},
});

export function useRange(): RangeCtx {
  return useContext(RangeContext);
}

const NAV = [
  { href: "/at-a-glance", label: "At a glance" },
  { href: "/", label: "Overview" },
  { href: "/trends", label: "Trends" },
  { href: "/people", label: "People" },
  { href: "/squad", label: "Squad" },
  { href: "/teams", label: "Cycles" },
  { href: "/report", label: "Report" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [range, setRangeState] = useState<Range>("week");
  const [anchor, setAnchor] = useState<string>(todayUTC());
  const [refreshKey, setRefreshKey] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    // URL params win (deep-linkable), then fall back to the saved range.
    const params = new URLSearchParams(window.location.search);
    const urlRange = params.get("range") as Range | null;
    const urlAnchor = params.get("anchor");
    const saved = window.localStorage.getItem("range") as Range | null;
    if (urlRange && RANGES.includes(urlRange)) setRangeState(urlRange);
    else if (saved && RANGES.includes(saved)) setRangeState(saved);
    if (urlAnchor && /^\d{4}-\d{2}-\d{2}$/.test(urlAnchor)) setAnchor(urlAnchor);
  }, []);

  const setRange = (r: Range) => {
    setRangeState(r);
    window.localStorage.setItem("range", r);
  };

  const refresh = useCallback(() => {
    setRefreshing(true);
    setRefreshKey((k) => k + 1);
    // Visual feedback: keep the spinner for 1 second minimum so the user
    // knows the refresh was triggered, even if data comes back instantly.
    setTimeout(() => setRefreshing(false), 1000);
  }, []);

  return (
    <RangeContext.Provider value={{ range, setRange, anchor, setAnchor, refreshKey, refresh }}>
      <div className="min-h-screen bg-void">
        {/* Top navigation rail — 56px, --edge bottom border only. Inner content
            is centered to the same max-width gutter as the page body. */}
        <header className="no-print sticky top-0 z-30 h-14 border-b border-edge bg-void">
          <div className="mx-auto flex h-full max-w-[1600px] items-stretch px-4 sm:px-6 lg:px-10">
            <Link
              href="/"
              className="-ml-1 flex shrink-0 items-center gap-3 pr-4 text-[14px] font-semibold tracking-eyebrow text-ink sm:pr-10"
            >
              <span
                className="inline-block h-2 w-2"
                style={{ background: "var(--signal)" }}
                aria-hidden
              />
              OSCILLATOR
            </Link>
            {/* Scrolls horizontally rather than wrapping/clipping once the six
                links no longer fit a narrow viewport. */}
            <nav className="flex items-stretch gap-1 overflow-x-auto">
              {NAV.map((item) => {
                const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="relative flex shrink-0 items-center px-3 text-nav font-medium transition-colors hover:text-ink sm:px-5"
                    style={{ color: active ? "var(--ink)" : "var(--muted)" }}
                  >
                    {item.label}
                    {active && (
                      <span
                        className="absolute inset-x-4 -bottom-px h-0.5"
                        style={{ background: "var(--signal)" }}
                        aria-hidden
                      />
                    )}
                  </Link>
                );
              })}
            </nav>
          </div>
        </header>

        {/* Command bar — 52px, --surface; range selector + scrubber share the
            centered gutter so controls line up with the content below. */}
        <div className="no-print sticky top-14 z-20 border-b border-edge bg-surface">
          <div className="mx-auto flex h-[52px] max-w-[1600px] items-center gap-3 px-4 sm:gap-6 sm:px-6 lg:px-10">
            <Eyebrowed label="RANGE">
              <Segmented
                options={[
                  { value: "day", label: "Day" },
                  { value: "week", label: "Week" },
                  { value: "month", label: "Month" },
                  { value: "all", label: "All" },
                ]}
                value={range}
                onChange={(v) => setRange(v as Range)}
              />
            </Eyebrowed>

            {/* Spacer pushes the refresh button to the right */}
            <div className="flex-1" />

            <button
              id="refresh-data-btn"
              onClick={refresh}
              disabled={refreshing}
              aria-label="Refresh dashboard data"
              className="flex shrink-0 items-center gap-2 rounded px-2 py-1.5 text-[12px] font-medium tracking-eyebrow transition-all sm:px-3"
              style={{
                color: refreshing ? "var(--muted)" : "var(--signal)",
                border: "1px solid",
                borderColor: refreshing ? "var(--edge)" : "var(--signal)",
                opacity: refreshing ? 0.6 : 1,
                cursor: refreshing ? "not-allowed" : "pointer",
              }}
            >
              {/* Spinner or static icon */}
              <svg
                width="13"
                height="13"
                viewBox="0 0 16 16"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                style={{
                  animation: refreshing ? "spin 0.8s linear infinite" : "none",
                  color: "inherit",
                }}
              >
                <path
                  d="M13.65 2.35A8 8 0 1 0 15 8h-2a6 6 0 1 1-1.05-3.39L9 7h6V1l-1.35 1.35Z"
                  fill="currentColor"
                />
              </svg>
              {/* Text hides below sm to keep the row from overflowing next to
                  the range control; the icon alone stays a clear affordance. */}
              <span className="hidden sm:inline">{refreshing ? "Refreshing…" : "Refresh"}</span>
            </button>
          </div>
        </div>

        {/* Date scrubber strip — the secondary control rail */}
        <div className="no-print border-b border-edge bg-void">
          <div className="mx-auto max-w-[1600px] px-4 sm:px-6 lg:px-10">
            <DateScrubber />
          </div>
        </div>

        {/* Content — centered, generous gutters + vertical rhythm so panels
            breathe instead of bleeding edge-to-edge. */}
        <main className="mx-auto min-h-[60vh] max-w-[1600px] px-4 py-6 sm:px-6 sm:py-8 lg:px-10 lg:py-10">
          {children}
        </main>
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </RangeContext.Provider>
  );
}

function Eyebrowed({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 sm:gap-3.5">
      {/* Hidden below sm — the segmented control's own labels (Day/Week/...)
          already say what this is; freeing the space matters more there. */}
      <span className="eyebrow hidden sm:inline">{label}</span>
      {children}
    </div>
  );
}
