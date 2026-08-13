import { ActivityTracker } from "./activity.js";
import { ActivityUI } from "./activity-ui.js";
import { connectTelemetryStream, connectUniverseStream, requestAnalyst } from "./api.js";
import { AnalystUI } from "./analyst-ui.js";
import { ObservatoryState } from "./state.js";
import { TelemetryUI } from "./telemetry-ui.js";
import { TokenUI } from "./token-ui.js";
import { TokenUniverseView } from "./views/token-universe-view.js";

const state = new ObservatoryState();
const activity = new ActivityTracker();
const streamStatus = document.querySelector("#stream-status");
const stageElement = document.querySelector("#universe-stage");
const flowStageElement = document.querySelector("#operational-flow-stage");
const viewUniverseButton = document.querySelector("#view-token-universe");
const viewFlowButton = document.querySelector("#view-operational-flow");
const toolbarLabel = document.querySelector("#primary-view-label");
const toolbarNote = document.querySelector("#primary-view-note");
const workspace = document.querySelector("#workspace");
const sidePanel = document.querySelector("#side-panel");
const sidePanelToggle = document.querySelector("#side-panel-toggle");
const sidePanelResizer = document.querySelector("#side-panel-resizer");
const SIDE_PANEL_MIN = 360;
const SIDE_PANEL_MAX = 640;

const telemetryUI = new TelemetryUI(flowStageElement);
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

    const move = pointerEvent => {
      setSidePanelWidth(startWidth + startX - pointerEvent.clientX);
    };
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

function setPrimaryMode(mode) {
  const nextMode = mode === "flow" ? "flow" : "universe";
  if (nextMode === "flow" && !flowReady) {
    ensureOperationalFlow()
      .then(() => setPrimaryMode("flow"))
      .catch(() => {});
    return;
  }

  primaryMode = nextMode;
  const flowVisible = primaryMode === "flow";
  stageElement.classList.toggle("hidden", flowVisible);
  viewUniverseButton.classList.toggle("active", !flowVisible);
  viewFlowButton.classList.toggle("active", flowVisible);
  viewUniverseButton.setAttribute("aria-pressed", String(!flowVisible));
  viewFlowButton.setAttribute("aria-pressed", String(flowVisible));
  toolbarLabel.textContent = flowVisible ? "OPERATIONAL FLOW · LIVE" : "TOKEN UNIVERSE · LIVE";
  toolbarNote.textContent = flowVisible
    ? "Volatile runtime telemetry · particles are work pulses, not tokens"
    : "Live population · search reaches every active token";
  if (flowReady) telemetryUI.setVisible(flowVisible);
  if (!flowVisible) renderView();
}

function setupPrimaryViewSwitch() {
  viewUniverseButton.addEventListener("click", () => setPrimaryMode("universe"));
  viewFlowButton.addEventListener("click", () => setPrimaryMode("flow"));
}

function renderView(events = []) {
  currentView.render({
    tokens: state.values(),
    selectedMint: state.selectedMint,
    events,
  });
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
  // Read the already-canonical browser population. This does not create a second
  // state owner; it only keeps the visual Tracking reservoir aligned with ACTIVE.
  telemetryUI.setActiveCount(state.values().length);
}

function applySnapshot(snapshot) {
  const selectedBefore = state.selectedMint;
  const tokens = Array.isArray(snapshot?.tokens) ? snapshot.tokens : [];
  const timestamp = Date.parse(snapshot?.generated_at);

  activity.reset();
  state.load(tokens);
  syncFlowPopulation();
  renderView();
  tokenUI.enableSearch();
  tokenUI.renderSelected();
  tokenUI.refreshSearch();

  if (state.selectedMint !== selectedBefore) analystUI.selectionChanged();
  else analystUI.populationChanged();

  renderDerivedState(Number.isFinite(timestamp) ? timestamp : Date.now());
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

  tokenUI = new TokenUI({ state, onSelect: selectToken });
  activityUI = new ActivityUI({ state, onSelect: selectToken });
  analystUI = new AnalystUI({ state, requestAnalyst, onSelect: selectToken });
  analystUI.sync(false);
  setPrimaryMode("universe");

  // Functional streams are established before the optional WP4 presentation.
  // A visual rendering failure must never take the canonical population offline.
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

  // Presentation initialization is intentionally isolated from the functional core.
  ensureOperationalFlow().catch(() => {});
}

setInterval(() => {
  if (tokenUI && activityUI) renderDerivedState();
  telemetryUI.render();
}, 1000);

bootstrap().catch(error => {
  console.error(error);
  setStreamStatus("error", "Offline");
});
