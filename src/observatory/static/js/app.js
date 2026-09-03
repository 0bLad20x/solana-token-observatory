import { ActivityTracker } from "./activity.js";
import { ActivityUI } from "./activity-ui.js";
import { connectTelemetryStream, connectUniverseStream, requestAnalyst } from "./api.js";
import { AnalystUI } from "./analyst-ui.js";
import { MARKET_PULSE_SAMPLE_INTERVAL_MS, MarketPulseSeries } from "./market-pulse.js";
import { ObservatoryState } from "./state.js";
import { TelemetryUI } from "./telemetry-ui.js";
import { TokenUI } from "./token-ui.js";
import { MarketPulseView } from "./views/market-pulse-view.js";
import { TokenUniverseView } from "./views/token-universe-view.js";

const state = new ObservatoryState();
const activity = new ActivityTracker();
const pulseSeries = new MarketPulseSeries();
const streamStatus = document.querySelector("#stream-status");
const stageElement = document.querySelector("#universe-stage");
const flowStageElement = document.querySelector("#operational-flow-stage");
const pulseStageElement = document.querySelector("#market-pulse-stage");
const viewUniverseButton = document.querySelector("#view-token-universe");
const viewFlowButton = document.querySelector("#view-operational-flow");
const viewPulseButton = document.querySelector("#view-market-pulse");
const toolbarLabel = document.querySelector("#primary-view-label");
const toolbarNote = document.querySelector("#primary-view-note");
const workspace = document.querySelector("#workspace");
const sidePanel = document.querySelector("#side-panel");
const sidePanelToggle = document.querySelector("#side-panel-toggle");
const sidePanelResizer = document.querySelector("#side-panel-resizer");
const SIDE_PANEL_MIN = 360;
const SIDE_PANEL_MAX = 640;

const telemetryUI = new TelemetryUI(flowStageElement);
const pulseView = new MarketPulseView(pulseStageElement);
let currentView = null;
let tokenUI = null;
let activityUI = null;
let analystUI = null;
let primaryMode = "universe";
let flowReady = false;
let flowInitPromise = null;

function setStreamStatus(mode, label) {
  streamStatus.className = `stream-status ${mode}`;
  streamStatus.querySelector("span").textContent = label;
}

function setSidePanelWidth(width) {
  const bounded = Math.min(SIDE_PANEL_MAX, Math.max(SIDE_PANEL_MIN, width));
  workspace.style.setProperty("--side-panel-width", `${Math.round(bounded)}px`);
}

function setSidePanelCollapsed(collapsed) {
  workspace.classList.toggle("panel-collapsed", collapsed);
  sidePanelToggle.setAttribute("aria-expanded", String(!collapsed));
  sidePanelToggle.textContent = collapsed ? "Show" : "Hide";
}

function setupSidePanel() {
  sidePanelToggle.addEventListener("click", () => {
    setSidePanelCollapsed(!workspace.classList.contains("panel-collapsed"));
  });
  sidePanelResizer.addEventListener("keydown", event => {
    if (workspace.classList.contains("panel-collapsed")) return;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const width = sidePanel.getBoundingClientRect().width;
    setSidePanelWidth(width + (event.key === "ArrowLeft" ? 24 : -24));
  });
  sidePanelResizer.addEventListener("pointerdown", event => {
    if (workspace.classList.contains("panel-collapsed")) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = sidePanel.getBoundingClientRect().width;
    const move = pointerEvent => setSidePanelWidth(startWidth + startX - pointerEvent.clientX);
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  });
}

function ensureOperationalFlow() {
  if (flowInitPromise) return flowInitPromise;
  flowInitPromise = telemetryUI.init()
    .then(() => {
      flowReady = true;
      telemetryUI.setVisible(primaryMode === "flow");
    })
    .catch(error => {
      console.error("operational_flow_init_failed", error);
      telemetryUI.setConnection("Presentation error");
      throw error;
    });
  return flowInitPromise;
}

function renderPulse() {
  pulseView.render({ current: pulseSeries.current(), history: pulseSeries.history() });
}

function setPrimaryMode(mode) {
  const nextMode = mode === "flow" ? "flow" : mode === "pulse" ? "pulse" : "universe";
  if (nextMode === "flow" && !flowReady) {
    ensureOperationalFlow().then(() => setPrimaryMode("flow")).catch(() => {});
    return;
  }
  primaryMode = nextMode;
  const universeVisible = primaryMode === "universe";
  const flowVisible = primaryMode === "flow";
  const pulseVisible = primaryMode === "pulse";
  stageElement.classList.toggle("hidden", !universeVisible);
  flowStageElement.classList.toggle("hidden", !flowVisible);
  pulseStageElement.classList.toggle("hidden", !pulseVisible);
  viewUniverseButton.classList.toggle("active", universeVisible);
  viewFlowButton.classList.toggle("active", flowVisible);
  viewPulseButton.classList.toggle("active", pulseVisible);
  viewUniverseButton.setAttribute("aria-pressed", String(universeVisible));
  viewFlowButton.setAttribute("aria-pressed", String(flowVisible));
  viewPulseButton.setAttribute("aria-pressed", String(pulseVisible));

  if (flowVisible) {
    toolbarLabel.textContent = "OPERATIONAL FLOW · LIVE";
    toolbarNote.textContent = "Volatile runtime telemetry · particles are work pulses, not tokens";
  } else if (pulseVisible) {
    toolbarLabel.textContent = "MARKET PULSE · LIVE";
    toolbarNote.textContent = "Rolling 5m market activity · 1s in-memory samples";
  } else {
    toolbarLabel.textContent = "TOKEN UNIVERSE · LIVE";
    toolbarNote.textContent = "Live population · search reaches every active token";
  }

  if (flowReady) telemetryUI.setVisible(flowVisible);
  if (universeVisible) renderView();
  if (pulseVisible) renderPulse();
}

function setupPrimaryViewSwitch() {
  viewUniverseButton.addEventListener("click", () => setPrimaryMode("universe"));
  viewFlowButton.addEventListener("click", () => setPrimaryMode("flow"));
  viewPulseButton.addEventListener("click", () => setPrimaryMode("pulse"));
}

function renderView(events = []) {
  currentView.render({ tokens: state.values(), selectedMint: state.selectedMint, events });
}

function selectToken(mint) {
  if (!state.select(mint)) return false;
  renderView();
  tokenUI.renderSelected();
  analystUI.selectionChanged();
  return true;
}

function renderDerivedState(now = Date.now()) {
  const changed = activity.changedCount(now);
  const ranked = activity.topVolumeActivity(now);
  tokenUI.renderStats(changed);
  activityUI.render(ranked);
}

function syncFlowPopulation() {
  telemetryUI.setActiveCount(state.activeTokens().length);
}

function applySnapshot(snapshot) {
  const selectedBefore = state.selectedMint;
  const tokens = Array.isArray(snapshot?.tokens) ? snapshot.tokens : [];
  const timestamp = Date.parse(snapshot?.generated_at);
  const sampleAt = Number.isFinite(timestamp) ? timestamp : Date.now();
  activity.reset();
  state.load(tokens);
  pulseSeries.sample(state.values(), sampleAt);
  syncFlowPopulation();
  renderView();
  if (primaryMode === "pulse") renderPulse();
  tokenUI.enableSearch();
  tokenUI.renderSelected();
  tokenUI.refreshSearch();
  if (state.selectedMint !== selectedBefore) analystUI.selectionChanged();
  else analystUI.populationChanged();
  renderDerivedState(sampleAt);
}

function applyDelta(events, generatedAt) {
  const timestamp = Date.parse(generatedAt);
  for (const event of events) {
    state.applyEvent(event);
    activity.applyEvent(event, timestamp);
  }
  syncFlowPopulation();
  renderView(events);
  tokenUI.renderSelected();
  tokenUI.refreshSearch();
  analystUI.populationChanged();
  renderDerivedState(Number.isFinite(timestamp) ? timestamp : Date.now());
}

async function bootstrap() {
  setupSidePanel();
  setupPrimaryViewSwitch();
  currentView = new TokenUniverseView(stageElement, { onSelect: selectToken });
  await currentView.init();
  pulseView.init();
  tokenUI = new TokenUI({ state, onSelect: selectToken });
  activityUI = new ActivityUI({ state, onSelect: selectToken });
  analystUI = new AnalystUI({ state, requestAnalyst, onSelect: selectToken });
  analystUI.sync(false);
  setPrimaryMode("universe");
  connectUniverseStream({
    onOpen: () => setStreamStatus("live", "Live"),
    onError: () => setStreamStatus("error", "Reconnecting"),
    onSnapshot: applySnapshot,
    onDelta: delta => applyDelta(delta.events || [], delta.generated_at),
  });
  connectTelemetryStream({
    onOpen: () => telemetryUI.setConnection("Live"),
    onError: () => telemetryUI.setConnection("Reconnecting"),
    onSnapshot: snapshot => telemetryUI.load(snapshot),
    onEvent: event => telemetryUI.apply(event),
  });
  ensureOperationalFlow().catch(() => {});
}

setInterval(() => {
  if (tokenUI && activityUI) renderDerivedState();
  telemetryUI.render();
}, 1000);

setInterval(() => {
  if (!tokenUI) return;
  if (pulseSeries.sample(state.values()) && primaryMode === "pulse") renderPulse();
}, MARKET_PULSE_SAMPLE_INTERVAL_MS);

bootstrap().catch(error => {
  console.error(error);
  setStreamStatus("error", "Offline");
});
