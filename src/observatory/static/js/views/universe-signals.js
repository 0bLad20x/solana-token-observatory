const DATA_UPDATE_MS = 850;
const MARKET_SIGNAL_MS = 1450;
const VOLUME_SURGE_MS = 1500;
const DRAW_INTERVAL_MS = 1000 / 30;

export const SIGNAL_DEFAULTS = Object.freeze({
  showDataUpdates: true,
  marketMove: 0.03,
  strongMarketMove: 0.10,
  showVolumeIntensity: true,
  volumePercentile: 0.90,
});

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function percentile(sorted, fraction) {
  if (!sorted.length) return null;
  const position = clamp(fraction, 0, 1) * (sorted.length - 1);
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  const weight = position - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

export function ratioValue(numerator, denominator) {
  const top = Number(numerator);
  const bottom = Number(denominator);
  if (!Number.isFinite(top) || !Number.isFinite(bottom) || top < 0 || bottom <= 0) {
    return null;
  }
  return top / bottom;
}

export function buildPopulationRatioScale(
  tokens,
  numeratorField,
  denominatorField,
  thresholdPercentile,
  highPercentile = 0.995,
) {
  const values = tokens
    .map(token => ratioValue(token?.[numeratorField], token?.[denominatorField]))
    .filter(value => value != null && value > 0)
    .sort((left, right) => left - right);

  if (!values.length) {
    return {
      count: 0,
      threshold: null,
      high: null,
      score: () => null,
    };
  }

  const threshold = percentile(values, thresholdPercentile);
  const high = Math.max(threshold, percentile(values, highPercentile));
  const lowLog = Math.log10(threshold);
  const highLog = high > threshold ? Math.log10(high) : lowLog;

  return {
    count: values.length,
    threshold,
    high,
    score(value) {
      if (!Number.isFinite(value) || value < threshold || value <= 0) return null;
      if (highLog <= lowLog) return 1;
      return clamp((Math.log10(value) - lowLog) / (highLog - lowLog), 0, 1);
    },
  };
}

export function marketMoveFromEvent(event) {
  if (event?.type !== "token_updated") return null;
  const percent = Number(event?.changes?.market_cap?.percent);
  return Number.isFinite(percent) ? percent / 100 : null;
}

export function marketSignalLevel(change, settings = SIGNAL_DEFAULTS) {
  if (!Number.isFinite(change)) return "none";
  const magnitude = Math.abs(change);
  if (magnitude < settings.marketMove) return "none";
  return magnitude >= settings.strongMarketMove ? "strong" : "move";
}

export function volumeIntensityChange(event) {
  if (event?.type !== "token_updated" || !event.token) return null;
  const afterVolume = Number(event.token.volume_5m);
  const afterMarketCap = Number(event.token.market_cap);
  const volumeDelta = Number(event?.changes?.volume_5m?.absolute);
  const marketDelta = Number(event?.changes?.market_cap?.absolute);
  if (![afterVolume, afterMarketCap, volumeDelta, marketDelta].every(Number.isFinite)) {
    return null;
  }

  const after = ratioValue(afterVolume, afterMarketCap);
  const before = ratioValue(afterVolume - volumeDelta, afterMarketCap - marketDelta);
  if (after == null || before == null) return null;
  return after - before;
}

function formatRatio(value) {
  if (!Number.isFinite(value)) return "—";
  const percent = value * 100;
  if (percent >= 100) return `${percent.toFixed(0)}%`;
  if (percent >= 10) return `${percent.toFixed(1)}%`;
  if (percent >= 1) return `${percent.toFixed(2)}%`;
  if (percent >= 0.1) return `${percent.toFixed(2)}%`;
  return `${percent.toFixed(3)}%`;
}

function easeOut(value) {
  const t = clamp(value, 0, 1);
  return 1 - (1 - t) ** 3;
}

class UniverseSignalLayer {
  constructor(view) {
    this.view = view;
    this.canvas = null;
    this.context = null;
    this.toggle = null;
    this.panel = null;
    this.controlRefs = new Map();
    this.resizeObserver = null;
    this.frame = null;
    this.lastDrawAt = 0;
    this.settings = { ...SIGNAL_DEFAULTS };
    this.tokens = new Map();
    this.effects = new Map();
    this.volumeScale = buildPopulationRatioScale([], "volume_5m", "market_cap", 0.90);
  }

  init() {
    if (!this.view.root || !this.view.canvas) return;

    this.canvas = document.createElement("canvas");
    this.canvas.className = "token-universe-signal-canvas";
    Object.assign(this.canvas.style, {
      position: "absolute",
      inset: "0",
      width: "100%",
      height: "100%",
      zIndex: "2",
      pointerEvents: "none",
    });
    this.context = this.canvas.getContext("2d");
    this.view.root.append(this.canvas);

    this.#buildControls();
    this.#extendLegend();

    this.resizeObserver = new ResizeObserver(() => this.#resizeCanvas());
    this.resizeObserver.observe(this.view.root);
    this.#resizeCanvas();
    this.#scheduleFrame();
  }

  render({ tokens = [], events = [] } = {}) {
    this.tokens = new Map(tokens.map(token => [token.mint, token]));
    this.volumeScale = buildPopulationRatioScale(
      tokens,
      "volume_5m",
      "market_cap",
      this.settings.volumePercentile,
    );

    const now = performance.now();
    for (const event of events) {
      const mint = event?.token?.mint;
      if (!mint) continue;
      if (event.type === "token_retired") {
        this.effects.delete(mint);
        continue;
      }
      if (event.type !== "token_updated") continue;

      const effect = this.effects.get(mint) || {};
      effect.dataStart = now;
      effect.dataUntil = now + DATA_UPDATE_MS;

      const marketChange = marketMoveFromEvent(event);
      const marketLevel = marketSignalLevel(marketChange, this.settings);
      if (marketLevel !== "none") {
        effect.marketStart = now;
        effect.marketUntil = now + MARKET_SIGNAL_MS;
        effect.marketChange = marketChange;
      }

      const volumeChange = volumeIntensityChange(event);
      if (volumeChange != null && volumeChange > 0) {
        const intensity = ratioValue(event.token.volume_5m, event.token.market_cap);
        const score = this.volumeScale.score(intensity);
        if (score != null) {
          effect.volumeStart = now;
          effect.volumeUntil = now + VOLUME_SURGE_MS;
          effect.volumeChange = volumeChange;
        }
      }

      this.effects.set(mint, effect);
    }
    this.#scheduleFrame();
  }

  destroy() {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.resizeObserver?.disconnect();
    this.toggle?.remove();
    this.panel?.remove();
    this.canvas?.remove();
    this.effects.clear();
  }

  #buildControls() {
    const controls = this.view.root.querySelector(".token-universe-controls");
    if (!controls) return;

    this.toggle = document.createElement("button");
    this.toggle.type = "button";
    this.toggle.className = "token-universe-physics-toggle";
    this.toggle.textContent = "Signals";
    this.toggle.setAttribute("aria-expanded", "false");

    this.panel = document.createElement("div");
    this.panel.className = "token-universe-physics-panel token-universe-signals-panel";
    this.panel.hidden = true;

    const heading = document.createElement("div");
    heading.className = "token-universe-physics-heading";
    const title = document.createElement("span");
    title.textContent = "Live signals";
    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "token-universe-physics-reset";
    restore.textContent = "Reset";
    restore.addEventListener("click", () => this.#resetSettings());
    heading.append(title, restore);
    this.panel.append(heading);

    this.#addToggleRow("showDataUpdates", "Data updates");
    this.#addRangeRow({
      key: "marketMove",
      label: "Market move",
      min: 0.005,
      max: 0.20,
      step: 0.005,
      format: value => `${(value * 100).toFixed(1)}%`,
    });
    this.#addRangeRow({
      key: "strongMarketMove",
      label: "Strong move",
      min: 0.01,
      max: 0.50,
      step: 0.01,
      format: value => `${(value * 100).toFixed(0)}%`,
    });
    this.#addToggleRow("showVolumeIntensity", "Volume / MC");
    this.#addRangeRow({
      key: "volumePercentile",
      label: "Volume top",
      min: 0.50,
      max: 0.99,
      step: 0.01,
      format: value => `top ${Math.max(1, Math.round((1 - value) * 100))}%`,
    });

    const note = document.createElement("div");
    note.className = "token-universe-physics-note";
    note.textContent = "Volume intensity = rolling 5m volume / market cap · threshold is relative to the live population · session-only";
    this.panel.append(note);

    this.toggle.addEventListener("click", () => {
      const open = this.panel.hidden;
      if (open && this.view.physicsPanel) {
        this.view.physicsPanel.hidden = true;
        this.view.physicsToggle?.classList.remove("active");
        this.view.physicsToggle?.setAttribute("aria-expanded", "false");
      }
      this.panel.hidden = !open;
      this.toggle.classList.toggle("active", open);
      this.toggle.setAttribute("aria-expanded", String(open));
    });

    this.view.physicsToggle?.addEventListener("click", () => {
      if (this.view.physicsPanel?.hidden === false) this.#closePanel();
    });

    if (this.view.physicsToggle) controls.insertBefore(this.toggle, this.view.physicsToggle);
    else controls.append(this.toggle);
    this.view.root.append(this.panel);
  }

  #addToggleRow(key, labelText) {
    const row = document.createElement("div");
    row.className = "token-universe-physics-row";
    row.style.gridTemplateColumns = "1fr auto";

    const label = document.createElement("span");
    label.className = "token-universe-physics-label";
    label.textContent = labelText;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "token-universe-physics-step";
    button.style.minWidth = "44px";
    const sync = () => {
      button.textContent = this.settings[key] ? "ON" : "OFF";
      button.setAttribute("aria-pressed", String(Boolean(this.settings[key])));
    };
    button.addEventListener("click", () => {
      this.settings[key] = !this.settings[key];
      sync();
      this.#draw(performance.now());
    });
    sync();
    this.controlRefs.set(key, { type: "toggle", button, sync });
    row.append(label, button);
    this.panel.append(row);
  }

  #addRangeRow(spec) {
    const row = document.createElement("div");
    row.className = "token-universe-physics-row";

    const label = document.createElement("label");
    label.className = "token-universe-physics-label";
    label.textContent = spec.label;

    const minus = document.createElement("button");
    minus.type = "button";
    minus.className = "token-universe-physics-step";
    minus.textContent = "−";

    const input = document.createElement("input");
    input.type = "range";
    input.className = "token-universe-physics-range";
    input.min = String(spec.min);
    input.max = String(spec.max);
    input.step = String(spec.step);
    input.value = String(this.settings[spec.key]);
    input.setAttribute("aria-label", spec.label);

    const plus = document.createElement("button");
    plus.type = "button";
    plus.className = "token-universe-physics-step";
    plus.textContent = "+";

    const value = document.createElement("output");
    value.className = "token-universe-physics-value";

    const apply = next => this.#setRange(spec, next);
    input.addEventListener("input", () => apply(Number(input.value)));
    minus.addEventListener("click", () => apply(this.settings[spec.key] - spec.step));
    plus.addEventListener("click", () => apply(this.settings[spec.key] + spec.step));

    this.controlRefs.set(spec.key, { type: "range", input, value, spec });
    row.append(label, minus, input, plus, value);
    this.panel.append(row);
    this.#syncRange(spec.key);
  }

  #setRange(spec, rawValue) {
    if (!Number.isFinite(rawValue)) return;
    const stepped = Math.round(rawValue / spec.step) * spec.step;
    this.settings[spec.key] = Number(clamp(stepped, spec.min, spec.max).toFixed(6));

    if (spec.key === "marketMove" && this.settings.marketMove > this.settings.strongMarketMove) {
      this.settings.strongMarketMove = this.settings.marketMove;
      this.#syncRange("strongMarketMove");
    }
    if (spec.key === "strongMarketMove" && this.settings.strongMarketMove < this.settings.marketMove) {
      this.settings.strongMarketMove = this.settings.marketMove;
    }

    if (spec.key === "volumePercentile") {
      this.volumeScale = buildPopulationRatioScale(
        [...this.tokens.values()],
        "volume_5m",
        "market_cap",
        this.settings.volumePercentile,
      );
    }
    this.#syncRange(spec.key);
    this.#draw(performance.now());
  }

  #syncRange(key) {
    const ref = this.controlRefs.get(key);
    if (!ref || ref.type !== "range") return;
    ref.input.value = String(this.settings[key]);
    ref.value.textContent = ref.spec.format(this.settings[key]);
  }

  #resetSettings() {
    Object.assign(this.settings, SIGNAL_DEFAULTS);
    for (const [key, ref] of this.controlRefs) {
      if (ref.type === "toggle") ref.sync();
      else this.#syncRange(key);
    }
    this.volumeScale = buildPopulationRatioScale(
      [...this.tokens.values()],
      "volume_5m",
      "market_cap",
      this.settings.volumePercentile,
    );
    this.#draw(performance.now());
  }

  #closePanel() {
    if (!this.panel || !this.toggle) return;
    this.panel.hidden = true;
    this.toggle.classList.remove("active");
    this.toggle.setAttribute("aria-expanded", "false");
  }

  #extendLegend() {
    const legend = this.view.root.querySelector(".token-universe-legend");
    if (!legend || legend.querySelector("[data-live-signals]")) return;
    const update = document.createElement("span");
    update.dataset.liveSignals = "update";
    update.textContent = "Pulse = new source state";
    const volume = document.createElement("span");
    volume.dataset.liveSignals = "volume";
    volume.textContent = "Outer ring = high 5m volume / MC";
    legend.append(update, volume);
  }

  #resizeCanvas() {
    if (!this.canvas || !this.context || !this.view.canvas) return;
    const rect = this.view.canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (this.canvas.width === width && this.canvas.height === height) return;
    this.canvas.width = width;
    this.canvas.height = height;
    this.canvas.dataset.dpr = String(dpr);
  }

  #scheduleFrame() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(timestamp => this.#loop(timestamp));
  }

  #loop(timestamp) {
    this.frame = null;
    if (timestamp - this.lastDrawAt >= DRAW_INTERVAL_MS) {
      this.lastDrawAt = timestamp;
      this.#draw(timestamp);
    }
    this.#scheduleFrame();
  }

  #draw(timestamp) {
    if (!this.canvas || !this.context || !this.view.canvas) return;
    this.#resizeCanvas();

    const context = this.context;
    const dpr = Number(this.canvas.dataset.dpr || 1);
    const width = this.canvas.width / dpr;
    const height = this.canvas.height / dpr;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);

    if (!width || !height || !this.view.root?.offsetParent) return;

    context.save();
    context.translate(this.view.viewport.x, this.view.viewport.y);
    context.scale(this.view.viewport.k, this.view.viewport.k);

    for (const node of this.view.nodes.values()) {
      if (!this.view.enabledLaunchpads.has(node.launchpad)) continue;
      const token = this.tokens.get(node.mint) || node.token;
      if (!token) continue;
      const radius = Math.max(1, node.radius || node.targetRadius || 1);
      const effect = this.effects.get(node.mint);

      if (this.settings.showVolumeIntensity) {
        this.#drawVolumeIntensity(context, node, token, radius, effect, timestamp);
      }

      const marketActive = effect?.marketUntil > timestamp
        && marketSignalLevel(effect.marketChange, this.settings) !== "none";
      if (marketActive) {
        this.#drawMarketSignal(context, node, radius, effect, timestamp);
      } else if (this.settings.showDataUpdates && effect?.dataUntil > timestamp) {
        this.#drawDataPulse(context, node, radius, effect, timestamp);
      }

      if (node.mint === this.view.selectedMint || node.mint === this.view.hoverMint) {
        this.#drawFocusMetrics(context, node, token, radius);
      }
    }

    context.restore();
    this.#pruneEffects(timestamp);
  }

  #drawDataPulse(context, node, radius, effect, timestamp) {
    const progress = clamp((timestamp - effect.dataStart) / DATA_UPDATE_MS, 0, 1);
    const eased = easeOut(progress);
    const alpha = (1 - progress) * 0.42;
    context.beginPath();
    context.arc(node.x, node.y, radius + 2 + eased * 12, 0, Math.PI * 2);
    context.strokeStyle = `rgba(146,155,173,${alpha})`;
    context.lineWidth = 1.2 / this.view.viewport.k;
    context.stroke();
  }

  #drawMarketSignal(context, node, radius, effect, timestamp) {
    const progress = clamp((timestamp - effect.marketStart) / MARKET_SIGNAL_MS, 0, 1);
    const fade = Math.sin(Math.PI * progress);
    const level = marketSignalLevel(effect.marketChange, this.settings);
    const strong = level === "strong";
    const direction = Math.sign(effect.marketChange || 0);
    if (!direction) return;
    const rgb = direction > 0 ? "61,220,151" : "255,92,119";
    const distance = 5 + easeOut(progress) * (strong ? 20 : 12);

    context.beginPath();
    context.arc(node.x, node.y, radius + distance, 0, Math.PI * 2);
    context.strokeStyle = `rgba(${rgb},${(strong ? 0.78 : 0.48) * fade})`;
    context.lineWidth = (strong ? 2.5 : 1.5) / this.view.viewport.k;
    context.stroke();

    if (strong && this.view.viewport.k >= 0.72) {
      const percent = Math.abs(effect.marketChange * 100);
      context.fillStyle = `rgba(${rgb},${0.9 * fade})`;
      context.font = `700 ${Math.max(8, 10 / this.view.viewport.k)}px Inter, system-ui, sans-serif`;
      context.textAlign = "center";
      context.textBaseline = "bottom";
      context.fillText(
        `${direction > 0 ? "▲" : "▼"} ${percent >= 100 ? percent.toFixed(0) : percent.toFixed(1)}% MC`,
        node.x,
        node.y - radius - 9 / this.view.viewport.k,
      );
    }
  }

  #drawVolumeIntensity(context, node, token, radius, effect, timestamp) {
    const intensity = ratioValue(token.volume_5m, token.market_cap);
    const score = this.volumeScale.score(intensity);
    if (score == null) return;

    const surgeActive = effect?.volumeUntil > timestamp;
    const progress = surgeActive
      ? clamp((timestamp - effect.volumeStart) / VOLUME_SURGE_MS, 0, 1)
      : 1;
    const pulse = surgeActive ? Math.sin(Math.PI * progress) : 0;
    const ringRadius = radius + 5 + score * 6 + pulse * 6;
    const alpha = 0.16 + score * 0.34 + pulse * 0.24;

    context.beginPath();
    context.arc(node.x, node.y, ringRadius, 0, Math.PI * 2);
    context.setLineDash([3 / this.view.viewport.k, 3 / this.view.viewport.k]);
    context.strokeStyle = `rgba(183,124,255,${Math.min(0.82, alpha)})`;
    context.lineWidth = (0.9 + score * 1.5 + pulse * 0.7) / this.view.viewport.k;
    context.stroke();
    context.setLineDash([]);
  }

  #drawFocusMetrics(context, node, token, radius) {
    if (this.view.viewport.k < 0.72) return;
    const volumeRatio = ratioValue(token.volume_5m, token.market_cap);
    const x = node.x + radius + 8 / this.view.viewport.k;
    const y = node.y + 1 / this.view.viewport.k;
    context.fillStyle = "rgba(183,124,255,.9)";
    context.font = `650 ${Math.max(8, 9 / this.view.viewport.k)}px Inter, system-ui, sans-serif`;
    context.textAlign = "left";
    context.textBaseline = "middle";
    context.fillText(`VOL/MC ${formatRatio(volumeRatio)}`, x, y);
  }

  #pruneEffects(timestamp) {
    for (const [mint, effect] of this.effects) {
      const latest = Math.max(
        effect.dataUntil || 0,
        effect.marketUntil || 0,
        effect.volumeUntil || 0,
      );
      if (latest <= timestamp) this.effects.delete(mint);
    }
  }
}

const INSTALL_FLAG = Symbol.for("solana-token-observatory.universe-live-signals");

export function installUniverseSignals(TokenUniverseView) {
  const prototype = TokenUniverseView?.prototype;
  if (!prototype || prototype[INSTALL_FLAG]) return;
  Object.defineProperty(prototype, INSTALL_FLAG, { value: true });

  const baseInit = prototype.init;
  const baseRender = prototype.render;
  const baseDestroy = prototype.destroy;

  prototype.init = function initWithSignals(...args) {
    const result = baseInit.apply(this, args);
    this.universeSignalLayer = new UniverseSignalLayer(this);
    this.universeSignalLayer.init();
    return result;
  };

  prototype.render = function renderWithSignals(payload = {}) {
    const events = Array.isArray(payload.events) ? payload.events : [];
    const baseEvents = events.filter(event => event?.type !== "token_updated");
    const result = baseRender.call(this, { ...payload, events: baseEvents });
    this.universeSignalLayer?.render({ ...payload, events });
    return result;
  };

  prototype.destroy = function destroyWithSignals(...args) {
    this.universeSignalLayer?.destroy();
    this.universeSignalLayer = null;
    return baseDestroy.apply(this, args);
  };
}
