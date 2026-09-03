import { TokenUniverseView } from "./views/token-universe-view.js";
import { installUniverseSignals } from "./views/universe-signals.js";

installUniverseSignals(TokenUniverseView);
await import("./app.js");
