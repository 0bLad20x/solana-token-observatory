import { ActivityTracker } from "./activity.js";
import { ActivityUI } from "./activity-ui.js";
import { connectTelemetryStream, connectUniverseStream, fetchToken, fetchUniverse, requestAnalyst } from "./api.js";
import { AnalystUI } from "./analyst-ui.js";
import { ObservatoryState } from "./state.js";
import { TelemetryUI } from "./telemetry-ui.js";
import { TokenUI } from "./token-ui.js";
import { SimpleTokenView } from "./views/simple-token-view.js";

const state = new ObservatoryState();
const activity = new ActivityTracker();
const telemetryUI = new TelemetryUI();
const streamStatus = document.querySelector("#stream-status");
const stageElement = document.querySelector("#universe-stage");

let currentView = null;
let tokenUI = null;
let activityUI = null;
let analystUI = null;

function setStreamStatus(mode, label) {
  streamStatus.className = `stream-status ${mode}`;
  streamStatus.querySelector("span").textContent = label;
}

function selectToken(mint) {
  if (!state.select(mint)) return false;
  currentView.setSelectedMint(mint);
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

function applySnapshot(snapshot) {
  const selectedBefore = state.selectedMint;
  const tokens = Array.isArray(snapshot?.tokens) ? snapshot.tokens : [];
  const timestamp = Date.parse(snapshot?.generated_at);

  activity.reset();
  state.load(tokens);
  currentView.load(tokens);
  currentView.setSelectedMint(state.selectedMint);
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

  currentView.applyEvents(events);
  tokenUI.renderSelected();
  tokenUI.refreshSearch();
  analystUI.populationChanged();
  renderDerivedState(Number.isFinite(timestamp) ? timestamp : Date.now());
}

async function bootstrap() {
  currentView = new SimpleTokenView(stageElement, { onSelect: selectToken });
  await currentView.init();

  tokenUI = new TokenUI({ state, onSelect: selectToken });
  activityUI = new ActivityUI({ state, onSelect: selectToken });
  analystUI = new AnalystUI({ state, requestAnalyst, onSelect: selectToken });

  const payload = await fetchUniverse();
  state.load(payload.tokens);
  currentView.load(payload.tokens);
  tokenUI.enableSearch();
  tokenUI.renderSelected();
  analystUI.sync(false);
  renderDerivedState();

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
}

setInterval(() => {
  if (tokenUI && activityUI) renderDerivedState();
  telemetryUI.render();
}, 1000);

setInterval(async () => {
  const mint = state.selectedMint;
  if (!mint || !tokenUI) return;
  try {
    const token = await fetchToken(mint);
    if (state.selectedMint !== mint) return;
    tokenUI.renderDetail(token);
  } catch (error) {
    console.warn("Token detail refresh failed", error);
  }
}, 5000);

bootstrap().catch(error => {
  console.error(error);
  setStreamStatus("error", "Offline");
  telemetryUI.setConnection("Offline");
});
