import { exec } from "node:child_process";
import { createReadStream } from "node:fs";
import { appendFile, mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { createInterface } from "node:readline";
import { promisify } from "node:util";

const execAsync = promisify(exec);

const DEFAULTS = {
  mode: "live",
  minMarketCap: null,
  maxMarketCap: null,
  maxCreated: null,
  minCreated: null,
  minTotalFee: null,
  rps: 20,
  concurrency: 1,
  startWidth: 10_000,
  out: null,
  mintsOut: null,
  eventsOut: null,
  pollSeconds: 2,
  once: false,
  cold: false,
};

const MODE_DEFAULTS = {
  full: {
    minMarketCap: 0.1,
    maxMarketCap: null,
    maxCreated: null,
    minTotalFee: 0.01,
    out: "data/gmgn_full_marketcap.json",
    mintsOut: "data/gmgn_full_mints.jsonl",
    eventsOut: null,
  },
  live: {
    minMarketCap: 30_000,
    maxMarketCap: 5_000_000,
    maxCreated: "30m",
    minTotalFee: 0.01,
    out: "data/gmgn_live_marketcap.json",
    mintsOut: "data/gmgn_live_mints.jsonl",
    eventsOut: null,
  },
  "signal-live": {
    minMarketCap: 30_000,
    maxMarketCap: 5_000_000,
    maxCreated: null,
    minTotalFee: null,
    out: "data/gmgn_signal_live_state.json",
    mintsOut: null,
    eventsOut: "data/gmgn_signal_live_events.jsonl",
  },
  "signal-full": {
    minMarketCap: 30_000,
    maxMarketCap: 5_000_000,
    maxCreated: null,
    minTotalFee: null,
    out: "data/gmgn_signal_full_state.json",
    mintsOut: null,
    eventsOut: "data/gmgn_signal_full_events.jsonl",
  },
};

const TRENCHES = {
  limit: 80,
  target: 77,
  targetMin: 74,
  mergeThreshold: 50,
  growth: [
    [0, 8], [20, 4], [40, 2.5], [55, 2], [65, 1.6], [70, 1.4], [73, 1.2],
  ],
};

// Fast live feed: only signals useful for immediate reaction.
const LIVE_SIGNAL_TYPES = [2, 5, 6, 7, 8, 10, 12, 20];

// Full signal archive: all currently safe explicitly queryable signal types.
// 14-16 are intentionally excluded because the current upstream rejects them when requested explicitly.
const FULL_SIGNAL_TYPES = [...Array.from({ length: 13 }, (_, i) => i + 1), 17, 18, 19, 20, 21];

// Initial live-quality profile. These thresholds are deliberately data-driven knobs, not permanent truth.
const SIGNAL_LIVE_PROFILE = {
  2:  { name: "Dex Ad",          totalFeeMin: 5 },
  5:  { name: "Dex Boost",       totalFeeMin: 10 },
  6:  { name: "Price Up",        totalFeeMin: 10 },
  7:  { name: "ATH",             totalFeeMin: 10 },
  8:  { name: "MC Key Level",    totalFeeMin: 10 },
  10: { name: "Bundler Sell",    totalFeeMin: 10 },
  12: { name: "Smart Money Buy", totalFeeMin: 5 },
  20: { name: "KOL Buy",         totalFeeMin: 5 },
};

const SIGNAL_LIVE_MAX_AGE_SECONDS = 120;
const SIGNAL_LIMIT = 50;
const SIGNAL_MIN_WIDTH = 1;
const SIGNAL_MAX_SPLIT_PASSES = 30;
const SIGNAL_GROUP_BATCH_SIZE = 20;

const MIN_WIDTH = 0.00001;
const MAX_ADJUSTMENTS = 40;
const TAIL_CHECK_EVERY = 4;
const TAIL_WIDTH_GROWTH_TRIGGER = 8;
const PARTIAL_SAVE_EVERY = 5;

const sleep = ms => new Promise(resolvePromise => setTimeout(resolvePromise, ms));
const clean = value => Number(Number(value).toPrecision(15));
const widthOf = (min, max) => (max === null ? null : clean(max - min));
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const sameNumber = (left, right) => Math.abs(left - right) <= 1e-10;
const displayCap = value => (value === null ? "∞" : value);

// ============================================================
// CLI
// ============================================================

function readNumber(argv, index, flag) {
  if (index + 1 >= argv.length) throw new Error(`${flag} benötigt einen Wert`);
  return Number(argv[index + 1]);
}

function readText(argv, index, flag) {
  if (index + 1 >= argv.length) throw new Error(`${flag} benötigt einen Wert`);
  return argv[index + 1];
}

function readOptionalNumber(argv, index, flag) {
  const value = readText(argv, index, flag);
  if (/^(none|null|inf|infinity)$/i.test(value)) return null;
  return Number(value);
}

function parseArgs(argv) {
  const raw = { ...DEFAULTS };
  const explicitlySet = new Set();

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];

    if (arg === "--probe") continue;
    if (arg === "--cold") raw.cold = true;
    else if (arg === "--once") raw.once = true;
    else if (arg === "--mode") {
      raw.mode = readText(argv, i++, arg).toLowerCase();
      explicitlySet.add("mode");
    } else if (arg === "--min-marketcap") {
      raw.minMarketCap = readNumber(argv, i++, arg);
      explicitlySet.add("minMarketCap");
    } else if (arg === "--max-marketcap") {
      raw.maxMarketCap = readOptionalNumber(argv, i++, arg);
      explicitlySet.add("maxMarketCap");
    } else if (arg === "--max-created") {
      raw.maxCreated = readText(argv, i++, arg);
      explicitlySet.add("maxCreated");
    } else if (arg === "--min-created") {
      raw.minCreated = readText(argv, i++, arg);
      explicitlySet.add("minCreated");
    } else if (arg === "--min-total-fee") {
      raw.minTotalFee = readOptionalNumber(argv, i++, arg);
      explicitlySet.add("minTotalFee");
    } else if (arg === "--rps") {
      raw.rps = readNumber(argv, i++, arg);
    } else if (arg === "--concurrency") {
      raw.concurrency = readNumber(argv, i++, arg);
    } else if (arg === "--start-width") {
      raw.startWidth = readNumber(argv, i++, arg);
    } else if (arg === "--out") {
      raw.out = readText(argv, i++, arg);
      explicitlySet.add("out");
    } else if (arg === "--mints-out") {
      raw.mintsOut = readText(argv, i++, arg);
      explicitlySet.add("mintsOut");
    } else if (arg === "--events-out") {
      raw.eventsOut = readText(argv, i++, arg);
      explicitlySet.add("eventsOut");
    } else if (arg === "--poll-seconds") {
      raw.pollSeconds = readNumber(argv, i++, arg);
    } else {
      throw new Error(`Unbekanntes Argument: ${arg}`);
    }
  }

  if (!Object.hasOwn(MODE_DEFAULTS, raw.mode)) {
    throw new Error("--mode muss full, live, signal-live oder signal-full sein");
  }

  const modeDefaults = MODE_DEFAULTS[raw.mode];
  const options = {
    ...raw,
    minMarketCap: explicitlySet.has("minMarketCap") ? raw.minMarketCap : modeDefaults.minMarketCap,
    maxMarketCap: explicitlySet.has("maxMarketCap") ? raw.maxMarketCap : modeDefaults.maxMarketCap,
    maxCreated: explicitlySet.has("maxCreated")
      ? raw.maxCreated
      : (explicitlySet.has("minCreated") ? null : modeDefaults.maxCreated),
    minTotalFee: explicitlySet.has("minTotalFee") ? raw.minTotalFee : modeDefaults.minTotalFee,
    out: explicitlySet.has("out") ? raw.out : modeDefaults.out,
    mintsOut: explicitlySet.has("mintsOut") ? raw.mintsOut : modeDefaults.mintsOut,
    eventsOut: explicitlySet.has("eventsOut") ? raw.eventsOut : modeDefaults.eventsOut,
  };

  if (!Number.isFinite(options.minMarketCap) || options.minMarketCap < 0) {
    throw new Error("--min-marketcap ist ungültig");
  }

  if (
    options.maxMarketCap !== null &&
    (!Number.isFinite(options.maxMarketCap) || options.maxMarketCap <= options.minMarketCap)
  ) {
    throw new Error("--max-marketcap muss größer als --min-marketcap sein");
  }

  if (options.minTotalFee !== null && (!Number.isFinite(options.minTotalFee) || options.minTotalFee < 0)) {
    throw new Error("--min-total-fee ist ungültig");
  }

  if (!Number.isFinite(options.rps) || options.rps <= 0) {
    throw new Error("--rps ist ungültig");
  }

  if (!Number.isInteger(options.concurrency) || options.concurrency <= 0) {
    throw new Error("--concurrency ist ungültig");
  }

  if (!Number.isFinite(options.startWidth) || options.startWidth <= 0) {
    throw new Error("--start-width ist ungültig");
  }

  if (!Number.isFinite(options.pollSeconds) || options.pollSeconds <= 0) {
    throw new Error("--poll-seconds ist ungültig");
  }

  if (!options.out) throw new Error("--out darf nicht leer sein");

  if (options.mode === "full") {
    if (options.maxCreated || options.minCreated) {
      throw new Error("--mode full verwendet bewusst keinen Created-Time-Filter");
    }
  }

  if (options.mode === "live") {
    const durationPattern = /^\d+(?:\.\d+)?[sm]$/i;
    if (options.maxCreated && !durationPattern.test(options.maxCreated)) {
      throw new Error("--max-created erwartet z. B. 30m oder 120s");
    }
    if (options.minCreated && !durationPattern.test(options.minCreated)) {
      throw new Error("--min-created erwartet z. B. 30m oder 120s");
    }
  }

  if (options.mode === "signal-live" || options.mode === "signal-full") {
    if (options.maxCreated || options.minCreated) {
      throw new Error(`--mode ${options.mode} verwendet keine Created-Time-Filter`);
    }

    if (options.maxMarketCap === null) {
      throw new Error(`--mode ${options.mode} benötigt eine endliche --max-marketcap`);
    }

    if (!options.eventsOut) {
      throw new Error(`--events-out darf in ${options.mode} nicht leer sein`);
    }

    if (resolve(options.out) === resolve(options.eventsOut)) {
      throw new Error("--out und --events-out müssen unterschiedliche Dateien sein");
    }
  } else {
    if (!options.mintsOut) throw new Error("--mints-out darf nicht leer sein");
    if (resolve(options.out) === resolve(options.mintsOut)) {
      throw new Error("--out und --mints-out müssen unterschiedliche Dateien sein");
    }
  }

  return options;
}

// ============================================================
// Files and API key
// ============================================================

async function ensureParent(filename) {
  await mkdir(dirname(resolve(filename)), { recursive: true });
}

async function loadApiKey() {
  const text = await readFile(".env", "utf8");

  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    const index = trimmed.indexOf("=");
    if (index < 0 || trimmed.slice(0, index).trim() !== "GMGN_API_KEY") continue;

    let value = trimmed.slice(index + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    if (!value) throw new Error("GMGN_API_KEY ist leer");
    return value;
  }

  throw new Error("GMGN_API_KEY fehlt in .env");
}

async function replaceFile(temp, target) {
  try {
    await rename(temp, target);
  } catch (error) {
    if (!["EEXIST", "EPERM"].includes(error?.code)) throw error;
    await unlink(target).catch(() => {});
    await rename(temp, target);
  }
}

async function writeJsonAtomic(filename, value) {
  await ensureParent(filename);
  const temp = `${filename}.tmp`;
  await writeFile(temp, JSON.stringify(value, null, 2), "utf8");
  await replaceFile(temp, filename);
}

// ============================================================
// Request handling
// ============================================================

class RequestGate {
  constructor(rps) {
    this.intervalMs = 1000 / rps;
    this.nextStartAt = 0;
  }

  async wait() {
    const waitMs = Math.max(0, this.nextStartAt - Date.now());
    if (waitMs) await sleep(waitMs);
    this.nextStartAt = Date.now() + this.intervalMs;
  }
}

function quoteShellValue(value) {
  const text = String(value);

  if (process.platform === "win32") {
    // This matches the quoting pattern already proven with gmgn-cli under cmd.exe.
    return `"${text.replace(/"/g, '\\"')}"`;
  }

  return `'${text.replace(/'/g, `'\\''`)}'`;
}

async function runGmgn(command, apiKey) {
  try {
    const { stdout } = await execAsync(command, {
      windowsHide: true,
      env: {
        ...process.env,
        GMGN_API_KEY: apiKey,
        GMGN_RATE_LIMIT_AUTO_RETRY_MAX_WAIT_MS: "0",
      },
      maxBuffer: 50 * 1024 * 1024,
    });

    return {
      ok: true,
      rateLimited: false,
      data: JSON.parse(stdout.trim()),
      error: null,
    };
  } catch (error) {
    const message = [error?.stderr, error?.stdout, error?.message]
      .filter(Boolean)
      .join(" ")
      .trim();

    return {
      ok: false,
      rateLimited: /HTTP 429|RATE_LIMIT_EXCEEDED|RATE_LIMIT_BANNED/i.test(message),
      data: null,
      error: message,
    };
  }
}

// ============================================================
// Shared response helpers
// ============================================================

function extractFeeFields(value, path = "", result = {}) {
  if (value == null) return result;

  if (Array.isArray(value)) {
    value.forEach((item, i) => extractFeeFields(item, `${path}[${i}]`, result));
    return result;
  }

  if (typeof value !== "object") return result;

  for (const [key, child] of Object.entries(value)) {
    const current = path ? `${path}.${key}` : key;
    if (/fee|tip|tax|royalty/i.test(key)) result[current] = child;
    else if (child && typeof child === "object") extractFeeFields(child, current, result);
  }

  return result;
}

function collectSignalEvents(value, result = [], seen = new Set()) {
  if (value == null) return result;

  if (Array.isArray(value)) {
    value.forEach(item => collectSignalEvents(item, result, seen));
    return result;
  }

  if (typeof value !== "object") return result;

  if (typeof value.token_address === "string" && value.id != null) {
    const key = String(value.id);
    if (!seen.has(key)) {
      seen.add(key);
      result.push(value);
    }
    return result;
  }

  Object.values(value).forEach(child => {
    if (child && typeof child === "object") collectSignalEvents(child, result, seen);
  });

  return result;
}

// ============================================================
// SIGNALS — shared event helpers
// ============================================================

async function loadSeenSignalIds(filename) {
  const ids = new Set();

  try {
    const input = createReadStream(filename, { encoding: "utf8" });
    const lines = createInterface({ input, crlfDelay: Infinity });

    for await (const line of lines) {
      if (!line.trim()) continue;

      try {
        const record = JSON.parse(line);
        if (record?.id != null) ids.add(String(record.id));
      } catch {
        // Eine einzelne beschädigte JSONL-Zeile darf den Feed nicht blockieren.
      }
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }

  return ids;
}

function normalizeSignalEvent(event, scanMode) {
  return {
    source: "gmgn.market.signal",
    scan_mode: scanMode,
    collected_at: new Date().toISOString(),
    id: event.id ?? null,
    token_address: event.token_address ?? null,
    signal_type: Number(event.signal_type),
    ath: event.ath ?? null,
    market_cap: event.market_cap ?? null,
    trigger_at: event.trigger_at ?? null,
    trigger_mc: event.trigger_mc ?? null,
    first_trigger_mc: event.first_trigger_mc ?? null,
    signal_times: event.signal_times ?? null,
    signal_times_by_type: event.signal_times_by_type ?? {},
    data: event.data ?? null,
    cur_data: event.cur_data ?? null,
  };
}

async function appendNewSignalEvents(filename, events, seenIds, scanMode) {
  const localIds = new Set();
  const fresh = [];

  for (const event of events) {
    const id = event?.id == null ? null : String(event.id);
    if (!id || seenIds.has(id) || localIds.has(id)) continue;

    localIds.add(id);
    fresh.push(normalizeSignalEvent(event, scanMode));
  }

  if (!fresh.length) return 0;

  await appendFile(
    filename,
    `${fresh.map(JSON.stringify).join("\n")}\n`,
    "utf8",
  );

  for (const id of localIds) seenIds.add(id);
  return fresh.length;
}

function buildSignalGroup(signalType, minTriggerMc, maxTriggerMc, totalFeeMin = null) {
  const group = {
    signal_type: [signalType],
    trigger_mc_min: minTriggerMc,
    trigger_mc_max: maxTriggerMc,
  };

  if (totalFeeMin !== null) group.total_fee_min = totalFeeMin;
  return group;
}

function buildSignalCommand(groups) {
  return [
    "gmgn-cli market signal",
    "--chain sol",
    `--groups ${quoteShellValue(JSON.stringify(groups))}`,
    "--raw",
  ].join(" ");
}

function countSignalEventsByType(events, signalTypes) {
  const counts = Object.fromEntries(signalTypes.map(type => [String(type), 0]));

  for (const event of events) {
    const key = String(Number(event.signal_type));
    if (Object.hasOwn(counts, key)) counts[key]++;
  }

  return counts;
}

function filterFreshSignalEvents(events, maxAgeSeconds, nowSeconds = Date.now() / 1000) {
  const cutoff = nowSeconds - maxAgeSeconds;

  return events.filter(event => {
    const triggerAt = Number(event.trigger_at);
    return Number.isFinite(triggerAt) && triggerAt >= cutoff;
  });
}

// ============================================================
// SIGNAL LIVE — one request per poll, freshness first
// ============================================================

function effectiveLiveSignalProfile(options) {
  return Object.fromEntries(
    LIVE_SIGNAL_TYPES.map(type => {
      const base = SIGNAL_LIVE_PROFILE[type];
      return [
        String(type),
        {
          ...base,
          totalFeeMin: options.minTotalFee ?? base.totalFeeMin,
        },
      ];
    }),
  );
}

function signalLiveConfigMatches(config, options) {
  if (!config || typeof config !== "object") return false;

  return (
    config.algorithm === "gmgn-signal-live-v3" &&
    config.mode === "signal-live" &&
    Number(config.min_trigger_mc) === Number(options.minMarketCap) &&
    Number(config.max_trigger_mc) === Number(options.maxMarketCap) &&
    Number(config.max_event_age_seconds) === Number(SIGNAL_LIVE_MAX_AGE_SECONDS) &&
    JSON.stringify(config.signal_types) === JSON.stringify(LIVE_SIGNAL_TYPES) &&
    JSON.stringify(config.profile) === JSON.stringify(effectiveLiveSignalProfile(options))
  );
}

async function loadSignalLiveState(options) {
  if (options.cold) return null;

  try {
    const state = JSON.parse(await readFile(options.out, "utf8"));
    return signalLiveConfigMatches(state?.config, options) ? state : null;
  } catch {
    return null;
  }
}

async function runSignalLive(options, apiKey) {
  await Promise.all([
    ensureParent(options.out),
    ensureParent(options.eventsOut),
  ]);

  const seenIds = await loadSeenSignalIds(options.eventsOut);
  const gate = new RequestGate(options.rps);
  const profile = effectiveLiveSignalProfile(options);

  let state = await loadSignalLiveState(options);
  const resumed = Boolean(state);

  if (!state) {
    const now = new Date().toISOString();

    state = {
      generated_at: now,
      updated_at: now,
      config: {
        algorithm: "gmgn-signal-live-v3",
        mode: "signal-live",
        chain: "sol",
        signal_types: LIVE_SIGNAL_TYPES,
        min_trigger_mc: options.minMarketCap,
        max_trigger_mc: options.maxMarketCap,
        max_event_age_seconds: SIGNAL_LIVE_MAX_AGE_SECONDS,
        poll_seconds: options.pollSeconds,
        limit_per_group: SIGNAL_LIMIT,
        profile,
      },
      summary: {
        resumed: false,
        cycles: 0,
        queries: 0,
        successful_queries: 0,
        failed_queries: 0,
        unique_events: seenIds.size,
        stale_events_ignored: 0,
        stopped_by_rate_limit: false,
        stop_reason: null,
      },
      last_cycle: null,
      last_error: null,
    };
  }

  state.config.poll_seconds = options.pollSeconds;
  state.summary.resumed = resumed;
  state.summary.unique_events = seenIds.size;
  state.summary.stop_reason = null;
  state.summary.stopped_by_rate_limit = false;

  let stopRequested = false;
  let fatalError = false;
  let wakePollSleep = null;

  function requestStop(signal) {
    if (stopRequested) return;
    stopRequested = true;
    state.summary.stop_reason = signal;

    console.log(
      `\n${signal} empfangen: laufenden Signal-Request abschließen und State speichern …`,
    );

    if (wakePollSleep) wakePollSleep();
  }

  const onSigint = () => requestStop("SIGINT");
  const onSigterm = () => requestStop("SIGTERM");

  process.on("SIGINT", onSigint);
  process.on("SIGTERM", onSigterm);

  async function saveState() {
    state.updated_at = new Date().toISOString();
    state.summary.unique_events = seenIds.size;
    await writeJsonAtomic(options.out, state);
  }

  async function waitForNextPoll(cycleStartedAt) {
    if (stopRequested) return;

    const remainingMs = Math.max(
      0,
      options.pollSeconds * 1000 - (Date.now() - cycleStartedAt),
    );

    if (!remainingMs) return;

    await new Promise(resolvePromise => {
      let done = false;

      const finish = () => {
        if (done) return;
        done = true;
        wakePollSleep = null;
        clearTimeout(timer);
        resolvePromise();
      };

      const timer = setTimeout(finish, remainingMs);
      wakePollSleep = finish;
    });
  }

  async function runCycle() {
    const cycleStartedAt = Date.now();
    const cycleStartedIso = new Date(cycleStartedAt).toISOString();
    const uniqueBefore = seenIds.size;

    const groups = LIVE_SIGNAL_TYPES.map(type => {
      const rule = profile[String(type)];
      return buildSignalGroup(
        type,
        options.minMarketCap,
        options.maxMarketCap,
        rule.totalFeeMin,
      );
    });

    await gate.wait();
    if (stopRequested) return { ok: true, cycleStartedAt };

    const queryNumber = state.summary.queries + 1;
    console.log(
      `signal q${String(queryNumber).padStart(4, "0")} | live | groups=${groups.length}`,
    );

    const startedAt = Date.now();
    const result = await runGmgn(buildSignalCommand(groups), apiKey);
    const durationMs = Date.now() - startedAt;

    state.summary.queries++;

    if (!result.ok) {
      state.summary.failed_queries++;
      state.summary.stopped_by_rate_limit = result.rateLimited;
      state.last_error = {
        at: new Date().toISOString(),
        rate_limited: result.rateLimited,
        error: result.error,
      };

      console.error(`    ERROR | ${durationMs}ms | ${result.error}`);

      if (!result.rateLimited) {
        fatalError = true;
        stopRequested = true;
        state.summary.stop_reason = "request_error";
      }

      await saveState();
      return { ok: false, rateLimited: result.rateLimited, cycleStartedAt };
    }

    state.summary.successful_queries++;
    state.summary.stopped_by_rate_limit = false;
    state.last_error = null;

    const events = collectSignalEvents(result.data);
    const freshEvents = filterFreshSignalEvents(events, SIGNAL_LIVE_MAX_AGE_SECONDS);
    const staleIgnored = events.length - freshEvents.length;

    const countsByType = countSignalEventsByType(events, LIVE_SIGNAL_TYPES);
    const freshCountsByType = countSignalEventsByType(freshEvents, LIVE_SIGNAL_TYPES);

    const responseCappedTypes = LIVE_SIGNAL_TYPES.filter(
      type => countsByType[String(type)] >= SIGNAL_LIMIT,
    );

    // Nur wenn alle 50 Slots auch frisch sind, könnten aktuelle Events fehlen.
    const freshCappedTypes = LIVE_SIGNAL_TYPES.filter(
      type => freshCountsByType[String(type)] >= SIGNAL_LIMIT,
    );

    const newEvents = await appendNewSignalEvents(
      options.eventsOut,
      freshEvents,
      seenIds,
      "signal-live",
    );

    state.summary.cycles++;
    state.summary.stale_events_ignored += staleIgnored;

    state.last_cycle = {
      started_at: cycleStartedIso,
      completed_at: new Date().toISOString(),
      duration_ms: Date.now() - cycleStartedAt,
      query_duration_ms: durationMs,
      returned_events: events.length,
      fresh_events: freshEvents.length,
      stale_events_ignored: staleIgnored,
      new_events: seenIds.size - uniqueBefore,
      unique_events_total: seenIds.size,
      counts_by_type: countsByType,
      fresh_counts_by_type: freshCountsByType,
      response_capped_types: responseCappedTypes,
      fresh_capped_types: freshCappedTypes,
    };

    await saveState();

    console.log(
      `    events=${events.length}` +
      ` | fresh=${freshEvents.length}` +
      ` | new=${newEvents}` +
      ` | unique_total=${seenIds.size}` +
      ` | fresh_capped=${freshCappedTypes.length ? freshCappedTypes.join(",") : "-"}` +
      ` | ${durationMs}ms`,
    );

    return { ok: true, cycleStartedAt };
  }

  console.log("\n=== SIGNAL LIVE ===");
  console.log(`Signal types: ${LIVE_SIGNAL_TYPES.join(", ")}`);
  console.log(`Trigger MC: ${options.minMarketCap} - ${options.maxMarketCap}`);
  console.log(`Freshness: <= ${SIGNAL_LIVE_MAX_AGE_SECONDS}s`);
  console.log(`Poll: ${options.once ? "once" : `${options.pollSeconds}s`}`);
  console.log("Quality filters:");

  for (const type of LIVE_SIGNAL_TYPES) {
    const rule = profile[String(type)];
    console.log(`  ${type.toString().padStart(2, " ")} ${rule.name.padEnd(20, " ")} total_fee >= ${rule.totalFeeMin}`);
  }

  console.log(`State: ${options.out}`);
  console.log(`Events: ${options.eventsOut}`);
  console.log(`Existing event IDs: ${seenIds.size}`);
  console.log(`State: ${resumed ? "resume" : "cold"}${options.cold ? " (--cold; event log retained)" : ""}\n`);

  try {
    do {
      const cycle = await runCycle();

      if (stopRequested || options.once) break;

      // Bei 429 nicht hektisch retrien; normaler nächster Poll reicht.
      if (!cycle.ok && !cycle.rateLimited) break;

      await waitForNextPoll(cycle.cycleStartedAt);
    } while (!stopRequested);
  } finally {
    await saveState();
    process.off("SIGINT", onSigint);
    process.off("SIGTERM", onSigterm);
  }

  if (["SIGINT", "SIGTERM"].includes(state.summary.stop_reason)) {
    process.exitCode = 130;
  } else if (fatalError) {
    process.exitCode = 1;
  }

  console.log("\n========================================");
  console.log(stopRequested ? "SIGNAL LIVE GESTOPPT" : "SIGNAL LIVE FERTIG");
  console.log("========================================");
  console.log(`Cycles: ${state.summary.cycles}`);
  console.log(`Queries: ${state.summary.queries}`);
  console.log(`Successful: ${state.summary.successful_queries}`);
  console.log(`Failed: ${state.summary.failed_queries}`);
  console.log(`Unique Events: ${seenIds.size}`);
  console.log(`Last new events: ${state.last_cycle?.new_events ?? 0}`);
  console.log(`Last fresh capped: ${state.last_cycle?.fresh_capped_types?.join(",") || "-"}`);
  console.log(`Stop reason: ${state.summary.stop_reason ?? "-"}`);
  console.log(`State: ${options.out}`);
  console.log(`Events: ${options.eventsOut}`);
}

// ============================================================
// SIGNAL FULL — exhaustive coverage, saturation may split
// ============================================================

function initialSignalFullRanges(options) {
  return Object.fromEntries(
    FULL_SIGNAL_TYPES.map(type => [
      String(type),
      [{
        min_trigger_mc: options.minMarketCap,
        max_trigger_mc: options.maxMarketCap,
      }],
    ]),
  );
}

function signalFullConfigMatches(config, options) {
  if (!config || typeof config !== "object") return false;

  return (
    config.algorithm === "gmgn-signal-full-v1" &&
    config.mode === "signal-full" &&
    Number(config.min_trigger_mc) === Number(options.minMarketCap) &&
    Number(config.max_trigger_mc) === Number(options.maxMarketCap) &&
    (config.min_total_fee ?? null) === (options.minTotalFee ?? null) &&
    JSON.stringify(config.signal_types) === JSON.stringify(FULL_SIGNAL_TYPES)
  );
}

async function loadSignalFullState(options) {
  if (options.cold) return null;

  try {
    const state = JSON.parse(await readFile(options.out, "utf8"));
    if (!signalFullConfigMatches(state?.config, options)) return null;

    for (const type of FULL_SIGNAL_TYPES) {
      const ranges = state?.ranges_by_type?.[String(type)];
      if (!Array.isArray(ranges) || !ranges.length) return null;
    }

    return state;
  } catch {
    return null;
  }
}

function signalRangeKey(range) {
  return `${range.min_trigger_mc}:${range.max_trigger_mc}`;
}

function rangeContainsTriggerMc(range, triggerMc) {
  return (
    Number.isFinite(triggerMc) &&
    triggerMc >= range.min_trigger_mc &&
    triggerMc <= range.max_trigger_mc
  );
}

function splitSignalRange(range) {
  const width = range.max_trigger_mc - range.min_trigger_mc;
  if (!Number.isFinite(width) || width <= SIGNAL_MIN_WIDTH) return null;

  const mid = clean(range.min_trigger_mc + width / 2);
  if (mid <= range.min_trigger_mc || mid >= range.max_trigger_mc) return null;

  return [
    {
      min_trigger_mc: range.min_trigger_mc,
      max_trigger_mc: mid,
    },
    {
      min_trigger_mc: mid,
      max_trigger_mc: range.max_trigger_mc,
    },
  ];
}

function flattenSignalFullRanges(state) {
  const descriptors = [];

  for (const type of FULL_SIGNAL_TYPES) {
    for (const range of state.ranges_by_type[String(type)]) {
      descriptors.push({ signal_type: type, ...range });
    }
  }

  return descriptors;
}

function replaceSignalFullRange(state, descriptor, replacements) {
  const key = String(descriptor.signal_type);
  const oldKey = signalRangeKey(descriptor);

  state.ranges_by_type[key] = state.ranges_by_type[key]
    .filter(range => signalRangeKey(range) !== oldKey)
    .concat(replacements)
    .sort((a, b) => a.min_trigger_mc - b.min_trigger_mc);
}

function buildSignalFullQueryBatches(descriptors) {
  const byType = new Map();

  for (const descriptor of descriptors) {
    const type = Number(descriptor.signal_type);
    if (!byType.has(type)) byType.set(type, []);
    byType.get(type).push(descriptor);
  }

  for (const ranges of byType.values()) {
    ranges.sort((a, b) => a.min_trigger_mc - b.min_trigger_mc);
  }

  const maxRangesPerType = Math.max(
    0,
    ...[...byType.values()].map(ranges => ranges.length),
  );

  const batches = [];

  // GMGN erlaubt jeden signal_type innerhalb eines --groups Requests nur einmal.
  for (let slot = 0; slot < maxRangesPerType; slot++) {
    const round = [];

    for (const type of FULL_SIGNAL_TYPES) {
      const descriptor = byType.get(type)?.[slot];
      if (descriptor) round.push(descriptor);
    }

    for (let i = 0; i < round.length; i += SIGNAL_GROUP_BATCH_SIZE) {
      batches.push(round.slice(i, i + SIGNAL_GROUP_BATCH_SIZE));
    }
  }

  return batches;
}

async function runSignalFull(options, apiKey) {
  await Promise.all([
    ensureParent(options.out),
    ensureParent(options.eventsOut),
  ]);

  const seenIds = await loadSeenSignalIds(options.eventsOut);
  const gate = new RequestGate(options.rps);

  let state = await loadSignalFullState(options);
  const resumed = Boolean(state);

  if (!state) {
    const now = new Date().toISOString();

    state = {
      generated_at: now,
      updated_at: now,
      config: {
        algorithm: "gmgn-signal-full-v1",
        mode: "signal-full",
        chain: "sol",
        signal_types: FULL_SIGNAL_TYPES,
        excluded_signal_types: [14, 15, 16],
        min_trigger_mc: options.minMarketCap,
        max_trigger_mc: options.maxMarketCap,
        min_total_fee: options.minTotalFee,
        limit_per_group: SIGNAL_LIMIT,
      },
      summary: {
        resumed: false,
        runs: 0,
        queries: 0,
        successful_queries: 0,
        failed_queries: 0,
        unique_events: seenIds.size,
        stopped_by_rate_limit: false,
        unresolved: false,
        completed: false,
        stop_reason: null,
      },
      ranges_by_type: initialSignalFullRanges(options),
      last_run: null,
      last_error: null,
    };
  }

  state.summary.resumed = resumed;
  state.summary.unique_events = seenIds.size;
  state.summary.stopped_by_rate_limit = false;
  state.summary.unresolved = false;
  state.summary.completed = false;
  state.summary.stop_reason = null;

  let stopRequested = false;
  let fatalError = false;

  function requestStop(signal) {
    if (stopRequested) return;
    stopRequested = true;
    state.summary.stop_reason = signal;
    console.log(`\n${signal} empfangen: laufenden Signal-Full-Request abschließen und State speichern …`);
  }

  const onSigint = () => requestStop("SIGINT");
  const onSigterm = () => requestStop("SIGTERM");

  process.on("SIGINT", onSigint);
  process.on("SIGTERM", onSigterm);

  async function saveState() {
    state.updated_at = new Date().toISOString();
    state.summary.unique_events = seenIds.size;
    await writeJsonAtomic(options.out, state);
  }

  async function queryDescriptorBatch(descriptors, purpose, batchNumber, batchTotal) {
    const groups = descriptors.map(descriptor =>
      buildSignalGroup(
        descriptor.signal_type,
        descriptor.min_trigger_mc,
        descriptor.max_trigger_mc,
        options.minTotalFee,
      ),
    );

    const types = groups.map(group => Number(group.signal_type[0]));
    if (new Set(types).size !== types.length) {
      throw new Error(`Interner Fehler: duplicate signal_type in Full-Batch: ${types.join(",")}`);
    }

    await gate.wait();
    if (stopRequested) {
      return { ok: true, complete: false, events: [] };
    }

    const queryNumber = state.summary.queries + 1;
    const batchLabel = batchTotal > 1 ? ` | batch=${batchNumber}/${batchTotal}` : "";

    console.log(
      `signal q${String(queryNumber).padStart(4, "0")} | ${purpose}` +
      ` | groups=${groups.length}${batchLabel}`,
    );

    const startedAt = Date.now();
    const result = await runGmgn(buildSignalCommand(groups), apiKey);
    const durationMs = Date.now() - startedAt;

    state.summary.queries++;

    if (!result.ok) {
      state.summary.failed_queries++;
      state.summary.stopped_by_rate_limit = result.rateLimited;
      state.last_error = {
        at: new Date().toISOString(),
        rate_limited: result.rateLimited,
        error: result.error,
      };

      console.error(`    ERROR | ${durationMs}ms | ${result.error}`);

      if (!result.rateLimited) {
        fatalError = true;
        state.summary.stop_reason = "request_error";
      } else {
        state.summary.stop_reason = "rate_limit";
      }

      stopRequested = true;
      await saveState();

      return {
        ok: false,
        complete: false,
        rateLimited: result.rateLimited,
        events: [],
      };
    }

    state.summary.successful_queries++;
    state.summary.stopped_by_rate_limit = false;
    state.last_error = null;

    const events = collectSignalEvents(result.data);
    const newEvents = await appendNewSignalEvents(
      options.eventsOut,
      events,
      seenIds,
      "signal-full",
    );

    console.log(
      `    events=${events.length}` +
      ` | new=${newEvents}` +
      ` | unique_total=${seenIds.size}` +
      ` | ${durationMs}ms`,
    );

    return { ok: true, complete: true, events };
  }

  async function queryDescriptors(descriptors, purpose) {
    const batches = buildSignalFullQueryBatches(descriptors);
    const allEvents = [];

    for (let i = 0; i < batches.length; i++) {
      if (stopRequested) {
        return { ok: true, complete: false, events: allEvents };
      }

      const response = await queryDescriptorBatch(
        batches[i],
        purpose,
        i + 1,
        batches.length,
      );

      if (!response.ok || !response.complete) {
        return { ...response, events: allEvents };
      }

      allEvents.push(...response.events);
    }

    return {
      ok: true,
      complete: true,
      events: collectSignalEvents(allEvents),
    };
  }

  console.log("\n=== SIGNAL FULL ===");
  console.log(`Signal types: ${FULL_SIGNAL_TYPES.join(", ")}`);
  console.log("Excluded unsafe explicit types: 14, 15, 16");
  console.log(`Trigger MC: ${options.minMarketCap} - ${options.maxMarketCap}`);
  console.log(`Total fee filter: ${options.minTotalFee ?? "none"}`);
  console.log("Coverage: exhaustive with Trigger-MC saturation splitting");
  console.log(`State: ${options.out}`);
  console.log(`Events: ${options.eventsOut}`);
  console.log(`Existing event IDs: ${seenIds.size}`);
  console.log(`State: ${resumed ? "resume" : "cold"}${options.cold ? " (--cold; event log retained)" : ""}\n`);

  const runStartedAt = Date.now();
  const queriesBefore = state.summary.queries;
  const uniqueBefore = seenIds.size;
  let saturatedRanges = 0;
  const unresolvedRanges = [];

  let pending = flattenSignalFullRanges(state);

  try {
    for (
      let pass = 0;
      pending.length && pass < SIGNAL_MAX_SPLIT_PASSES && !stopRequested;
      pass++
    ) {
      const response = await queryDescriptors(
        pending,
        pass === 0 ? "full" : `saturation_split_${pass}`,
      );

      if (!response.ok || !response.complete || stopRequested) break;

      const nextPending = [];
      const replacements = [];

      for (const descriptor of pending) {
        const matchingIds = new Set();

        for (const event of response.events) {
          if (Number(event.signal_type) !== descriptor.signal_type) continue;

          const triggerMc = Number(event.trigger_mc);
          if (!rangeContainsTriggerMc(descriptor, triggerMc)) continue;
          if (event.id != null) matchingIds.add(String(event.id));
        }

        if (matchingIds.size < SIGNAL_LIMIT) continue;

        saturatedRanges++;
        const children = splitSignalRange(descriptor);

        if (!children) {
          unresolvedRanges.push({
            ...descriptor,
            count: matchingIds.size,
            reason: "minimum_width_saturated",
          });
          continue;
        }

        replacements.push({ descriptor, children });
        nextPending.push(
          ...children.map(range => ({
            signal_type: descriptor.signal_type,
            ...range,
          })),
        );
      }

      // Erst nach einem vollständig abgearbeiteten Pass den gelernten State verändern.
      for (const { descriptor, children } of replacements) {
        replaceSignalFullRange(state, descriptor, children);
      }

      await saveState();
      pending = nextPending;
    }

    if (pending.length && !stopRequested) {
      unresolvedRanges.push(
        ...pending.map(descriptor => ({
          ...descriptor,
          reason: "max_split_passes",
        })),
      );
    }

    state.summary.runs++;
    state.summary.unresolved = unresolvedRanges.length > 0;
    state.summary.completed = !stopRequested && unresolvedRanges.length === 0 && pending.length === 0;

    state.last_run = {
      started_at: new Date(runStartedAt).toISOString(),
      completed_at: new Date().toISOString(),
      duration_ms: Date.now() - runStartedAt,
      queries: state.summary.queries - queriesBefore,
      new_events: seenIds.size - uniqueBefore,
      unique_events_total: seenIds.size,
      saturated_ranges: saturatedRanges,
      unresolved_ranges: unresolvedRanges,
      range_count_by_type: Object.fromEntries(
        FULL_SIGNAL_TYPES.map(type => [
          String(type),
          state.ranges_by_type[String(type)].length,
        ]),
      ),
    };
  } finally {
    await saveState();
    process.off("SIGINT", onSigint);
    process.off("SIGTERM", onSigterm);
  }

  if (["SIGINT", "SIGTERM"].includes(state.summary.stop_reason)) {
    process.exitCode = 130;
  } else if (fatalError) {
    process.exitCode = 1;
  }

  console.log("\n========================================");
  console.log(state.summary.completed ? "SIGNAL FULL FERTIG" : "SIGNAL FULL GESTOPPT/GESPEICHERT");
  console.log("========================================");
  console.log(`Runs: ${state.summary.runs}`);
  console.log(`Queries: ${state.summary.queries}`);
  console.log(`Successful: ${state.summary.successful_queries}`);
  console.log(`Failed: ${state.summary.failed_queries}`);
  console.log(`Unique Events: ${seenIds.size}`);
  console.log(`Last new events: ${state.last_run?.new_events ?? 0}`);
  console.log(`Saturated ranges: ${state.last_run?.saturated_ranges ?? 0}`);
  console.log(`Unresolved: ${state.summary.unresolved}`);
  console.log(`Completed: ${state.summary.completed}`);
  console.log(`Stop reason: ${state.summary.stop_reason ?? "-"}`);
  console.log(`State: ${options.out}`);
  console.log(`Events: ${options.eventsOut}`);
}


// ============================================================
// TRENCHES — discovery/state collector
// ============================================================

function summarizeTrenchesResponse(data) {
  const bucketCounts = {};
  const localMints = new Set();
  const entries = [];
  let rawRecords = 0;

  if (!data || typeof data !== "object") {
    return {
      bucketCounts,
      maxBucket: 0,
      rawRecords: 0,
      uniqueMints: 0,
      duplicateRecords: 0,
      saturated: false,
      entries,
    };
  }

  for (const [bucket, tokens] of Object.entries(data)) {
    if (!Array.isArray(tokens)) continue;

    bucketCounts[bucket] = tokens.length;
    rawRecords += tokens.length;

    for (const token of tokens) {
      if (!token || typeof token !== "object" || !token.address) continue;
      localMints.add(token.address);
      entries.push({ token, bucket });
    }
  }

  const maxBucket = Math.max(0, ...Object.values(bucketCounts));

  return {
    bucketCounts,
    maxBucket,
    rawRecords,
    uniqueMints: localMints.size,
    duplicateRecords: Math.max(0, rawRecords - localMints.size),
    saturated: maxBucket >= TRENCHES.limit,
    entries,
  };
}

function normalizedRangeList(ranges) {
  if (!Array.isArray(ranges)) return [];

  return ranges
    .map(range => {
      const rawMin = Object.hasOwn(range, "min_marketcap") ? range.min_marketcap : range.min;
      const rawMax = Object.hasOwn(range, "max_marketcap") ? range.max_marketcap : range.max;

      return {
        min: Number(rawMin),
        max: rawMax === null ? null : Number(rawMax),
      };
    })
    .filter(range => Number.isFinite(range.min) && (range.max === null || Number.isFinite(range.max)))
    .sort((a, b) => a.min - b.min);
}

function hasCompleteCoverage(ranges, startMarketCap, endMarketCap) {
  if (!ranges.length || !sameNumber(ranges[0].min, startMarketCap)) return false;

  for (let i = 0; i < ranges.length - 1; i++) {
    if (ranges[i].max === null || !sameNumber(ranges[i].max, ranges[i + 1].min)) return false;
  }

  const finalMax = ranges.at(-1)?.max ?? null;
  if (endMarketCap === null) return finalMax === null;
  return finalMax !== null && sameNumber(finalMax, endMarketCap);
}

function normalizeRanges(ranges, startMarketCap, endMarketCap) {
  const normalized = normalizedRangeList(ranges);
  return normalized.length && hasCompleteCoverage(normalized, startMarketCap, endMarketCap)
    ? normalized
    : null;
}

function sameOptionalText(left, right) {
  return (left ?? null) === (right ?? null);
}

function trenchesConfigMatches(config, options) {
  if (!config || typeof config !== "object") return false;

  const savedMax = config.max_marketcap ?? null;
  const sameMax = savedMax === null
    ? options.maxMarketCap === null
    : options.maxMarketCap !== null && sameNumber(Number(savedMax), options.maxMarketCap);

  return (
    config.range_dimension === "market_cap" &&
    config.scan_mode === options.mode &&
    Number(config.min_marketcap) === Number(options.minMarketCap) &&
    (config.min_total_fee ?? null) === (options.minTotalFee ?? null) &&
    sameMax &&
    sameOptionalText(config.max_created, options.maxCreated) &&
    sameOptionalText(config.min_created, options.minCreated)
  );
}

function contiguousPrefixEnd(ranges, startMarketCap, endMarketCap) {
  const normalized = normalizedRangeList(ranges);

  if (!normalized.length) return { cursor: startMarketCap, complete: false };
  if (!sameNumber(normalized[0].min, startMarketCap)) return null;

  let cursor = startMarketCap;

  for (const range of normalized) {
    if (!sameNumber(range.min, cursor)) break;

    if (range.max === null) {
      return { cursor: null, complete: endMarketCap === null };
    }

    cursor = range.max;

    if (endMarketCap !== null && sameNumber(cursor, endMarketCap)) {
      return { cursor, complete: true };
    }

    if (endMarketCap !== null && cursor > endMarketCap) return null;
  }

  return { cursor, complete: false };
}

async function loadPreviousTrenchesState(filename, options) {
  try {
    const data = JSON.parse(await readFile(filename, "utf8"));
    if (!trenchesConfigMatches(data?.config, options)) return null;
    return normalizeRanges(data?.ranges, options.minMarketCap, options.maxMarketCap);
  } catch {
    return null;
  }
}

async function loadPartialTrenchesOutput(filename, options) {
  try {
    const data = JSON.parse(await readFile(filename, "utf8"));
    if (data?.summary?.completed) return null;
    if (!trenchesConfigMatches(data?.config, options)) return null;
    if (!contiguousPrefixEnd(data?.ranges, options.minMarketCap, options.maxMarketCap)) return null;
    return data;
  } catch {
    return null;
  }
}

async function restoreMintState(filename, allMints, trenchesMints) {
  let restored = 0;

  try {
    const input = createReadStream(filename, { encoding: "utf8" });
    const lines = createInterface({ input, crlfDelay: Infinity });

    for await (const line of lines) {
      if (!line.trim()) continue;

      let record;
      try {
        record = JSON.parse(line);
      } catch {
        continue;
      }

      const mint = record?.mint_address;
      if (!mint) continue;

      allMints.add(mint);
      if (record.source === "trenches") trenchesMints.add(mint);
      restored++;
    }

    return { exists: true, restored };
  } catch (error) {
    if (error?.code === "ENOENT") return { exists: false, restored: 0 };
    throw error;
  }
}

async function runTrenchesCollector(options, apiKey) {
  await Promise.all([ensureParent(options.out), ensureParent(options.mintsOut)]);

  const partialFile = `${options.out}.partial`;
  const partialMintsFile = `${options.mintsOut}.partial`;

  if (options.cold) {
    await Promise.all([
      unlink(partialFile).catch(() => {}),
      unlink(partialMintsFile).catch(() => {}),
    ]);
  }

  const gate = new RequestGate(options.rps);
  const allMints = new Set();
  const trenchesMints = new Set();
  const feeFieldsSeen = new Set();
  const pendingMintRecords = [];

  let resumeOutput = options.cold
    ? null
    : await loadPartialTrenchesOutput(partialFile, options);

  let resumePrefix = null;

  if (resumeOutput) {
    const restored = await restoreMintState(partialMintsFile, allMints, trenchesMints);

    if (!restored.exists) {
      console.warn("Partial-Metadaten gefunden, aber Mint-Partial fehlt. Resume wird verworfen und neu gestartet.");
      resumeOutput = null;
    } else {
      resumePrefix = contiguousPrefixEnd(
        resumeOutput.ranges,
        options.minMarketCap,
        options.maxMarketCap,
      );

      console.log(
        `Resume: ${restored.restored} Mint-Records wiederhergestellt | Cursor=${displayCap(resumePrefix?.cursor ?? null)}`,
      );
    }
  }

  if (!resumeOutput) await writeFile(partialMintsFile, "", "utf8");

  const startedAt = Date.now();
  const elapsedBeforeResume = Number(resumeOutput?.summary?.elapsed_ms ?? 0);
  const runId = resumeOutput?.generated_at ?? new Date(startedAt).toISOString();
  let queryCounter = Array.isArray(resumeOutput?.queries) ? resumeOutput.queries.length : 0;
  let stopped = false;
  let interrupted = false;

  const output = resumeOutput ?? {
    generated_at: runId,
    updated_at: runId,
    config: {
      algorithm: "adaptive-marketcap-js-v10",
      chain: "sol",
      source: "market trenches",
      scan_mode: options.mode,
      range_dimension: "market_cap",
      min_marketcap: options.minMarketCap,
      max_marketcap: options.maxMarketCap,
      max_created: options.maxCreated,
      min_created: options.minCreated,
      min_total_fee: options.minTotalFee,
      rps: options.rps,
      concurrency: options.concurrency,
      start_width_marketcap: options.startWidth,
    },
    data: {
      format: "jsonl",
      path: options.mintsOut,
      partial_path: partialMintsFile,
      identity: "mint_address",
      record_policy: "first_complete_observation_per_mint",
    },
    summary: {
      execution_mode: null,
      resumed: false,
      stop_reason: null,
      queries: 0,
      successful_queries: 0,
      failed_queries: 0,
      unique_mints: 0,
      trenches_unique_mints: 0,
      trenches_repeated_across_ranges: 0,
      accepted_ranges: 0,
      elapsed_ms: 0,
      effective_rps: 0,
      stopped_by_rate_limit: false,
      unresolved: false,
      completed: false,
    },
    fee_fields_seen: [],
    ranges: [],
    queries: [],
  };

  output.config.algorithm = "adaptive-marketcap-js-v10";
  output.config.rps = options.rps;
  output.config.concurrency = options.concurrency;
  output.config.start_width_marketcap = options.startWidth;
  output.data.path = options.mintsOut;
  output.data.partial_path = partialMintsFile;
  output.summary.resumed = Boolean(resumeOutput);
  output.summary.stop_reason = null;
  output.summary.stopped_by_rate_limit = false;
  output.summary.unresolved = false;
  output.summary.completed = false;
  output.queries ??= [];
  output.ranges ??= [];

  for (const field of output.fee_fields_seen ?? []) feeFieldsSeen.add(field);

  function requestGracefulStop(signal) {
    if (interrupted) return;
    interrupted = true;
    stopped = true;
    output.summary.stop_reason = signal;
    console.log(`\n${signal} empfangen: laufenden Request abschließen, Mints flushen und Partial-State speichern …`);
  }

  const onSigint = () => requestGracefulStop("SIGINT");
  const onSigterm = () => requestGracefulStop("SIGTERM");
  process.on("SIGINT", onSigint);
  process.on("SIGTERM", onSigterm);

  function updateSummary() {
    output.updated_at = new Date().toISOString();
    output.summary.queries = output.queries.length;
    output.summary.unique_mints = allMints.size;
    output.summary.trenches_unique_mints = trenchesMints.size;
    output.summary.accepted_ranges = output.ranges.length;
    output.summary.elapsed_ms = elapsedBeforeResume + (Date.now() - startedAt);
    output.summary.effective_rps = output.summary.elapsed_ms
      ? Number((output.summary.queries / (output.summary.elapsed_ms / 1000)).toFixed(2))
      : 0;
    output.fee_fields_seen = [...feeFieldsSeen].sort();
    output.ranges.sort((a, b) => a.min_marketcap - b.min_marketcap);
  }

  async function save(filename) {
    updateSummary();
    await writeJsonAtomic(filename, output);
  }

  async function checkpoint() {
    if (output.queries.length % PARTIAL_SAVE_EVERY === 0) await save(partialFile);
  }

  function queueMint(mint, record) {
    if (!mint || allMints.has(mint)) return false;

    allMints.add(mint);
    pendingMintRecords.push({
      run_id: runId,
      collected_at: new Date().toISOString(),
      mint_address: mint,
      ...record,
    });

    return true;
  }

  async function flushMints() {
    if (!pendingMintRecords.length) return;

    const records = pendingMintRecords.splice(0, pendingMintRecords.length);
    await appendFile(
      partialMintsFile,
      `${records.map(JSON.stringify).join("\n")}\n`,
      "utf8",
    );
  }

  async function commit() {
    await flushMints();
    await replaceFile(partialMintsFile, options.mintsOut);
    output.summary.completed = true;
    output.summary.stop_reason = null;
    await save(options.out);
    await unlink(partialFile).catch(() => {});
  }

  async function executeProbe(min, max, purpose, command) {
    if (stopped) return null;

    await gate.wait();
    if (stopped) return null;

    const id = `q${String(++queryCounter).padStart(4, "0")}`;
    console.log(`${id} | trenches | ${purpose} | mc ${min} - ${displayCap(max)}`);

    const requestStartedAt = Date.now();
    const result = await runGmgn(command, apiKey);
    const durationMs = Date.now() - requestStartedAt;

    if (!result.ok) {
      output.summary.failed_queries++;
      output.summary.unresolved = true;
      output.summary.stopped_by_rate_limit = result.rateLimited;
      output.queries.push({
        id,
        source: "trenches",
        purpose,
        min_marketcap: min,
        max_marketcap: max,
        max_created: options.maxCreated,
        min_created: options.minCreated,
        min_total_fee: options.minTotalFee,
        status: "error",
        duration_ms: durationMs,
        error: result.error,
      });

      stopped = true;
      output.summary.stop_reason = interrupted
        ? output.summary.stop_reason
        : (result.rateLimited ? "rate_limit" : "request_error");

      await flushMints();
      await save(partialFile);
      return null;
    }

    const processed = summarizeTrenchesResponse(result.data);
    const record = {
      id,
      source: "trenches",
      purpose,
      min_marketcap: min,
      max_marketcap: max,
      max_created: options.maxCreated,
      min_created: options.minCreated,
      min_total_fee: options.minTotalFee,
      status: "ok",
      duration_ms: durationMs,
      bucket_counts: processed.bucketCounts,
      max_bucket: processed.maxBucket,
      raw_records: processed.rawRecords,
      unique_mints: processed.uniqueMints,
      duplicate_records: processed.duplicateRecords,
      saturated: processed.saturated,
    };

    output.queries.push(record);
    output.summary.successful_queries++;

    await flushMints();
    await checkpoint();

    console.log(
      `    load=${processed.maxBucket} | unique=${processed.uniqueMints}` +
      ` | saturated=${processed.saturated} | ${durationMs}ms`,
    );

    return {
      record,
      min,
      max,
      width: widthOf(min, max),
      load: processed.maxBucket,
      uniqueMints: processed.uniqueMints,
      saturated: processed.saturated,
      payload: { entries: processed.entries },
    };
  }

  async function probeRange(min, max, purpose) {
    const parts = [
      "gmgn-cli market trenches",
      "--chain sol",
      `--limit ${TRENCHES.limit}`,
      `--min-marketcap ${min}`,
      `--min-total-fee ${options.minTotalFee}`,
    ];

    if (max !== null) parts.push(`--max-marketcap ${max}`);
    if (options.maxCreated) parts.push(`--max-created ${options.maxCreated}`);
    if (options.minCreated) parts.push(`--min-created ${options.minCreated}`);
    parts.push("--raw");

    return executeProbe(min, max, purpose, parts.join(" "));
  }

  async function acceptRange(result) {
    const grouped = new Map();

    for (const { token, bucket } of result.payload?.entries ?? []) {
      if (!token?.address) continue;

      const group = grouped.get(token.address) ?? [];
      group.push({ bucket, data: token });
      grouped.set(token.address, group);
      Object.keys(extractFeeFields(token)).forEach(field => feeFieldsSeen.add(field));
    }

    let newUniqueMints = 0;
    let repeatedUniqueMints = 0;

    for (const [mint, records] of grouped) {
      if (trenchesMints.has(mint)) repeatedUniqueMints++;
      else newUniqueMints++;

      trenchesMints.add(mint);
      const first = records[0]?.data ?? {};

      queueMint(mint, {
        source: "trenches",
        first_query: result.record.id,
        market_cap: first.market_cap ?? first.usd_market_cap ?? null,
        launchpad_platform: first.launchpad_platform ?? null,
        created_timestamp: first.created_timestamp ?? null,
        open_timestamp: first.open_timestamp ?? null,
        complete_timestamp: first.complete_timestamp ?? null,
        raw_records: records,
      });
    }

    await flushMints();

    output.summary.trenches_repeated_across_ranges += repeatedUniqueMints;
    output.ranges.push({
      min_marketcap: result.min,
      max_marketcap: result.max,
      width: result.width,
      min_total_fee: options.minTotalFee,
      max_bucket: result.load,
      raw_records: result.record.raw_records ?? null,
      unique_mints: grouped.size,
      new_unique_mints: newUniqueMints,
      repeated_unique_mints: repeatedUniqueMints,
      cumulative_unique_mints: trenchesMints.size,
      duplicate_records_within_query: result.record.duplicate_records ?? null,
      density: result.width > 0 ? result.load / result.width : null,
      query: result.record.id,
    });

    console.log(
      `    ACCEPT trenches ${result.min} - ${displayCap(result.max)}` +
      ` | load=${result.load} | unique=${grouped.size} | new=${newUniqueMints}` +
      ` | repeat=${repeatedUniqueMints} | cumulative=${trenchesMints.size}`,
    );
  }

  function growthFactor(count) {
    for (const [max, factor] of TRENCHES.growth) {
      if (count <= max) return factor;
    }
    return clamp(TRENCHES.target / count, 1.03, 1.15);
  }

  function predictWidth(result) {
    if (result.width === null) return null;
    if (result.load <= 0) return clean(Math.max(MIN_WIDTH, result.width * 8));

    const densityGrowth = TRENCHES.target / result.load;
    return clean(
      Math.max(
        MIN_WIDTH,
        result.width * clamp(Math.max(densityGrowth, growthFactor(result.load)), 1.03, 8),
      ),
    );
  }

  async function findWindow(start, widthHint, hardEnd = null, purpose = "adaptive") {
    let width = Math.max(MIN_WIDTH, widthHint);
    let bestSafe = null;
    let safeWidth = null;
    let saturatedWidth = null;

    for (let attempt = 0; attempt < MAX_ADJUSTMENTS; attempt++) {
      if (hardEnd !== null) width = Math.min(width, hardEnd - start);
      if (width < MIN_WIDTH) break;

      const end = clean(start + width);
      if (end <= start) break;

      const result = await probeRange(start, end, purpose);
      if (!result) return null;

      if (result.saturated) {
        saturatedWidth = result.width;

        if (saturatedWidth <= MIN_WIDTH) {
          console.error(`Range nicht weiter teilbar: market cap ${start} - ${end} bleibt saturated.`);
          return null;
        }

        width = safeWidth === null
          ? clean(result.width / 2)
          : clean((safeWidth + saturatedWidth) / 2);
        continue;
      }

      bestSafe = result;
      safeWidth = result.width;

      if (
        result.load >= TRENCHES.targetMin ||
        (hardEnd !== null && (end >= hardEnd || sameNumber(end, hardEnd)))
      ) {
        return result;
      }

      if (saturatedWidth !== null && saturatedWidth - safeWidth <= MIN_WIDTH) return bestSafe;

      width = saturatedWidth !== null
        ? clean((safeWidth + saturatedWidth) / 2)
        : (predictWidth(result) ?? width);
    }

    return bestSafe;
  }

  async function repairSegment(start, end, widthHint) {
    const repaired = [];
    let cursor = start;
    let width = Math.max(MIN_WIDTH, widthHint);

    while (cursor < end && !sameNumber(cursor, end) && !stopped) {
      const result = await findWindow(cursor, width, end, "repair");
      if (!result || result.max === null) return null;

      repaired.push(result);
      cursor = result.max;
      width = predictWidth(result) ?? width;
    }

    return repaired;
  }

  async function scanRange(start, initialWidth, hardEnd = null, initialTailCheck = true) {
    let cursor = start;
    let width = initialWidth;

    if (hardEnd !== null) {
      while (cursor < hardEnd && !sameNumber(cursor, hardEnd) && !stopped) {
        const result = await findWindow(cursor, width, hardEnd);
        if (!result || result.max === null) return false;

        await acceptRange(result);
        cursor = result.max;
        width = predictWidth(result) ?? width;
      }

      return !stopped && (cursor >= hardEnd || sameNumber(cursor, hardEnd));
    }

    let acceptedSinceTail = 0;
    let previousWidth = null;

    if (initialTailCheck) {
      const tail = await probeRange(cursor, null, "tail_probe");
      if (!tail) return false;
      if (!tail.saturated) {
        await acceptRange(tail);
        return true;
      }
    }

    while (!stopped) {
      const result = await findWindow(cursor, width);
      if (!result || result.max === null) return false;

      await acceptRange(result);
      cursor = result.max;

      const currentWidth = result.width;
      width = predictWidth(result) ?? width;
      acceptedSinceTail++;

      const widthJump = previousWidth !== null && currentWidth !== null
        ? currentWidth / previousWidth
        : 1;

      previousWidth = currentWidth;

      if (
        acceptedSinceTail < TAIL_CHECK_EVERY &&
        widthJump < TAIL_WIDTH_GROWTH_TRIGGER
      ) {
        continue;
      }

      const tail = await probeRange(cursor, null, "tail_probe");
      if (!tail) return false;
      if (!tail.saturated) {
        await acceptRange(tail);
        return true;
      }

      acceptedSinceTail = 0;
    }

    return false;
  }

  async function warmStart(previousRanges) {
    console.log(`Warm-Start trenches: ${previousRanges.length} gelernte Ranges`);
    const results = [];

    for (const range of previousRanges) {
      const result = await probeRange(range.min, range.max, "warm_probe");
      if (!result) return false;
      results.push(result);
    }

    for (let i = 0; i < results.length && !stopped;) {
      const current = results[i];
      const next = results[i + 1] ?? null;

      if (current.max === null) {
        if (!current.saturated) {
          await acceptRange(current);
          return true;
        }

        const hint = results[Math.max(0, i - 1)]?.width ?? options.startWidth;
        return scanRange(current.min, hint, null, false);
      }

      if (current.saturated) {
        console.log(`REPAIR trenches saturated ${current.min} - ${current.max}`);
        const repaired = await repairSegment(current.min, current.max, current.width * 0.7);
        if (!repaired) return false;
        for (const result of repaired) await acceptRange(result);
        i++;
        continue;
      }

      if (current.load < TRENCHES.mergeThreshold && next && !next.saturated) {
        const merged = await probeRange(current.min, next.max, "merge_probe");
        if (!merged) return false;

        if (!merged.saturated) {
          await acceptRange(merged);
          i += 2;
          if (merged.max === null) return true;
          continue;
        }
      }

      await acceptRange(current);
      i++;
    }

    return !stopped;
  }

  const previousRanges = resumeOutput || options.cold
    ? null
    : await loadPreviousTrenchesState(options.out, options);

  output.summary.execution_mode = resumeOutput
    ? "resume"
    : (previousRanges ? "warm" : "cold");

  console.log("\n=== SOURCE: TRENCHES ===");

  let success;

  if (resumeOutput) {
    const cursor = resumePrefix?.cursor ?? options.minMarketCap;

    if (resumePrefix?.complete) {
      success = true;
    } else {
      const lastWidth = Number(output.ranges.at(-1)?.width);
      const widthHint = Number.isFinite(lastWidth) && lastWidth > 0
        ? lastWidth
        : options.startWidth;

      console.log(`Resume Trenches ab market cap ${displayCap(cursor)}`);
      success = await scanRange(cursor, widthHint, options.maxMarketCap, true);
    }
  } else if (previousRanges) {
    success = await warmStart(previousRanges);
  } else {
    success = await scanRange(
      options.minMarketCap,
      options.startWidth,
      options.maxMarketCap,
      true,
    );
  }

  if (
    success &&
    !stopped &&
    !normalizeRanges(output.ranges, options.minMarketCap, options.maxMarketCap)
  ) {
    output.summary.unresolved = true;
    success = false;
    console.error("Coverage-Fehler bei Trenches.");
  }

  await flushMints();

  if (success && !stopped && !output.summary.unresolved) {
    await commit();
  } else {
    await save(partialFile);
  }

  updateSummary();
  process.off("SIGINT", onSigint);
  process.off("SIGTERM", onSigterm);

  if (interrupted) process.exitCode = 130;

  console.log("\n========================================");
  console.log(interrupted ? "GESTOPPT UND GESPEICHERT" : "FERTIG");
  console.log("========================================");
  console.log(`Scan: ${options.mode} | execution=${output.summary.execution_mode}`);
  console.log(`Market Cap: ${options.minMarketCap} - ${displayCap(options.maxMarketCap)}`);
  console.log(`Created filter: min=${options.minCreated ?? "-"} | max=${options.maxCreated ?? "-"}`);
  console.log(`Requests: ${output.summary.queries}`);
  console.log(`Successful: ${output.summary.successful_queries}`);
  console.log(`Failed: ${output.summary.failed_queries}`);
  console.log(`Trenches Mints: ${output.summary.trenches_unique_mints}`);
  console.log(`Repeats across accepted ranges: ${output.summary.trenches_repeated_across_ranges}`);
  console.log(`Accepted Ranges: ${output.summary.accepted_ranges}`);
  console.log(`Elapsed: ${(output.summary.elapsed_ms / 1000).toFixed(2)}s`);
  console.log(`Effective rate: ${output.summary.effective_rps} req/s`);
  console.log(`429: ${output.summary.stopped_by_rate_limit}`);
  console.log(`Stop reason: ${output.summary.stop_reason ?? "-"}`);
  console.log(`Unresolved: ${output.summary.unresolved}`);
  console.log(`Completed: ${output.summary.completed}`);
  console.log(`Metadata: ${output.summary.completed ? options.out : partialFile}`);
  console.log(`Mint data: ${output.summary.completed ? options.mintsOut : partialMintsFile}`);
}

// ============================================================
// Main
// ============================================================

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const apiKey = await loadApiKey();

  console.log("\nGMGN Adaptive Collector");
  console.log(`Mode: ${options.mode}`);

  if (options.mode === "signal-live") {
    await runSignalLive(options, apiKey);
    return;
  }

  if (options.mode === "signal-full") {
    await runSignalFull(options, apiKey);
    return;
  }

  console.log(`Market Cap range: $${options.minMarketCap} - ${displayCap(options.maxMarketCap)}`);
  console.log(`Created filter: min=${options.minCreated ?? "-"} | max=${options.maxCreated ?? "-"}`);
  console.log(`Total Fee filter >= ${options.minTotalFee}`);
  console.log(`Trenches: limit=${TRENCHES.limit} | target=${TRENCHES.targetMin}-${TRENCHES.limit - 1}`);
  console.log(`Rate: max ${options.rps} req/s`);
  console.log(`Metadata: ${options.out}`);
  console.log(`Mint data: ${options.mintsOut}\n`);

  await runTrenchesCollector(options, apiKey);
}

main().catch(error => {
  console.error(error?.stack || error?.message || error);
  process.exitCode = 1;
});