import { integerFormat, tokenIdentity } from "./format.js";

const SCOPE_CONFIG = {
  current_data: {
    title: "Current token data",
    chip: "CURRENT DATA",
    submit: "Ask",
    pendingSubmit: "Querying…",
    pendingStatus: "Translating question into query_tokens…",
    placeholder: "Which five tokens have the highest market cap?",
    needsToken: false,
    contextVerb: "",
    evidenceLabel: "QUERY EVIDENCE",
  },
  web: {
    title: "Token web research",
    chip: "EXTERNAL EVIDENCE",
    submit: "Research",
    pendingSubmit: "Researching…",
    pendingStatus: "Searching the web…",
    placeholder: "What can be verified about this token?",
    needsToken: true,
    contextVerb: "Researching",
    evidenceLabel: "WEB SOURCES",
  },
  temporal: {
    title: "Temporal summary analysis",
    chip: "SUMMARY ANALYSIS",
    submit: "Analyze",
    pendingSubmit: "Analyzing…",
    pendingStatus: "Loading compact temporal summary…",
    placeholder: "Give an expert assessment of this token from its observed summary.",
    needsToken: true,
    contextVerb: "Analyzing",
    evidenceLabel: "TEMPORAL EVIDENCE",
  },
  rugcheck: {
    title: "RugCheck safety evidence",
    chip: "RUGCHECK EVIDENCE",
    submit: "Check",
    pendingSubmit: "Checking…",
    pendingStatus: "Fetching exact-mint RugCheck report…",
    placeholder: "Assess the safety evidence for this token.",
    needsToken: true,
    contextVerb: "Checking",
    evidenceLabel: "RUGCHECK EVIDENCE",
  },
};

export class AnalystUI {
  constructor({ state, requestAnalyst, onSelect }) {
    this.state = state;
    this.requestAnalyst = requestAnalyst;
    this.onSelect = onSelect;
    this.scope = "current_data";
    this.lastAnswer = "";
    this.copyResetTimer = null;

    this.card = document.querySelector("#analyst-card");
    this.focusToggle = document.querySelector("#analyst-focus-toggle");
    this.form = document.querySelector("#analyst-form");
    this.question = document.querySelector("#analyst-question");
    this.submit = document.querySelector("#analyst-submit");
    this.context = document.querySelector("#analyst-context");
    this.contextMint = document.querySelector("#analyst-context-mint");
    this.status = document.querySelector("#analyst-status");
    this.result = document.querySelector("#analyst-result");
    this.resultQuestion = document.querySelector("#analyst-result-question");
    this.answer = document.querySelector("#analyst-answer");
    this.answerCopy = document.querySelector("#analyst-answer-copy");
    this.sources = document.querySelector("#analyst-sources");
    this.evidenceHeading = document.querySelector("#analyst-evidence-heading");
    this.title = document.querySelector("#analyst-title");
    this.chip = document.querySelector("#analyst-chip");
    this.modes = [...document.querySelectorAll("[data-analyst-scope]")];

    this.form.addEventListener("submit", event => this.#submit(event));
    this.focusToggle.addEventListener("click", () => {
      this.setFocused(!this.card.classList.contains("analyst-focused"));
    });
    this.answerCopy.addEventListener("click", () => this.copyAnswer());
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && this.card.classList.contains("analyst-focused")) {
        this.setFocused(false);
      }
    });

    for (const button of this.modes) {
      button.addEventListener("click", () => {
        this.scope = button.dataset.analystScope;
        this.sync(true);
      });
    }
  }

  setFocused(focused) {
    this.card.classList.toggle("analyst-focused", focused);
    document.body.classList.toggle("analyst-focus-active", focused);
    this.focusToggle.setAttribute("aria-pressed", String(focused));
    this.focusToggle.textContent = focused ? "Close" : "Focus";
  }

  sync(clearResult = false) {
    const token = this.state.selectedToken();
    const config = SCOPE_CONFIG[this.scope];

    this.title.textContent = config.title;
    this.chip.textContent = config.chip;
    this.chip.classList.toggle("current", this.scope === "current_data");
    this.evidenceHeading.textContent = config.evidenceLabel;

    for (const button of this.modes) {
      button.classList.toggle("active", button.dataset.analystScope === this.scope);
    }

    this.question.disabled = config.needsToken && !token;
    this.submit.disabled = config.needsToken && !token;
    this.submit.textContent = config.submit;
    this.question.placeholder = config.placeholder;

    if (config.needsToken) {
      this.context.textContent = token
        ? `${tokenIdentity(token)} · exact mint`
        : "Select a token first";
      this.contextMint.textContent = token?.mint || "";
      this.contextMint.classList.toggle("hidden", !token?.mint);
    } else {
      this.context.textContent = `${integerFormat.format(this.state.stats().active)} active tokens`;
      this.contextMint.textContent = "";
      this.contextMint.classList.add("hidden");
    }

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
    this.resultQuestion.textContent = "";
    this.answer.replaceChildren();
    this.sources.replaceChildren();
    this.lastAnswer = "";
    this.resetCopyButton();
  }

  async copyAnswer() {
    if (!this.lastAnswer) return;

    try {
      await navigator.clipboard.writeText(this.lastAnswer);
      this.answerCopy.textContent = "Copied";
    } catch (error) {
      console.warn("Analyst answer copy failed", error);
      this.answerCopy.textContent = "Copy failed";
    }

    clearTimeout(this.copyResetTimer);
    this.copyResetTimer = setTimeout(() => this.resetCopyButton(), 1400);
  }

  resetCopyButton() {
    clearTimeout(this.copyResetTimer);
    this.copyResetTimer = null;
    this.answerCopy.textContent = "Copy answer";
  }

  async #submit(event) {
    event.preventDefault();
    const question = this.question.value.trim();
    const requestScope = this.scope;
    const config = SCOPE_CONFIG[requestScope];
    const mint = this.state.selectedMint;
    if (!question || (config.needsToken && !mint)) return;

    this.setFocused(true);
    this.submit.disabled = true;
    this.submit.textContent = config.pendingSubmit;
    this.status.textContent = config.pendingStatus;
    this.result.classList.add("hidden");

    try {
      const body = { scope: requestScope, question };
      if (config.needsToken) body.mint = mint;
      const payload = await this.requestAnalyst(body);
      if (this.scope === requestScope) this.#render(payload, question);
    } catch (error) {
      this.status.textContent = error.message;
    } finally {
      this.sync(false);
    }
  }

  #render(payload, question) {
    this.lastAnswer = payload.answer || "";
    this.resultQuestion.textContent = question;
    this.#renderAnswer(this.lastAnswer);
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
    } else if (payload.scope === "rugcheck") {
      this.#renderRugCheckEvidence(payload.evidence);
      this.status.textContent = "RugCheck evidence analysis completed";
    } else if (Array.isArray(payload.sources) && payload.sources.length) {
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

  #renderAnswer(text) {
    this.answer.replaceChildren();
    let list = null;
    let listType = "";

    for (const rawLine of String(text || "").split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line) {
        list = null;
        listType = "";
        continue;
      }

      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        const element = document.createElement(heading[1].length === 1 ? "h3" : "h4");
        element.textContent = heading[2];
        this.answer.append(element);
        list = null;
        listType = "";
        continue;
      }

      const unordered = line.match(/^[-*]\s+(.+)$/);
      const ordered = line.match(/^\d+[.)]\s+(.+)$/);
      if (unordered || ordered) {
        const nextType = unordered ? "ul" : "ol";
        if (!list || listType !== nextType) {
          list = document.createElement(nextType);
          listType = nextType;
          this.answer.append(list);
        }
        const item = document.createElement("li");
        item.textContent = (unordered || ordered)[1];
        list.append(item);
        continue;
      }

      const strongLine = line.match(/^\*\*(.+)\*\*$/);
      if (strongLine) {
        const element = document.createElement("h4");
        element.textContent = strongLine[1];
        this.answer.append(element);
        list = null;
        listType = "";
        continue;
      }

      const paragraph = document.createElement("p");
      paragraph.textContent = line;
      this.answer.append(paragraph);
      list = null;
      listType = "";
    }
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

  #renderRugCheckEvidence(evidence) {
    const trace = document.createElement("strong");
    trace.textContent = `rugcheck_token_report · ${evidence.mode} · ~${integerFormat.format(evidence.analysis_rough_tokens)} analysis tokens`;
    const size = document.createElement("span");
    size.textContent = `raw ${integerFormat.format(evidence.raw_report_bytes)} bytes → metadata ${integerFormat.format(evidence.analysis_context_bytes)} bytes · source RugCheck`;
    const coverage = document.createElement("span");
    const markets = evidence.markets_observed == null
      ? "markets unavailable"
      : `${integerFormat.format(evidence.markets_observed)} markets aggregated`;
    const holders = evidence.top_holders_observed == null
      ? "top holders unavailable"
      : `${integerFormat.format(evidence.top_holders_observed)} top holders aggregated`;
    coverage.textContent = `${markets} · ${holders} · ${integerFormat.format(evidence.wallet_addresses_sent_to_llm || 0)} wallet addresses sent`;
    const fetched = document.createElement("span");
    fetched.textContent = `Fetched ${evidence.fetched_at}`;
    this.sources.append(trace, size, coverage, fetched);
  }
}
