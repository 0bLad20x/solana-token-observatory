import { TokenUniverseView } from "./views/token-universe-view.js";
import { installUniverseSignals } from "./views/universe-signals.js";

installUniverseSignals(TokenUniverseView);

const renderWithSignals = TokenUniverseView.prototype.render;
TokenUniverseView.prototype.render = function renderActiveUniverse(payload = {}) {
  const tokens = Array.isArray(payload.tokens)
    ? payload.tokens.filter(token => token?.tracking_enabled)
    : [];
  return renderWithSignals.call(this, { ...payload, tokens });
};

await import("./app.js");
