import { ObservatoryState, normalizedLaunchpad } from "./state.js";
import { TokenUniverse } from "./universe.js";

const stageElement = document.querySelector("#universe-stage");
const activeCount = document.querySelector("#active-count");
const launchpadCount = document.querySelector("#launchpad-count");
const changedCount = document.querySelector("#changed-count");
const streamStatus = document.querySelector("#stream-status");
const eventFeed = document.querySelector("#event-feed");
const feedRate = document.querySelector("#feed-rate");
const emptyDetail = document.querySelector("#empty-detail");
const tokenDetail = document.querySelector("#token-detail");
const analystForm = document.querySelector("#analyst-form");
const analystQuestion = document.querySelector("#analyst-question");
const analystSubmit = document.querySelector("#analyst-submit");
const analystContext = document.querySelector("#analyst-context");
const analystStatus = document.querySelector("#analyst-status");
const analystResult = document.querySelector("#analyst-result");
const analystAnswer = document.querySelector("#analyst-answer");
const analystSources = document.querySelector("#analyst-sources");

const state = new ObservatoryState();
const numberCompact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const integerFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function money(value) {
  return value == null ? "—" : `$${numberCompact.format(value)}`;
}

function count(value) {
  return value == null ? "—" : integerFormat.format(value);
}

function duration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(seconds < 18000 ? 1 : 0)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

function updateStats() {
  const stats = state.stats();
  activeCount.textContent = integerFormat.format(stats.active);
  launchpadCount.textContent = integerFormat.format(stats.launchpads);
  changedCount.textContent = integerFormat.format(stats.changed);
  feedRate.textContent = `${stats.events} event${stats.events === 1 ? "" : "s"}`;
}

function renderDetail(token) {
  if (!token) return;

  emptyDetail.classList.add("hidden");
  tokenDetail.classList.remove("hidden");
  document.querySelector("#detail-launchpad").textContent = normalizedLaunchpad(token);
  document.querySelector("#detail-name").textContent = token.name || token.symbol || "Unnamed token";
  document.querySelector("#detail-symbol").textContent = token.symbol || "—";

  const stateBadge = document.querySelector("#detail-state");
  stateBadge.textContent = token.tracking_enabled ? "ACTIVE" : "RETIRED";
  stateBadge.className = `state-badge ${token.tracking_enabled ? "active" : "retired"}`;

  document.querySelector("#detail-mcap").textContent = money(token.market_cap);
  document.querySelector("#detail-liquidity").textContent = money(token.liquidity);
  document.querySelector("#detail-holders").textContent = count(token.holders);
  document.querySelector("#detail-traders").textContent = count(token.traders_5m);
  document.querySelector("#detail-trades").textContent = count(token.trades_5m);
  document.querySelector("#detail-volume").textContent = money(token.volume_5m);
  document.querySelector("#detail-poll").textContent = `${duration(token.poll_age_seconds)} ago`;
  document.querySelector("#detail-change").textContent = `${duration(token.change_age_seconds)} ago`;
  document.querySelector("#detail-age").textContent = duration(token.age_seconds);
  document.querySelector("#detail-mint").textContent = token.mint;
}

function resetResearch(token) {
  analystQuestion.disabled = !token;
  analystSubmit.disabled = !token;
  analystContext.textContent = token
    ? `Researching ${token.symbol || token.name || token.mint.slice(0, 8)} · exact mint`
    : "Select a token first";
  analystStatus.textContent = "";
  analystResult.classList.add("hidden");
  analystAnswer.textContent = "";
  analystSources.replaceChildren();
}

function renderResearch(payload) {
  analystAnswer.textContent = payload.answer;
  analystSources.replaceChildren();

  if (payload.sources.length) {
    const heading = document.createElement("strong");
    heading.textContent = "Sources";
    analystSources.append(heading);
    for (const source of payload.sources) {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = source.title || source.url;
      analystSources.append(link);
    }
  } else {
    analystSources.textContent = "No cited web sources returned.";
  }

  analystStatus.textContent = payload.search_mode === "web_search_premium"
    ? "Premium web search completed"
    : "Web search completed";
  analystResult.classList.remove("hidden");
}

function eventSummary(event) {
  const token = event.token;
  if (event.type === "token_added") {
    return `entered ${normalizedLaunchpad(token)} · ${money(token.market_cap)}`;
  }
  if (event.type === "token_retired") {
    return event.reason || token.disabled_reason || "tracking disabled";
  }

  const percent = event.changes?.market_cap?.percent;
  if (percent != null && Math.abs(percent) >= 0.1) {
    return `market cap ${percent > 0 ? "+" : ""}${percent.toFixed(1)}% · ${money(token.market_cap)}`;
  }
  return `state changed · ${duration(token.change_age_seconds)} since update`;
}

function pushFeed(event) {
  const item = document.createElement("li");
  item.className = "event-item";
  const type = event.type.replace("token_", "");

  item.innerHTML = `
    <span class="event-type ${type}">${type.toUpperCase()}</span>
    <span class="event-copy"><strong></strong><span></span></span>
  `;
  item.querySelector("strong").textContent =
    event.token.symbol || event.token.name || event.token.mint.slice(0, 8);
  item.querySelector(".event-copy span").textContent = eventSummary(event);
  eventFeed.prepend(item);

  while (eventFeed.children.length > 36) {
    eventFeed.lastElementChild.remove();
  }
}

let universe = null;

function selectToken(mint) {
  state.select(mint);
  universe.setSelectedMint(mint);
  const token = state.token(mint);
  renderDetail(token);
  resetResearch(token);
}

function applyDelta(events) {
  for (const event of events) {
    state.applyEvent(event);
    pushFeed(event);
    if (state.selectedMint === event.token?.mint) renderDetail(state.selectedToken());
  }
  universe.applyEvents(events);
  updateStats();
}

async function bootstrap() {
  universe = new TokenUniverse(stageElement, { onSelect: selectToken });
  await universe.init();

  const response = await fetch("/api/universe");
  if (!response.ok) throw new Error(`Universe request failed: ${response.status}`);

  const payload = await response.json();
  state.load(payload.tokens);
  universe.load(payload.tokens);
  updateStats();

  const stream = new EventSource("/api/events");
  stream.addEventListener("open", () => {
    streamStatus.className = "stream-status live";
    streamStatus.querySelector("span").textContent = "Live";
  });
  stream.addEventListener("error", () => {
    streamStatus.className = "stream-status error";
    streamStatus.querySelector("span").textContent = "Reconnecting";
  });
  stream.addEventListener("universe_delta", message => {
    const delta = JSON.parse(message.data);
    applyDelta(delta.events);
  });
}

analystForm.addEventListener("submit", async event => {
  event.preventDefault();
  const question = analystQuestion.value.trim();
  if (!state.selectedMint || !question) return;

  analystSubmit.disabled = true;
  analystSubmit.textContent = "Researching…";
  analystStatus.textContent = "Searching the web…";
  analystResult.classList.add("hidden");

  try {
    const response = await fetch("/api/analyst", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mint: state.selectedMint, question }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || `Research failed: ${response.status}`);
    renderResearch(payload);
  } catch (error) {
    analystStatus.textContent = error.message;
  } finally {
    analystSubmit.disabled = false;
    analystSubmit.textContent = "Research";
  }
});

setInterval(updateStats, 1000);

setInterval(async () => {
  if (!state.selectedMint) return;
  try {
    const response = await fetch(`/api/token/${encodeURIComponent(state.selectedMint)}`);
    if (!response.ok) return;
    const token = await response.json();
    state.upsert(token);
    renderDetail(token);
  } catch (error) {
    console.warn("Token detail refresh failed", error);
  }
}, 5000);

bootstrap().catch(error => {
  console.error(error);
  streamStatus.className = "stream-status error";
  streamStatus.querySelector("span").textContent = "Offline";
});
