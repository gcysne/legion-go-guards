// Full page (cog in the Quick Access title): Events, Boot history and About tabs.
import { Field, Navigation, Tabs } from "@decky/ui";
import { callable } from "@decky/api";
import { ReactNode, useEffect, useState } from "react";
import { AboutTab } from "./about";

export const PAGE_ROUTE = "/legion-go-guards";
const FIRST_TAB = "events";
let initialTab = FIRST_TAB;

type GuardEvent = { time: string; severity: string; kind: string; summary: string; source: string };
const getEvents = callable<[number], GuardEvent[]>("get_events");
const getBootHistory = callable<[number], string[]>("get_boot_history");

export function openPage(tab = FIRST_TAB) {
  initialTab = tab;
  Navigation.CloseSideMenus();
  Navigation.Navigate(PAGE_ROUTE);
}

const DIM = { fontSize: 12, color: "#8b929a" } as const;
const COLORS: Record<string, string> = { critical: "#ff6b6b", error: "#ff6b6b", warning: "#ffd166" };

function Empty({ children }: { children: ReactNode }) {
  return <div style={{ ...DIM, padding: "16px 0" }}>{children}</div>;
}

function EventsTab() {
  const [rows, setRows] = useState<GuardEvent[] | null>(null);
  useEffect(() => { getEvents(200).then(setRows).catch(() => setRows([])); }, []);
  if (!rows) return <Empty>Loading…</Empty>;
  if (!rows.length) return <Empty>No events yet.</Empty>;
  return (
    <>
      {rows.map((e, i) => (
        <Field key={i} focusable label={<span style={{ color: COLORS[e.severity] }}>{e.kind.replace(/_/g, " ")}</span>}
          description={e.summary.split("\n")[0].slice(0, 300)}>
          <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>
            <div>{e.time.slice(0, 16)}</div>
            <div style={DIM}>{e.severity}</div>
          </div>
        </Field>
      ))}
    </>
  );
}

function BootsTab() {
  const [rows, setRows] = useState<string[] | null>(null);
  useEffect(() => { getBootHistory(100).then(setRows).catch(() => setRows([])); }, []);
  if (!rows) return <Empty>Loading…</Empty>;
  if (!rows.length) return <Empty>No boots recorded yet.</Empty>;
  return (
    <>
      <div style={{ ...DIM, margin: "8px 0" }}>How each earlier boot ended, newest first.</div>
      {rows.map((line, i) => {
        const [when, cat, ...rest] = line.split(/\s{2,}/);
        return (
          <Field key={i} focusable label={<span style={{ color: cat?.startsWith("normal") ? undefined : "#ffd166" }}>
            {(cat ?? "").replace(/_/g, " ")}</span>} description={rest.join("  ")}>
            <div style={{ whiteSpace: "nowrap" }}>{when}</div>
          </Field>
        );
      })}
    </>
  );
}

function Page({ children }: { children: ReactNode }) {
  return <div style={{ padding: "0 24px 24px" }}>{children}</div>;
}

export function GuardsPage() {
  const [tab, setTab] = useState(initialTab);
  useEffect(() => () => { initialTab = FIRST_TAB; }, []);
  return (
    <div style={{ marginTop: 40, height: "calc(100% - 40px)", background: "#0e141b" }}>
      <Tabs activeTab={tab} onShowTab={setTab} autoFocusContents tabs={[
        { id: "events", title: "Events", content: <Page><EventsTab /></Page> },
        { id: "boots", title: "Boot history", content: <Page><BootsTab /></Page> },
        { id: "about", title: "About", content: <Page><AboutTab /></Page> },
      ]} />
    </div>
  );
}
