import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const indexSource = readFileSync(
  new URL("../src/observatory/static/index.html", import.meta.url),
  "utf8",
);
const appSource = readFileSync(
  new URL("../src/observatory/static/js/app.js", import.meta.url),
  "utf8",
);
const tokenUiSource = readFileSync(
  new URL("../src/observatory/static/js/token-ui.js", import.meta.url),
  "utf8",
);
const stylesSource = readFileSync(
  new URL("../src/observatory/static/styles.css", import.meta.url),
  "utf8",
);

test("WP1 keeps one-screen stage with a resizable collapsible context panel", () => {
  assert.match(indexSource, /id="workspace"/);
  assert.match(indexSource, /id="side-panel-resizer"/);
  assert.match(indexSource, /id="side-panel-toggle"/);
  assert.match(appSource, /setSidePanelWidth/);
  assert.match(appSource, /setSidePanelCollapsed/);
  assert.match(stylesSource, /--side-panel-width:/);
  assert.match(stylesSource, /\.workspace\.panel-collapsed/);
});

test("WP1 inspector exposes the complete Mint with an explicit copy action", () => {
  assert.match(indexSource, /<code id="detail-mint">/);
  assert.match(indexSource, /id="detail-mint-copy"/);
  assert.match(tokenUiSource, /navigator\.clipboard\.writeText\(token\.mint\)/);
  assert.match(stylesSource, /overflow-wrap:\s*anywhere/);
});

test("active status is not rendered as redundant selected-token emphasis", () => {
  assert.match(tokenUiSource, /"state-badge active hidden"/);
  assert.match(tokenUiSource, /"state-badge retired"/);
});
