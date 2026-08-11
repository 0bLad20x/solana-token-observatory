import assert from "node:assert/strict";
import test from "node:test";

import { ObservatoryState } from "../src/observatory/static/js/state.js";

function token(
  mint,
  symbol,
  name,
  { trackingEnabled = true, marketCap = null, liquidity = null, holders = null } = {},
) {
  return {
    mint,
    symbol,
    name,
    launchpad: "pump.fun",
    tracking_enabled: trackingEnabled,
    market_cap: marketCap,
    liquidity,
    holders,
  };
}

test("search sorts matching identities by market cap", () => {
  const state = new ObservatoryState();
  state.load([
    token("ExactMint1111111111111111111111111111111", "CAT", "Cat Coin", { marketCap: 10 }),
    token("OtherMint2222222222222222222222222222222", "CATS", "Cats Club", { marketCap: 100 }),
    token("MissingMint33333333333333333333333333333", "CATX", "Cat Unknown"),
  ]);

  assert.deepEqual(
    state.searchTokens("cat").map(item => item.symbol),
    ["CATS", "CAT", "CATX"],
  );
  assert.equal(state.searchTokens("ExactMint1111111111111111111111111111111")[0].symbol, "CAT");
});

test("search covers name and mint but excludes retired tokens", () => {
  const state = new ObservatoryState();
  state.load([
    token("AlphaMint1111111111111111111111111111111", "AAA", "Northern Light"),
    token("RetiredMint22222222222222222222222222222", "OLD", "Northern Ghost", {
      trackingEnabled: false,
    }),
  ]);

  assert.deepEqual(state.searchTokens("northern").map(item => item.symbol), ["AAA"]);
  assert.deepEqual(state.searchTokens("alphamint").map(item => item.symbol), ["AAA"]);
});

test("search respects its result bound and live state", () => {
  const state = new ObservatoryState();
  state.load([
    token("MintA11111111111111111111111111111111111", "ONE", "Shared One"),
    token("MintB22222222222222222222222222222222222", "TWO", "Shared Two"),
  ]);

  assert.equal(state.searchTokens("shared", 1).length, 1);
  state.applyEvent({
    type: "token_added",
    token: token("MintC33333333333333333333333333333333333", "NEW", "Fresh Arrival"),
  });
  assert.equal(state.searchTokens("fresh")[0].symbol, "NEW");
});
