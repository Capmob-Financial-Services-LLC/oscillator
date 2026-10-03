"use client";

// At a glance: the 31 Oct push on one page. Who shipped what (points), whether
// it shipped when promised (delivery), what is late or due, and why some work
// is not scoring yet. Every other page stays; this one gathers them.

import { useInsight } from "@/lib/api";
import { useRange } from "@/components/shell";
import { EmptyState, ErrorState, Kpi, LoadingPanel, Panel, Section } from "@/components/ui";
import type {
  DatedIssue,
  DeliveryResp,
  DeliveryStat,
  Overview,
  PointsActorStat,
  PointsByActorResp,
  UnscoredResp,
  UnscoredTicketItem,
} from "@/lib/types";

const ORG = process.env.NEXT_PUBLIC_GITHUB_ORG ?? "Capmob-Financial-Services-LLC";
const DEADLINE = "2026-10-31";

// The 31 Oct plan (Capmob-AI/docs/plan-2026-10-31.md), sprint by sprint.
const SPRINTS = [
  { name: "S1", label: "Unblock and cut over", start: "2026-09-21", end: "2026-09-27" },
  { name: "S2", label: "The deal spine", start: "2026-09-28", end: "2026-10-04" },
  { name: "S3", label: "CapScore", start: "2026-10-05", end: "2026-10-11" },
  { name: "S4", label: "Matching and dashboard", start: "2026-10-12", end: "2026-10-18" },
  { name: "S5", label: "CapReport, hardening", start: "2026-10-19", end: "2026-10-25" },
  { name: "S6", label: "Pilot", start: "2026-10-26", end: "2026-10-31" },
];

const CATEGORY: Record<string, { label: string; color: string }> = {
  feature_fe: { label: "Frontend", color: "var(--xp-blue)" },
  feature_be: { label: "Backend", color: "var(--xp-teal)" },
  infra: { label: "Infra", color: "var(--xp-purple)" },
  bug_fix: { label: "Bug fixes", color: "var(--xp-coral)" },
  bug_find: { label: "Bugs found", color: "var(--xp-amber)" },
};
const OTHER = { label: "Other", color: "var(--muted)" };

// Why a ticket is not scoring, in plain words, and what to do about it.
const REASONS: Record<string, { label: string; fix: string; actionable: boolean }> = {
  missing_type: { label: "No type", fix: "Add one type:* label", actionable: true },
  missing_size: { label: "No size", fix: "Add size:s, size:m or size:l", actionable: true },
  missing_bug_fields: { label: "Bug details missing", fix: "Add sev:* and area:*", actionable: true },
  awaiting_triage: { label: "Bug not triaged", fix: "Add the triaged label", actionable: true },
  needs_review: { label: "Held for review", fix: "docs, perf, security and copy are reviewed before scoring", actionable: true },
  awaiting_close: { label: "Still open", fix: "Scores when it closes. Nothing to do.", actionable: false },
};

const today = () => new Date().toISOString().slice(0, 10);
const daysBetween = (a: string, b: string) =>
  Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);

function issueUrl(team: string | null, identifier: string | null): string | null {
  if (!team || !identifier?.startsWith("#")) return null;
  return `https://github.com/${ORG}/${team}/issues/${identifier.slice(1)}`;
}

export default function AtAGlancePage() {
  const { range, anchor, refreshKey } = useRange();
  const delivery = useInsight<DeliveryResp>("delivery", range, anchor, refreshKey);
  const points = useInsight<PointsByActorResp>("points/by-actor", range, anchor, refreshKey);
  const ov = useInsight<Overview>("overview", range, anchor, refreshKey);
  const unscored = useInsight<UnscoredResp>("points/unscored", range, anchor, refreshKey);
  const period = range === "day" ? "today" : range === "month" ? "this month" : range === "all" ? "all time" : "this week";

  return (
    <div className="flex flex-col gap-10">
      <Section
        title="At a glance"
        description="The 31 October push on one page: who shipped what, whether it shipped when promised, and what needs attention."
      >
        <SprintStrip />
      </Section>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <DeliveryKpi data={delivery.data} loading={delivery.loading} />
        <Kpi label={`Points ${period}`} value={sumPoints(points.data)} placeholder={points.loading} />
        <Kpi
          label={`Done ${period}`}
          value={ov.data?.throughput.current ?? 0}
          deltaPct={ov.data?.throughput.delta_pct}
          placeholder={ov.loading}
        />
        <Kpi
          label="Avg cycle time"
          value={(ov.data?.avg_cycle_hours.current ?? 0) / 24}
          unit="days"
          decimals={1}
          deltaPct={ov.data?.avg_cycle_hours.delta_pct}
          invertDelta
          placeholder={ov.loading || ov.data?.avg_cycle_hours.current == null}
        />
        <Kpi label="Overdue now" value={delivery.data?.totals.overdue ?? 0} placeholder={delivery.loading} />
      </div>

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-5">
        <div className="flex flex-col gap-4 xl:col-span-3">
          <Panel
            eyebrow="People"
            title="Points and delivery, side by side"
            subtitle={`Points: how much each person shipped ${period}. Delivery: of the work dated since S1, how much landed on time.`}
            loading={points.loading || delivery.loading}
          >
            <PeopleTable points={points.data?.actors ?? []} delivery={delivery.data?.by_actor ?? []} error={points.error ?? delivery.error} />
          </Panel>
          <Panel
            eyebrow="Scoring"
            title="Why some work is not scoring yet"
            subtitle="Points need the right labels. Each group says what is missing and how to fix it."
            loading={unscored.loading}
          >
            {unscored.error ? <ErrorState message={unscored.error} /> : <Unscored tickets={unscored.data?.tickets ?? []} />}
          </Panel>
        </div>
        <div className="xl:col-span-2">
          <Panel eyebrow="Deadlines" title="Late and coming up" subtitle="Open work past its Target date, and work due in the next 7 days." loading={delivery.loading}>
            {delivery.error ? <ErrorState message={delivery.error} /> : <Deadlines data={delivery.data} />}
          </Panel>
        </div>
      </div>

      <p className="text-body text-muted">
        <strong className="font-medium text-ink">How delivery is scored.</strong> Every issue with a Target date
        since S1 counts once for its assignee: closed on or before the date is on time; closed after it is late;
        still open past it is overdue and counts as a miss, like late work. Score = on time ÷ (on time + late +
        overdue). Cancelled and undated issues are left out. Points are unchanged and still follow the labels.
      </p>
    </div>
  );
}

function sumPoints(d: PointsByActorResp | null): number {
  return d ? d.actors.reduce((n, a) => n + a.total_points, 0) : 0;
}

// ---------------------------------------------------------------------------

function SprintStrip() {
  const now = today();
  const left = Math.max(0, daysBetween(now, DEADLINE));
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
        {SPRINTS.map((s) => {
          const state = now > s.end ? "past" : now >= s.start ? "now" : "next";
          const span = daysBetween(s.start, s.end) + 1;
          const done = state === "past" ? span : state === "now" ? daysBetween(s.start, now) + 1 : 0;
          return (
            <div
              key={s.name}
              className={`relative overflow-hidden rounded-lg border px-4 py-3 ${state === "now" ? "border-signal bg-surface" : "border-edge bg-surface"}`}
              aria-current={state === "now" ? "step" : undefined}
            >
              <div className="flex items-baseline justify-between">
                <span className={`font-mono text-title font-medium ${state === "next" ? "text-muted" : "text-ink"}`}>{s.name}</span>
                <span className="eyebrow">{state === "now" ? "Now" : state === "past" ? "Done" : ""}</span>
              </div>
              <div className="mt-1 truncate text-body text-muted">{s.label}</div>
              <div className="mt-1 text-eyebrow text-muted">
                {fmtDay(s.start)} to {fmtDay(s.end)}
              </div>
              <div className="absolute bottom-0 left-0 h-[3px] bg-signal" style={{ width: `${(100 * done) / span}%`, opacity: state === "past" ? 0.35 : 1 }} />
            </div>
          );
        })}
      </div>
      <p className="text-body text-muted">
        <span className="font-mono font-medium text-ink">{left}</span> days to the 31 October deadline.
      </p>
    </div>
  );
}

function DeliveryKpi({ data, loading }: { data: DeliveryResp | null; loading: boolean }) {
  const t = data?.totals;
  return (
    <div className="relative flex flex-col gap-3 overflow-hidden rounded-lg border border-edge bg-surface px-6 py-7">
      <span className="eyebrow">Delivery score</span>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-kpi font-light text-ink">{loading || t?.score == null ? "--" : t.score}</span>
        {!loading && t?.score != null && <span className="font-mono text-body text-muted">% on time</span>}
      </div>
      {t && <OnTimeBar s={t} />}
    </div>
  );
}

function OnTimeBar({ s, compact = false }: { s: DeliveryStat; compact?: boolean }) {
  const total = s.on_time + s.late + s.overdue;
  if (!total) return <span className="text-body text-muted">Nothing due yet</span>;
  const seg = [
    { n: s.on_time, label: "on time", color: "var(--xp-teal)" },
    { n: s.late, label: "late", color: "var(--xp-amber)" },
    { n: s.overdue, label: "overdue", color: "var(--negative)" },
  ];
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-void" role="img" aria-label={seg.map((x) => `${x.n} ${x.label}`).join(", ")}>
        {seg.map((x) => x.n > 0 && <div key={x.label} style={{ width: `${(100 * x.n) / total}%`, background: x.color }} />)}
      </div>
      {!compact && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-body text-muted">
          {seg.map((x) => (
            <span key={x.label} className="inline-flex items-center gap-1.5">
              <i className="inline-block h-2 w-2 rounded-full" style={{ background: x.color }} />
              <span className="font-mono text-ink">{x.n}</span> {x.label}
            </span>
          ))}
          {s.avg_days_late != null && <span>avg {s.avg_days_late} days late</span>}
        </div>
      )}
    </div>
  );
}

function PeopleTable({ points, delivery, error }: { points: PointsActorStat[]; delivery: DeliveryStat[]; error: string | null }) {
  if (error) return <ErrorState message={error} />;
  const people = new Map<string, { name: string; avatar: string | null; pts?: PointsActorStat; del?: DeliveryStat }>();
  for (const p of points) people.set(p.name ?? `#${p.actor_id}`, { name: p.name ?? "Unknown", avatar: p.avatar_url, pts: p });
  for (const d of delivery) {
    const cur = people.get(d.name) ?? { name: d.name, avatar: d.avatar_url };
    people.set(d.name, { ...cur, del: d });
  }
  const rows = [...people.values()].sort((a, b) => (b.pts?.total_points ?? 0) - (a.pts?.total_points ?? 0));
  if (!rows.length) return <EmptyState message="No points or dated work for this range." />;
  const max = Math.max(1, ...rows.map((r) => r.pts?.total_points ?? 0));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-body">
        <thead>
          <tr className="border-b border-edge text-left">
            <th className="eyebrow px-6 py-3 font-medium">Person</th>
            <th className="eyebrow px-3 py-3 font-medium">Points</th>
            <th className="eyebrow px-3 py-3 font-medium">Delivery</th>
            <th className="eyebrow px-6 py-3 text-right font-medium">Due 7d</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-b border-edge last:border-0 align-top">
              <td className="px-6 py-4">
                <div className="flex items-center gap-3">
                  {r.avatar ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={r.avatar} alt="" className="h-8 w-8 rounded-full" />
                  ) : (
                    <span className="grid h-8 w-8 place-items-center rounded-full bg-void font-mono text-eyebrow">{r.name.slice(0, 2).toUpperCase()}</span>
                  )}
                  <span className="font-medium text-ink">{r.name}</span>
                </div>
              </td>
              <td className="min-w-[220px] px-3 py-4">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-title font-medium text-ink">{r.pts?.total_points ?? 0}</span>
                </div>
                <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-void" style={{ width: `${(100 * (r.pts?.total_points ?? 0)) / max}%`, minWidth: r.pts?.total_points ? 6 : 0 }}>
                  {(r.pts?.by_category ?? []).map((c) => (
                    <div key={c.category} title={`${(CATEGORY[c.category] ?? OTHER).label}: ${c.points}`} style={{ flex: c.points, background: (CATEGORY[c.category] ?? OTHER).color }} />
                  ))}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-x-2.5 text-eyebrow text-muted">
                  {(r.pts?.by_category ?? []).sort((a, b) => b.points - a.points).map((c) => (
                    <span key={c.category}>
                      {(CATEGORY[c.category] ?? OTHER).label} <span className="font-mono text-ink">{c.points}</span>
                    </span>
                  ))}
                </div>
              </td>
              <td className="min-w-[220px] px-3 py-4">
                {r.del ? (
                  <div className="flex flex-col gap-1.5">
                    <span className="font-mono text-title font-medium text-ink">{r.del.score == null ? "--" : `${r.del.score}%`}</span>
                    <OnTimeBar s={r.del} />
                  </div>
                ) : (
                  <span className="text-muted">No dated work</span>
                )}
              </td>
              <td className="px-6 py-4 text-right font-mono text-title text-ink">{r.del?.due_soon ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Deadlines({ data }: { data: DeliveryResp | null }) {
  if (!data) return null;
  if (!data.overdue.length && !data.due_soon.length) return <EmptyState message="Nothing late and nothing due this week." />;
  return (
    <div className="flex flex-col">
      <DatedList title={`Overdue (${data.overdue.length})`} items={data.overdue.slice(0, 8)} tone="var(--negative)" suffix="late" more={data.overdue.length - 8} />
      <DatedList title={`Due in 7 days (${data.due_soon.length})`} items={data.due_soon.slice(0, 8)} tone="var(--xp-blue)" suffix="left" more={data.due_soon.length - 8} />
    </div>
  );
}

function DatedList({ title, items, tone, suffix, more }: { title: string; items: DatedIssue[]; tone: string; suffix: string; more: number }) {
  if (!items.length) return null;
  return (
    <div className="border-b border-edge last:border-0">
      <div className="eyebrow px-6 pb-2 pt-4">{title}</div>
      <ul>
        {items.map((d) => (
          <li key={`${d.team}${d.identifier}`} className="flex items-start gap-3 px-6 py-2.5">
            <span className="mt-0.5 shrink-0 rounded-full px-2 py-0.5 font-mono text-eyebrow" style={{ background: tone, color: "#fff" }}>
              {d.days}d {suffix}
            </span>
            <div className="min-w-0">
              <IssueLink team={d.team} identifier={d.identifier} url={d.url} title={d.title} />
              <div className="text-eyebrow text-muted">
                {d.assignee ?? "Unassigned"} · due {fmtDay(d.target_date)}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {more > 0 && <div className="px-6 pb-3 text-body text-muted">and {more} more</div>}
    </div>
  );
}

function Unscored({ tickets }: { tickets: UnscoredTicketItem[] }) {
  if (!tickets.length) return <EmptyState message="Everything closed is scoring." />;
  const groups = new Map<string, UnscoredTicketItem[]>();
  for (const t of tickets) groups.set(t.reason, [...(groups.get(t.reason) ?? []), t]);
  const ordered = [...groups.entries()].sort(
    ([a, x], [b, y]) => Number(REASONS[b]?.actionable ?? true) - Number(REASONS[a]?.actionable ?? true) || y.length - x.length,
  );
  return (
    <div className="grid grid-cols-1 gap-px bg-edge md:grid-cols-2">
      {ordered.map(([reason, items]) => {
        const r = REASONS[reason] ?? { label: reason, fix: "", actionable: true };
        return (
          <details key={reason} className="group bg-surface px-6 py-4" open={r.actionable && items.length <= 6}>
            <summary className="flex cursor-pointer list-none items-baseline justify-between gap-3">
              <span className="flex flex-col gap-0.5">
                <span className={`text-title font-medium ${r.actionable ? "text-ink" : "text-muted"}`}>{r.label}</span>
                <span className="text-body text-muted">{r.fix}</span>
              </span>
              <span className={`font-mono text-callout font-light ${r.actionable ? "text-signal" : "text-muted"}`}>{items.length}</span>
            </summary>
            <ul className="mt-3 flex flex-col gap-1.5">
              {items.slice(0, 12).map((t) => (
                <li key={t.issue_id} className="text-body">
                  <IssueLink team={t.team} identifier={t.identifier} url={issueUrl(t.team, t.identifier)} title={t.title} />
                  <span className="text-muted"> · {t.assignee_name ?? "Unassigned"}</span>
                </li>
              ))}
              {items.length > 12 && <li className="text-body text-muted">and {items.length - 12} more</li>}
            </ul>
          </details>
        );
      })}
    </div>
  );
}

function IssueLink({ team, identifier, url, title }: { team: string | null; identifier: string | null; url: string | null; title: string | null }) {
  const label = (
    <>
      <span className="font-mono text-muted">
        {team ? `${team} ` : ""}
        {identifier}
      </span>{" "}
      <span className="text-ink">{title}</span>
    </>
  );
  return url ? (
    <a href={url} target="_blank" rel="noreferrer" className="hover:underline">
      {label}
    </a>
  ) : (
    <span>{label}</span>
  );
}

function fmtDay(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}
