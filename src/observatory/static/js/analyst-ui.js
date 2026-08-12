import { integerFormat, tokenIdentity } from "./format.js";

export class AnalystUI {
  constructor({ state, requestAnalyst, onSelect }) {
    this.state = state;
    this.requestAnalyst = requestAnalyst;
    this.onSelect = onSelect;
    this.scope = "current_data";

    this.form = document.querySelector("#analyst-form");
    this.question = document.querySelector("#analyst-question");
    this.submit = document.querySelector("#analyst-submit");
    this.context = document.querySelector("#analyst-context");
    this.status = document.querySelector("#analyst-status");
    this.result = document.querySelector("#analyst-result");
    this.answer = document.querySelector("#analyst-answer");
    this.sources = document.querySelector("#analyst-sources");
    this.title = document.querySelector("#analyst-title");
    this.chip = document.querySelector("#analyst-chip");
    this.modes = [...document.querySelectorAll("[data-analyst-scope]")];

    this.form.addEventListener("submit", event => this.#submit(event));
    for (const button of this.modes) {
      button.addEventListener("click", () => {
        this.scope = button.dataset.analystScope;
        this.sync(true);
      });
    }
  }

  sync(clearResult = false) {
    const token = this.state.selectedToken();
    const isWeb = this.scope === "web";
    const isTemporal = this.scope === "temporal";
    const needsToken = isWeb || isTemporal;

    this.title.textContent = isWeb
      ? "Token web research"
      : isTemporal
        ? "Temporal summary analysis"
        : "Current token data";
    this.chip.textContent = isWeb
      ? "EXTERNAL EVIDENCE"
      : isTemporal
        ? "SUMMARY ANALYSIS"
        : "CURRENT DATA";
    this.chip.classList.toggle("current", this.scope === "current_data");

    for (const button of this.modes) {
      button.classList.toggle("active", button.dataset.analystScope === this.scope);
    }

    this.question.disabled = needsToken && !token;
    this.submit.disabled = needsToken && !token;
    this.submit.textContent = isWeb ? "Research" : isTemporal ? "Analyze" : "Ask";
    this.question.placeholder = isWeb
      ? "What can be verified about this token?"
      : isTemporal
        ? "Give an expert assessment of this token from its observed summary."
        : "Which five tokens have the highest market cap?";
    this.context.textContent = needsToken
      ? token
        ? `${isWeb ? "Researching" : "Analyzing"} ${tokenIdentity(token)} · exact mint`
        : "Select a token first"
      : `Ask about ${integerFormat.format(this.state.stats().active)} active tokens`;

    if (clearResult) this.clear();
  }

  selectionChanged() {
    this.sync(this.scope !== "current_data");
  }

  populationChanged() {
    if (this.scope === "current_data") this.sync(false);
  }

  clear() {
    this.status.textContent = "";
    this.result.classList.add("hidden");
    this.answer.textContent = "";
    this.sources.replaceChildren();
  }

  async #submit(event) {
    event.preventDefault();
    const question = this.question.value.trim();
    const requestScope = this.scope;
    const mint = this.state.selectedMint;
    const needsToken = requestScope === "web" || requestScope === "temporal";
    if (!question || (needsToken && !mint)) return;

    this.submit.disabled = true;
    this.submit.textContent = requestScope === "web"
      ? "Researching…"
      : requestScope === "temporal"
        ? "Analyzing…"
        : "Querying…";
    this.status.textContent = requestScope === "web"
      ? "Searching the web…"
      : requestScope === "temporal"
        ? "Loading compact temporal summary…"
        : "Translating question into query_tokens…";
    this.result.classList.add("hidden");

    try {
      const body = { scope: requestScope, question };
      if (needsToken) body.mint = mint;
      const payload = await this.requestAnalyst(body);
      if (this.scope === requestScope) this.#render(payload);
    } catch (error) {
      this.status.textContent = error.message;
    } finally {
      this.sync(false);
    }
  }

  #render(payload) {
    this.answer.textContent = payload.answer;
    this.sources.replaceChildren();

    if (payload.scope === "current_data") {
      if (payload.tool) {
        this.#renderTokens(payload.tool);
        this.status.textContent = "Current data query completed";
      } else {
        this.#renderCapabilities(payload.capabilities);
        this.status.textContent = "No unambiguous supported query was found";
      }
    } else if (payload.scope === "temporal") {
      this.#renderTemporalEvidence(payload.evidence);
      this.status.textContent = "Temporal summary analysis completed";
    } else if (payload.sources.length) {
      const heading = document.createElement("strong");
      heading.textContent = "Sources";
      this.sources.append(heading);
      for (const source of payload.sources) {
        const link = document.createElement("a");
        link.href = source.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = source.title || source.url;
        this.sources.append(link);
      }
      this.status.textContent = payload.search_mode === "web_search_premium"
        ? "Premium web search completed"
        : "Web search completed";
    } else {
      this.sources.textContent = "No cited web sources returned.";
      this.status.textContent = payload.search_mode === "web_search_premium"
        ? "Premium web search completed"
        : "Web search completed";
    }

    this.result.classList.remove("hidden");
  }

  #renderCapabilities(capabilities) {
    const heading = document.createElement("strong");
    heading.textContent = "Available current queries";
    this.sources.append(heading);

    const fields = document.createElement("span");
    fields.textContent = `Sort by: ${capabilities.fields.map(field => field.label).join(", ")}`;
    const orders = document.createElement("span");
    orders.textContent = "Order: highest / top or lowest / bottom";
    const launchpads = document.createElement("span");
    launchpads.textContent = `Launchpads: ${capabilities.launchpads.map(item => item.value).join(", ")}`;
    const limit = document.createElement("span");
    limit.textContent = `Results: default ${capabilities.default_limit}, maximum ${capabilities.maximum_limit}`;
    const example = document.createElement("span");
    const launchpad = capabilities.launchpads[0]?.value;
    example.textContent = launchpad
      ? `Example: Which five ${launchpad} tokens have the highest 5m volume?`
      : "Example: Which five tokens have the highest 5m volume?";
    this.sources.append(fields, orders, launchpads, limit, example);
  }

  #renderTokens(tool) {
    const trace = document.createElement("span");
    trace.textContent = `query_tokens · ${integerFormat.format(tool.matched_count)} matched · ${integerFormat.format(tool.returned_count)} returned`;
    this.sources.append(trace);
    if (!tool.tokens.length) return;

    const list = document.createElement("div");
    list.className = "analyst-token-list";
    for (const token of tool.tokens) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "analyst-token-choice";
      const identity = document.createElement("strong");
      identity.textContent = tokenIdentity(token);
      const mint = document.createElement("small");
      mint.textContent = token.mint;
      button.append(identity, mint);
      button.addEventListener("click", () => this.onSelect(token.mint));
      list.append(button);
    }
    this.sources.append(list);
  }

  #renderTemporalEvidence(evidence) {
    const trace = document.createElement("strong");
    trace.textContent = `temporal_summary · summary only · ~${integerFormat.format(evidence.rough_summary_tokens)} rough summary tokens`;
    const span = document.createElement("span");
    span.textContent = `${Number(evidence.history_hours).toFixed(2)}h evidence · ${integerFormat.format(evidence.observations)} observations`;
    const range = document.createElement("span");
    range.textContent = `${evidence.from} → ${evidence.to}`;
    this.sources.append(trace, span, range);
  }
}
