import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const indexSource = readFileSync(
  new URL("../src/observatory/static/index.html", import.meta.url),
  "utf8",
);
const analystSource = readFileSync(
  new URL("../src/observatory/static/js/analyst-ui.js", import.meta.url),
  "utf8",
);
const focusCss = readFileSync(
  new URL("../src/observatory/static/analyst-focus.css", import.meta.url),
  "utf8",
);

test("Analyst has one explicit focus workspace without a second state owner", () => {
  assert.match(indexSource, /id="analyst-card"/);
  assert.match(indexSource, /id="analyst-focus-toggle"/);
  assert.match(analystSource, /setFocused\(focused\)/);
  assert.match(analystSource, /this\.setFocused\(true\)/);
  assert.match(analystSource, /analyst-focus-active/);
  assert.match(focusCss, /\.analyst-card\.analyst-focused/);
  assert.doesNotMatch(analystSource, /fetch\(|EventSource|new Map\(/);
});

test("focused research result separates question answer and evidence", () => {
  assert.match(indexSource, /id="analyst-result-question"/);
  assert.match(indexSource, /id="analyst-answer"/);
  assert.match(indexSource, /id="analyst-evidence-heading"/);
  assert.match(indexSource, /id="analyst-sources"/);
  assert.match(indexSource, /id="analyst-answer-copy"/);
  assert.match(analystSource, /#renderAnswer\(text\)/);
  assert.doesNotMatch(analystSource, /innerHTML/);
});

test("selected-token analysis exposes exact Mint context", () => {
  assert.match(indexSource, /id="analyst-context"/);
  assert.match(indexSource, /id="analyst-context-mint"/);
  assert.match(analystSource, /this\.contextMint\.textContent = token\?\.mint \|\| ""/);
});

test("existing Analyst request contract remains scope question and optional mint", () => {
  assert.match(analystSource, /const body = \{ scope: requestScope, question \}/);
  assert.match(analystSource, /if \(config\.needsToken\) body\.mint = mint/);
  assert.match(analystSource, /this\.requestAnalyst\(body\)/);
});
