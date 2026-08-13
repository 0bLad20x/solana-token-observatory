import { count, money, timeFormat } from "../format.js";

const SVG_NS = "http://www.w3.org/2000/svg";

function percent(value) {
  return value == null || !Number.isFinite(value) ? "—" : `${value.toFixed(1)}%`;
}

function signedMoney(value) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value === 0) return money(0);
  return `${value > 0 ? "+" : "−"}${money(Math.abs(value))}`;
}

function coverageLabel(known, total) {
  if (!Number.isFinite(known) || !Number.isFinite(total) || total <= 0) return "no coverage";
  return `${count(known)} / ${count(total)} tokens`;
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

function numericSeries(history, accessor) {
  return history
    .map(point => ({ timestamp: point.timestamp, value: accessor(point) }))
    .filter(point => Number.isFinite(point.value));
}

function renderLineChart(svg, history, accessor, { minValue = null, maxValue = null } = {}) {
  svg.replaceChildren();
  const points = numericSeries(history, accessor);
  const width = 1000;
  const height = 260;
  const left = 66;
  const right = 22;
  const top = 20;
  const bottom = 34;
  const innerWidth = width - left - right;
  const innerHeight = height - top - bottom;

  const grid = svgElement("g", { class: "pulse-chart-grid" });
  for (let index = 0; index <= 4; index += 1) {
    const y = top + innerHeight * index / 4;
    grid.append(svgElement("line", { x1: left, x2: width - right, y1: y, y2: y }));
  }
  svg.append(grid);

  if (!points.length) return;
  const start = points[0].timestamp;
  const end = points.at(-1).timestamp;
  const values = points.map(point => point.value);
  let low = minValue ?? Math.min(...values);
  let high = maxValue ?? Math.max(...values);
  if (low === high) {
    const padding = Math.abs(low) * 0.05 || 1;
    low -= padding;
    high += padding;
  }

  const x = timestamp => left + (end === start ? innerWidth : (timestamp - start) / (end - start) * innerWidth);
  const y = value => top + (high - value) / (high - low) * innerHeight;
  const pathData = points
    .map((point, index) => `${index ? "L" : "M"}${x(point.timestamp).toFixed(2)},${y(point.value).toFixed(2)}`)
    .join(" ");

  svg.append(svgElement("path", { class: "pulse-chart-line", d: pathData }));
  const last = points.at(-1);
  svg.append(svgElement("circle", {
    class: "pulse-chart-dot",
    cx: x(last.timestamp),
    cy: y(last.value),
    r: 4,
  }));

  const labelTop = svgElement("text", { class: "pulse-axis-label", x: 8, y: top + 4 });
  labelTop.textContent = Number.isFinite(high) ? (Math.abs(high) >= 1000 ? money(high) : high.toFixed(1)) : "";
  svg.append(labelTop);
  const labelBottom = svgElement("text", { class: "pulse-axis-label", x: 8, y: top + innerHeight + 4 });
  labelBottom.textContent = Number.isFinite(low) ? (Math.abs(low) >= 1000 ? money(low) : low.toFixed(1)) : "";
  svg.append(labelBottom);

  const timeStart = svgElement("text", { class: "pulse-time-label", x: left, y: height - 8 });
  timeStart.textContent = timeFormat.format(new Date(start));
  svg.append(timeStart);
  const timeEnd = svgElement("text", {
    class: "pulse-time-label pulse-time-label-end",
    x: width - right,
    y: height - 8,
  });
  timeEnd.textContent = timeFormat.format(new Date(end));
  svg.append(timeEnd);
}

export class MarketPulseView {
  constructor(element) {
    this.element = element;
    this.ready = false;
  }

  init() {
    if (this.ready) return;
    this.element.innerHTML = `
      <div class="pulse-shell">
        <div class="pulse-chrome">
          <div>
            <span class="pulse-eyebrow">MARKET PULSE</span>
            <strong>Observed population activity</strong>
          </div>
          <span class="pulse-meta">1s samples · 6h RAM · rolling 5m source windows</span>
        </div>

        <div class="pulse-metrics">
          <article><span>ACTIVE</span><strong data-pulse="active">—</strong><small>tracked tokens</small></article>
          <article><span>VOLUME · 5M</span><strong data-pulse="volume">—</strong><small data-pulse="volume-coverage">no coverage</small></article>
          <article><span>BUY SHARE · 5M</span><strong data-pulse="buy-share">—</strong><small data-pulse="pressure-coverage">no coverage</small></article>
          <article><span>LIQUIDITY</span><strong data-pulse="liquidity">—</strong><small data-pulse="liquidity-median">median —</small></article>
          <article><span>BREADTH · 5M</span><strong data-pulse="breadth">—</strong><small>tokens with volume &gt; 0</small></article>
          <article><span>TOP 10 SHARE</span><strong data-pulse="concentration">—</strong><small>share of observed 5m volume</small></article>
        </div>

        <section class="pulse-chart-card pulse-chart-primary">
          <div class="pulse-chart-heading">
            <div><span>ROLLING 5M VOLUME</span><strong data-pulse="volume-current">—</strong></div>
            <small>Cross-section of the current active population. Samples are not accumulated.</small>
          </div>
          <svg data-pulse-chart="volume" viewBox="0 0 1000 260" preserveAspectRatio="none" aria-label="Observed rolling five minute volume over time"></svg>
        </section>

        <div class="pulse-chart-grid-cards">
          <section class="pulse-chart-card">
            <div class="pulse-chart-heading">
              <div><span>BUY PRESSURE · 5M</span><strong data-pulse="pressure-current">—</strong></div>
              <small data-pulse="pressure-detail">Buy / sell —</small>
            </div>
            <svg data-pulse-chart="pressure" viewBox="0 0 1000 260" preserveAspectRatio="none" aria-label="Buy share over time"></svg>
          </section>
          <section class="pulse-chart-card">
            <div class="pulse-chart-heading">
              <div><span>TOTAL LIQUIDITY</span><strong data-pulse="liquidity-current">—</strong></div>
              <small data-pulse="liquidity-coverage">no coverage</small>
            </div>
            <svg data-pulse-chart="liquidity" viewBox="0 0 1000 260" preserveAspectRatio="none" aria-label="Observed total liquidity over time"></svg>
          </section>
        </div>
      </div>
    `;
    this.ready = true;
  }

  set(selector, value) {
    const node = this.element.querySelector(`[data-pulse="${selector}"]`);
    if (node) node.textContent = value;
  }

  render({ current, history }) {
    this.init();
    if (!current) return;

    const active = current.active_count;
    this.set("active", count(active));
    this.set("volume", money(current.volume_5m.total));
    this.set("volume-current", money(current.volume_5m.total));
    this.set("volume-coverage", coverageLabel(current.volume_5m.known_tokens, active));
    this.set("buy-share", percent(current.pressure_5m.buy_share_pct));
    this.set("pressure-current", percent(current.pressure_5m.buy_share_pct));
    this.set("pressure-coverage", coverageLabel(current.pressure_5m.known_tokens, active));
    this.set(
      "pressure-detail",
      `Buy ${money(current.pressure_5m.buy_volume)} · Sell ${money(current.pressure_5m.sell_volume)} · Net ${signedMoney(current.pressure_5m.net_volume)}`,
    );
    this.set("liquidity", money(current.liquidity.total));
    this.set("liquidity-current", money(current.liquidity.total));
    this.set("liquidity-median", `median ${money(current.liquidity.median)}`);
    this.set("liquidity-coverage", coverageLabel(current.liquidity.known_tokens, active));
    this.set("breadth", percent(current.volume_5m.breadth_pct));
    this.set("concentration", percent(current.volume_5m.top10_share_pct));

    renderLineChart(
      this.element.querySelector('[data-pulse-chart="volume"]'),
      history,
      point => point.volume_5m.total,
      { minValue: 0 },
    );
    renderLineChart(
      this.element.querySelector('[data-pulse-chart="pressure"]'),
      history,
      point => point.pressure_5m.buy_share_pct,
      { minValue: 0, maxValue: 100 },
    );
    renderLineChart(
      this.element.querySelector('[data-pulse-chart="liquidity"]'),
      history,
      point => point.liquidity.total,
      { minValue: 0 },
    );
  }
}
