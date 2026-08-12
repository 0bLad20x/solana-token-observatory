import { ActivityTracker } from "./activity.js";
import { ActivityUI } from "./activity-ui.js";
import { connectUniverseStream, fetchToken, fetchUniverse, requestAnalyst } from "./api.js";
import { AnalystUI } from "./analyst-ui.js";
import { ObservatoryState } from "./state.js";
import { TokenUI } from "./token-ui.js";
import { SimpleTokenView } from "./views/simple-token-view.js";

const state = new ObservatoryState();
const activity = new ActivityTracker();
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
    onDelta: delta => applyDelta(delta.events || [], delta.generated_at),
  });
}

setInterval(() => {
  if (tokenUI && activityUI) renderDerivedState();
}, 1000);

setInterval(async () => {
  if (!state.selectedMint || !tokenUI) return;
  try {
    const token = await fetchToken(state.selectedMint);
    state.upsert(token);
    tokenUI.renderSelected();
  } catch (error) {
    console.warn("Token detail refresh failed", error);
  }
}, 5000);

bootstrap().catch(error => {
  console.error(error);
  setStreamStatus("error", "Offline");
});
