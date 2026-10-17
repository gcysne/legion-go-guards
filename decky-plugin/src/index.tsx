import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaThermometerHalf } from "react-icons/fa";

type Toast = { title: string; body: string; critical?: boolean };
type GuardEvent = { time: string; severity: string; kind: string; summary: string };
type Status = { services: Record<string, string>; events: GuardEvent[] };

const popToasts = callable<[], Toast[]>("pop_toasts");
const getStatus = callable<[], Status>("get_status");
const testAlerts = callable<[], string>("test_alerts");

const POLL_MS = 3000;

function showToast(t: Toast) {
  toaster.toast({
    title: t.title,
    body: t.body,
    critical: !!t.critical,
    duration: t.critical ? 15000 : 8000,
    playSound: false, // the guard already played its own alert sound
  });
}

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [testResult, setTestResult] = useState<string>("");

  const refresh = () => getStatus().then(setStatus).catch(() => setStatus(null));
  useEffect(() => {
    refresh();
  }, []);

  return (
    <>
      <PanelSection title="Services">
        {status ? (
          Object.entries(status.services).map(([name, state]) => (
            <PanelSectionRow key={name}>
              <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                <span>{name}</span>
                <span style={{ color: state === "active" ? "#7bd88f" : "#ff6b6b" }}>{state}</span>
              </div>
            </PanelSectionRow>
          ))
        ) : (
          <PanelSectionRow>Loading...</PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={refresh}>
            Refresh
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={async () => setTestResult(await testAlerts())}
          >
            Send test alerts
          </ButtonItem>
        </PanelSectionRow>
        {testResult && <PanelSectionRow>{testResult}</PanelSectionRow>}
      </PanelSection>
      <PanelSection title="Recent events">
        {status && status.events.length === 0 && <PanelSectionRow>No events yet.</PanelSectionRow>}
        {status?.events.map((e, i) => (
          <PanelSectionRow key={i}>
            <div style={{ fontSize: "12px", lineHeight: "1.3" }}>
              <div style={{ color: e.severity === "critical" || e.severity === "error" ? "#ff6b6b" : e.severity === "warning" ? "#ffd166" : undefined }}>
                {e.time.slice(5, 16)} {e.kind}
              </div>
              <div style={{ opacity: 0.8, wordBreak: "break-word" }}>{e.summary.slice(0, 140)}</div>
            </div>
          </PanelSectionRow>
        ))}
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  // Poll for alerts written by the guards; each poll also marks Decky as alive.
  const timer = setInterval(async () => {
    try {
      (await popToasts()).forEach(showToast);
    } catch (e) {
      console.error("legion-go-guards: poll failed", e);
    }
  }, POLL_MS);

  return {
    name: "Legion Go Guards",
    titleView: <div className={staticClasses.Title}>Legion Go Guards</div>,
    content: <Content />,
    icon: <FaThermometerHalf />,
    onDismount() {
      clearInterval(timer);
    },
  };
});
