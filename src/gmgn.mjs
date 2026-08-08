import { exec } from "node:child_process";
import { appendFile, mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { promisify } from "node:util";

const execAsync = promisify(exec);

const DEFAULTS = {
  minMarketCap: 2000,
  maxMarketCap: 2010,
  minTotalFee: 0.01,
  rps: 20,
  concurrency: 1,
  startWidth: 10_000,
  out: "data/gmgn_adaptive_marketcap.json",
  mintsOut: "data/gmgn_mints.jsonl",
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

const SIGNAL = {
  limit: 50,
  target: 47,
  targetMin: 44,
  mergeThreshold: 30,
  growth: [
    [0, 8], [12, 4], [25, 2.5], [34, 2], [41, 1.6], [44, 1.4], [46, 1.2],
  ],
};

const SIGNAL_TYPES = [...Array.from({ length: 13 }, (_, i) => i + 1), 17, 18, 19, 20, 21];
const ENABLE_SIGNALS = false;
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

function parseArgs(argv) {
  const options = { ...DEFAULTS, cold: false };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--probe") continue;
    if (arg === "--cold") options.cold = true;
    else if (arg === "--min-marketcap") options.minMarketCap = readNumber(argv, i++, arg);
    else if (arg === "--max-marketcap") options.maxMarketCap = readNumber(argv, i++, arg);
    else if (arg === "--min-total-fee") options.minTotalFee = readNumber(argv, i++, arg);
    else if (arg === "--rps") options.rps = readNumber(argv, i++, arg);
    else if (arg === "--concurrency") options.concurrency = readNumber(argv, i++, arg);
    else if (arg === "--start-width") options.startWidth = readNumber(argv, i++, arg);
    else if (arg === "--out") options.out = argv[++i];
    else if (arg === "--mints-out") options.mintsOut = argv[++i];
    else throw new Error(`Unbekanntes Argument: ${arg}`);
  }

  if (!Number.isFinite(options.minMarketCap) || options.minMarketCap < 0) throw new Error("--min-marketcap ist ungültig");
  if (options.maxMarketCap !== null && (!Number.isFinite(options.maxMarketCap) || options.maxMarketCap <= options.minMarketCap)) {
    throw new Error("--max-marketcap muss größer als --min-marketcap sein");
  }
  if (!Number.isFinite(options.minTotalFee) || options.minTotalFee < 0) throw new Error("--min-total-fee ist ungültig");
  if (!Number.isFinite(options.rps) || options.rps <= 0) throw new Error("--rps ist ungültig");
  if (!Number.isInteger(options.concurrency) || options.concurrency <= 0) throw new Error("--concurrency ist ungültig");
  if (!Number.isFinite(options.startWidth) || options.startWidth <= 0) throw new Error("--start-width ist ungültig");
  if (!options.out || !options.mintsOut) throw new Error("Output-Pfade dürfen nicht leer sein");
  if (resolve(options.out) === resolve(options.mintsOut)) throw new Error("--out und --mints-out müssen unterschiedliche Dateien sein");

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
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (!value) throw new Error("GMGN_API_KEY ist leer");
    return value;
  }
  throw new Error("GMGN_API_KEY fehlt in .env");
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

async function runGmgn(command, apiKey) {
  try {
    const { stdout } = await execAsync(command, {
      windowsHide: true,
      env: {
        ...process.env,
        GMGN_API_KEY: apiKey,
        GMGN_RATE_LIMIT_AUTO_RETRY_MAX_WAIT_MS: "0",
      },
      maxBuffer: 20 * 1024 * 1024,
    });

    return { ok: true, rateLimited: false, data: JSON.parse(stdout.trim()), error: null };
  } catch (error) {
    const message = [error?.stderr, error?.stdout, error?.message].filter(Boolean).join(" ").trim();
    return {
      ok: false,
      rateLimited: /HTTP 429|RATE_LIMIT_EXCEEDED|RATE_LIMIT_BANNED/i.test(message),
      data: null,
      error: message,
    };
  }
}

// ============================================================
// Response helpers
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
    if (/fee|tip|tax|royalty/i.test(key)) {
      result[current] = child;
    } else if (child && typeof child === "object") {
      extractFeeFields(child, current, result);
    }
  }
  return result;
}

function summarizeTrenchesResponse(data) {
  const bucketCounts = {};
  const localMints = new Set();
  const entries = [];
  let rawRecords = 0;

  if (!data || typeof data !== "object") {
    return { bucketCounts, maxBucket: 0, rawRecords: 0, uniqueMints: 0, duplicateRecords: 0, saturated: false, entries };
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

function collectSignalEvents(value, result = [], seen = new Set()) {
  if (value == null) return result;

  if (Array.isArray(value)) {
    value.forEach(item => collectSignalEvents(item, result, seen));
    return result;
  }

  if (typeof value !== "object") return result;

  if (typeof value.token_address === "string") {
    const key = value.id ?? (`${value.token_address}:${value.signal_type ?? ""}:${value.trigger_at ?? ""}`);
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
// Previous state
// ============================================================

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
  if (!Array.isArray(ranges) || !ranges.length) return null;

  const normalized = ranges.map(range => {
    const rawMin = Object.hasOwn(range, "min_marketcap") ? range.min_marketcap : range.min;
    const rawMax = Object.hasOwn(range, "max_marketcap") ? range.max_marketcap : range.max;
    return { min: Number(rawMin), max: rawMax === null ? null : Number(rawMax) };
  })
  .filter(range => Number.isFinite(range.min) && (range.max === null || Number.isFinite(range.max)))
  .sort((a, b) => a.min - b.min);

  return (normalized.length && hasCompleteCoverage(normalized, startMarketCap, endMarketCap)) ? normalized : null;
}

async function loadPreviousState(filename, options) {
  try {
    const data = JSON.parse(await readFile(filename, "utf8"));
    const config = data?.config ?? {};
    const savedMax = config.max_marketcap ?? null;
    const sameMax = savedMax === null ? options.maxMarketCap === null : (options.maxMarketCap !== null && sameNumber(Number(savedMax), options.maxMarketCap));

    if (config.range_dimension !== "market_cap" || Number(config.min_marketcap) !== Number(options.minMarketCap) || Number(config.min_total_fee) !== Number(options.minTotalFee) || !sameMax) {
      return { trenches: null, signals: {} };
    }

    const signals = {};
    for (const type of SIGNAL_TYPES) {
      const ranges = normalizeRanges(data?.signals?.ranges_by_type?.[type], options.minMarketCap, options.maxMarketCap);
      if (ranges) signals[type] = ranges;
    }

    return {
      trenches: normalizeRanges(data?.ranges, options.minMarketCap, options.maxMarketCap),
      signals,
    };
  } catch {
    return { trenches: null, signals: {} };
  }
}

// ============================================================
// Collector
// ============================================================

async function runCollector(options, apiKey) {
  await Promise.all([ensureParent(options.out), ensureParent(options.mintsOut)]);

  const gate = new RequestGate(options.rps);
  const allMints = new Set();
  const trenchesMints = new Set();
  const signalRawMints = new Set();
  const signalMints = new Set();
  const feeFieldsSeen = new Set();
  const pendingMintRecords = [];
  const partialFile = `${options.out}.partial`;
  const partialMintsFile = `${options.mintsOut}.partial`;
  const startedAt = Date.now();
  const runId = new Date(startedAt).toISOString();
  let queryCounter = 0;
  let stopped = false;

  await writeFile(partialMintsFile, "", "utf8");

  const output = {
    generated_at: runId,
    updated_at: runId,
    config: {
      algorithm: "adaptive-marketcap-js-v8",
      chain: "sol",
      sources: ENABLE_SIGNALS ? ["market trenches", "market signal"] : ["market trenches"],
      enable_signals: ENABLE_SIGNALS,
      range_dimension: "market_cap",
      min_marketcap: options.minMarketCap,
      max_marketcap: options.maxMarketCap,
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
      mode: null, trenches_mode: null, signals_mode: null,
      queries: 0, successful_queries: 0, failed_queries: 0,
      unique_mints: 0, trenches_unique_mints: 0, trenches_repeated_across_ranges: 0,
      signal_raw_unique_mints: 0, signal_unique_mints: 0, overlap_unique_mints: 0,
      accepted_ranges: 0, accepted_signal_ranges: 0,
      elapsed_ms: 0, effective_rps: 0,
      stopped_by_rate_limit: false, unresolved: false, completed: false,
    },
    fee_fields_seen: [],
    ranges: [],
    signals: {
      enabled: ENABLE_SIGNALS,
      signal_types: SIGNAL_TYPES,
      excluded_explicit_types: [14, 15, 16],
      range_dimension: "market_cap",
      min_total_fee: options.minTotalFee,
      ranges_by_type: {},
    },
    queries: [],
  };

  // State and persistence
  function updateSummary() {
    output.updated_at = new Date().toISOString();
    output.summary.queries = output.queries.length;
    output.summary.unique_mints = allMints.size;
    output.summary.trenches_unique_mints = trenchesMints.size;
    output.summary.signal_raw_unique_mints = signalRawMints.size;
    output.summary.signal_unique_mints = signalMints.size;
    output.summary.overlap_unique_mints = [...signalMints].filter(mint => trenchesMints.has(mint)).length;
    output.summary.accepted_ranges = output.ranges.length;
    output.summary.accepted_signal_ranges = Object.values(output.signals.ranges_by_type).reduce((sum, ranges) => sum + ranges.length, 0);
    output.summary.elapsed_ms = Date.now() - startedAt;
    output.summary.effective_rps = output.summary.elapsed_ms ? Number((output.summary.queries / (output.summary.elapsed_ms / 1000)).toFixed(2)) : 0;
    output.fee_fields_seen = [...feeFieldsSeen].sort();
    output.ranges.sort((a, b) => a.min_marketcap - b.min_marketcap);
  }

  async function save(filename) {
    updateSummary();
    await writeFile(filename, JSON.stringify(output, null, 2), "utf8");
  }

  async function checkpoint() {
    if (output.queries.length % PARTIAL_SAVE_EVERY === 0) await save(partialFile);
  }

  async function commit() {
    await flushMints();
    try {
      await rename(partialMintsFile, options.mintsOut);
    } catch (error) {
      if (!["EEXIST", "EPERM"].includes(error?.code)) throw error;
      await unlink(options.mintsOut).catch(() => {});
      await rename(partialMintsFile, options.mintsOut);
    }
    output.summary.completed = true;
    await save(options.out);
    await unlink(partialFile).catch(() => {});
  }

  function queueMint(mint, record) {
    if (!mint || allMints.has(mint)) return false;
    allMints.add(mint);
    pendingMintRecords.push({ run_id: runId, collected_at: new Date().toISOString(), mint_address: mint, ...record });
    return true;
  }

  async function flushMints() {
    if (!pendingMintRecords.length) return;
    const records = pendingMintRecords.splice(0, pendingMintRecords.length);
    const lines = records.map(JSON.stringify).join("\n");
    await appendFile(partialMintsFile, `${lines}\n`, "utf8");
  }

  // Signal storage
  function rememberSignalEvent(event, queryId, signalType) {
    if (!event.token_address) return false;
    signalRawMints.add(event.token_address);

    const marketCap = Number(event.market_cap ?? event.cur_data?.market_cap ?? event.data?.market_cap);
    if (!Number.isFinite(marketCap) || marketCap < options.minMarketCap || (options.maxMarketCap !== null && marketCap > options.maxMarketCap)) return false;

    signalMints.add(event.token_address);
    Object.keys(extractFeeFields(event)).forEach(field => feeFieldsSeen.add(field));

    queueMint(event.token_address, {
      source: "signal",
      first_query: queryId,
      signal_type: signalType,
      market_cap: marketCap,
      raw_records: [event],
    });
    return true;
  }

  // Shared query execution
  async function executeProbe(source, min, max, purpose, command, processResponse) {
    if (stopped) return null;
    await gate.wait();

    const id = `q${String(++queryCounter).padStart(4, "0")}`;
    console.log(`${id} | ${source} | ${purpose} | mc ${min} - ${displayCap(max)}`);
    
    const requestStartedAt = Date.now();
    const result = await runGmgn(command, apiKey);
    const durationMs = Date.now() - requestStartedAt;

    if (!result.ok) {
      output.summary.failed_queries++;
      output.summary.unresolved = true;
      output.summary.stopped_by_rate_limit = result.rateLimited;
      
      output.queries.push({
        id, source, purpose, min_marketcap: min, max_marketcap: max,
        min_total_fee: options.minTotalFee, status: "error",
        duration_ms: durationMs, error: result.error,
      });
      
      stopped = true;
      await flushMints();
      await save(partialFile);
      return null;
    }

    const processed = processResponse(result.data, id);
    const record = {
      id, source, purpose, min_marketcap: min, max_marketcap: max,
      min_total_fee: options.minTotalFee, status: "ok", duration_ms: durationMs,
      ...processed.record,
    };

    output.queries.push(record);
    output.summary.successful_queries++;
    
    await flushMints();
    await checkpoint();
    
    console.log(`    load=${processed.load} | unique=${processed.uniqueMints} | saturated=${processed.saturated} | ${durationMs}ms`);

    return {
      record, min, max, width: widthOf(min, max),
      load: processed.load, uniqueMints: processed.uniqueMints,
      saturated: processed.saturated, payload: processed.payload ?? null,
    };
  }

  // Trenches endpoint
  async function probeTrenchesRange(min, max, purpose) {
    const parts = [
      "gmgn-cli", "market", "trenches", "--chain", "sol",
      "--limit", String(TRENCHES.limit), "--min-marketcap", String(min),
      "--min-total-fee", String(options.minTotalFee),
    ];
    if (max !== null) parts.push("--max-marketcap", String(max));
    parts.push("--raw");

    return executeProbe("trenches", min, max, purpose, parts.join(" "), data => {
      const processed = summarizeTrenchesResponse(data);
      return {
        load: processed.maxBucket,
        uniqueMints: processed.uniqueMints,
        saturated: processed.saturated,
        payload: { entries: processed.entries },
        record: {
          bucket_counts: processed.bucketCounts,
          max_bucket: processed.maxBucket,
          raw_records: processed.rawRecords,
          unique_mints: processed.uniqueMints,
          duplicate_records: processed.duplicateRecords,
          saturated: processed.saturated,
        },
      };
    });
  }

  // Signal endpoint
  async function probeSignalRange(signalType, min, max, purpose) {
    const parts = [
      "gmgn-cli", "market", "signal", "--chain", "sol",
      "--signal-type", String(signalType), "--mc-min", String(min),
      "--total-fee-min", String(options.minTotalFee),
    ];
    if (max !== null) parts.push("--mc-max", String(max));
    parts.push("--raw");

    return executeProbe(`signal:${signalType}`, min, max, purpose, parts.join(" "), (data, id) => {
      const events = collectSignalEvents(data);
      const eligibleMints = new Set();
      let eligibleEvents = 0;

      for (const event of events) {
        if (!rememberSignalEvent(event, id, signalType)) continue;
        eligibleEvents++;
        eligibleMints.add(event.token_address);
      }

      return {
        load: events.length,
        uniqueMints: eligibleMints.size,
        saturated: events.length >= SIGNAL.limit,
        record: {
          signal_type: signalType,
          raw_events: events.length,
          eligible_events: eligibleEvents,
          eligible_unique_mints: eligibleMints.size,
          saturated: events.length >= SIGNAL.limit,
        },
      };
    });
  }

  // Accepted results
  async function acceptTrenches(result) {
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

      queueMint(mint, {
        source: "trenches",
        first_query: result.record.id,
        market_cap: records[0]?.data?.market_cap ?? records[0]?.data?.usd_market_cap ?? null,
        launchpad_platform: records[0]?.data?.launchpad_platform ?? null,
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

    console.log(`    ACCEPT trenches ${result.min} - ${displayCap(result.max)} | load=${result.load} | unique=${grouped.size} | new=${newUniqueMints} | repeat=${repeatedUniqueMints} | cumulative=${trenchesMints.size}`);
  }

  async function acceptSignal(signalType, result) {
    const key = String(signalType);
    output.signals.ranges_by_type[key] ??= [];
    
    output.signals.ranges_by_type[key].push({
      min_marketcap: result.min, max_marketcap: result.max,
      width: result.width, min_total_fee: options.minTotalFee,
      raw_events: result.load, eligible_unique_mints: result.uniqueMints,
      query: result.record.id,
    });
    
    output.signals.ranges_by_type[key].sort((a, b) => a.min_marketcap - b.min_marketcap);
    console.log(`    ACCEPT signal:${signalType} ${result.min} - ${displayCap(result.max)} | raw=${result.load} | eligible=${result.uniqueMints}`);
  }

  // Adaptive range algorithm
  function growthFactor(count, profile) {
    for (const [max, factor] of profile.growth) {
      if (count <= max) return factor;
    }
    return clamp(profile.target / count, 1.03, 1.15);
  }

  function predictWidth(result, profile) {
    if (result.width === null) return null;
    if (result.load <= 0) return clean(Math.max(MIN_WIDTH, result.width * 8));
    const densityGrowth = profile.target / result.load;
    return clean(Math.max(MIN_WIDTH, result.width * clamp(Math.max(densityGrowth, growthFactor(result.load, profile)), 1.03, 8)));
  }

  async function findWindow(source, start, widthHint, hardEnd = null, purpose = "adaptive") {
    let width = Math.max(MIN_WIDTH, widthHint);
    let bestSafe = null;
    let safeWidth = null;
    let saturatedWidth = null;

    for (let attempt = 0; attempt < MAX_ADJUSTMENTS; attempt++) {
      if (hardEnd !== null) width = Math.min(width, hardEnd - start);
      if (width < MIN_WIDTH) break;

      const end = clean(start + width);
      if (end <= start) break;

      const result = await source.probe(start, end, purpose);
      if (!result) return null;

      if (result.saturated) {
        saturatedWidth = result.width;
        if (saturatedWidth <= MIN_WIDTH) {
          console.error(`Range nicht weiter teilbar: market cap ${start} - ${end} bleibt saturated.`);
          return null;
        }
        width = safeWidth === null ? clean(result.width / 2) : clean((safeWidth + saturatedWidth) / 2);
        continue;
      }

      bestSafe = result;
      safeWidth = result.width;

      if (result.load >= source.profile.targetMin || (hardEnd !== null && (end >= hardEnd || sameNumber(end, hardEnd)))) return result;
      if (saturatedWidth !== null && saturatedWidth - safeWidth <= MIN_WIDTH) return bestSafe;

      width = saturatedWidth !== null ? clean((safeWidth + saturatedWidth) / 2) : (predictWidth(result, source.profile) ?? width);
    }
    return bestSafe;
  }

  async function repairSegment(source, start, end, widthHint) {
    const repaired = [];
    let cursor = start;
    let width = Math.max(MIN_WIDTH, widthHint);

    while (cursor < end && !sameNumber(cursor, end) && !stopped) {
      const result = await findWindow(source, cursor, width, end, "repair");
      if (!result || result.max === null) return null;

      repaired.push(result);
      cursor = result.max;
      width = predictWidth(result, source.profile) ?? width;
    }
    return repaired;
  }

  async function scanRange(source, start, initialWidth, hardEnd = null, initialTailCheck = true) {
    let cursor = start;
    let width = initialWidth;

    if (hardEnd !== null) {
      while (cursor < hardEnd && !sameNumber(cursor, hardEnd) && !stopped) {
        const result = await findWindow(source, cursor, width, hardEnd);
        if (!result || result.max === null) return false;
        
        await source.accept(result);
        cursor = result.max;
        width = predictWidth(result, source.profile) ?? width;
      }
      return !stopped && (cursor >= hardEnd || sameNumber(cursor, hardEnd));
    }

    let acceptedSinceTail = 0;
    let previousWidth = null;

    if (initialTailCheck) {
      const tail = await source.probe(cursor, null, "tail_probe");
      if (!tail) return false;
      if (!tail.saturated) {
        await source.accept(tail);
        return true;
      }
    }

    while (!stopped) {
      const result = await findWindow(source, cursor, width);
      if (!result || result.max === null) return false;

      await source.accept(result);
      cursor = result.max;
      const currentWidth = result.width;
      width = predictWidth(result, source.profile) ?? width;
      acceptedSinceTail++;

      const widthJump = previousWidth !== null && currentWidth !== null ? currentWidth / previousWidth : 1;
      previousWidth = currentWidth;

      if (acceptedSinceTail < TAIL_CHECK_EVERY && widthJump < TAIL_WIDTH_GROWTH_TRIGGER) continue;

      const tail = await source.probe(cursor, null, "tail_probe");
      if (!tail) return false;
      if (!tail.saturated) {
        await source.accept(tail);
        return true;
      }
      acceptedSinceTail = 0;
    }
    return false;
  }

  async function warmStart(source, previousRanges) {
    console.log(`Warm-Start ${source.name}: ${previousRanges.length} gelernte Ranges`);
    const results = [];

    for (const range of previousRanges) {
      const result = await source.probe(range.min, range.max, "warm_probe");
      if (!result) return false;
      results.push(result);
    }

    for (let i = 0; i < results.length && !stopped;) {
      const current = results[i];
      const next = results[i + 1] ?? null;

      if (current.max === null) {
        if (!current.saturated) {
          await source.accept(current);
          return true;
        }
        const hint = results[Math.max(0, i - 1)]?.width ?? source.startWidth;
        return scanRange(source, current.min, hint, null, false);
      }

      if (current.saturated) {
        console.log(`REPAIR ${source.name} saturated ${current.min} - ${current.max}`);
        const repaired = await repairSegment(source, current.min, current.max, current.width * 0.7);
        if (!repaired) return false;
        
        for (const result of repaired) await source.accept(result);
        i++;
        continue;
      }

      if (current.load < source.profile.mergeThreshold && next && !next.saturated) {
        const merged = await source.probe(current.min, next.max, "merge_probe");
        if (!merged) return false;
        
        if (!merged.saturated) {
          await source.accept(merged);
          i += 2;
          if (merged.max === null) return true;
          continue;
        }
      }

      await source.accept(current);
      i++;
    }
    return !stopped;
  }

  // Previous ranges
  const previous = options.cold ? { trenches: null, signals: {} } : await loadPreviousState(options.out, options);
  const allSignalsWarm = !ENABLE_SIGNALS || SIGNAL_TYPES.every(type => previous.signals[type]);

  output.summary.trenches_mode = previous.trenches ? "warm" : "cold";
  output.summary.signals_mode = ENABLE_SIGNALS ? (allSignalsWarm ? "warm" : "cold") : "disabled";
  output.summary.mode = ENABLE_SIGNALS ? (previous.trenches && allSignalsWarm ? "warm" : (!previous.trenches && !Object.keys(previous.signals).length ? "cold" : "mixed")) : (previous.trenches ? "warm" : "cold");

  // Trenches scan
  console.log("\n=== SOURCE 1: TRENCHES ===");
  const trenchesSource = {
    name: "trenches", profile: TRENCHES, startWidth: options.startWidth,
    probe: probeTrenchesRange, accept: acceptTrenches,
  };

  const trenchesSuccess = previous.trenches 
    ? await warmStart(trenchesSource, previous.trenches) 
    : await scanRange(trenchesSource, options.minMarketCap, options.startWidth, options.maxMarketCap, true);

  if (!trenchesSuccess || stopped) {
    await flushMints();
    await save(partialFile);
    return finish(false);
  }

  // Signal scan
  let signalsSuccess = true;

  if (ENABLE_SIGNALS) {
    console.log("\n=== SOURCE 2: SIGNALS ===");
    for (const signalType of SIGNAL_TYPES) {
      if (stopped) { signalsSuccess = false; break; }
      console.log(`\n--- signal_type=${signalType} ---`);

      const signalSource = {
        name: `signal:${signalType}`, profile: SIGNAL, startWidth: options.startWidth,
        probe: (min, max, purpose) => probeSignalRange(signalType, min, max, purpose),
        accept: result => acceptSignal(signalType, result),
      };

      const previousRanges = previous.signals[signalType] ?? null;
      const success = previousRanges 
        ? await warmStart(signalSource, previousRanges) 
        : await scanRange(signalSource, options.minMarketCap, options.startWidth, options.maxMarketCap, true);

      if (!success) { signalsSuccess = false; break; }
    }
  } else {
    console.log("\n=== SOURCE 2: SIGNALS DISABLED ===");
  }

  // Coverage validation
  if (trenchesSuccess && !normalizeRanges(output.ranges, options.minMarketCap, options.maxMarketCap)) {
    output.summary.unresolved = true;
    signalsSuccess = false;
    console.error("Coverage-Fehler bei Trenches.");
  }

  if (ENABLE_SIGNALS && signalsSuccess) {
    for (const signalType of SIGNAL_TYPES) {
      if (normalizeRanges(output.signals.ranges_by_type[signalType], options.minMarketCap, options.maxMarketCap)) continue;
      output.summary.unresolved = true;
      signalsSuccess = false;
      console.error(`Coverage-Fehler bei signal_type=${signalType}.`);
      break;
    }
  }

  // Final commit
  await flushMints();
  if (trenchesSuccess && signalsSuccess && !stopped && !output.summary.unresolved) {
    await commit();
    return finish(true);
  }

  await save(partialFile);
  return finish(false);

  // Final summary
  function finish(success) {
    updateSummary();
    console.log("\n========================================");
    console.log("FERTIG");
    console.log("========================================");
    console.log(`Mode: ${output.summary.mode} | trenches=${output.summary.trenches_mode} | signals=${output.summary.signals_mode}`);
    console.log(`Requests: ${output.summary.queries}`);
    console.log(`Successful: ${output.summary.successful_queries}`);
    console.log(`Failed: ${output.summary.failed_queries}`);
    console.log(`Trenches Mints: ${output.summary.trenches_unique_mints}`);
    console.log(`Trenches Repeats across accepted ranges: ${output.summary.trenches_repeated_across_ranges}`);
    console.log(`Signal Raw Mints: ${output.summary.signal_raw_unique_mints}`);
    console.log(`Signal Mints in selected range: ${output.summary.signal_unique_mints}`);
    console.log(`Overlap: ${output.summary.overlap_unique_mints}`);
    console.log(`Combined Unique Mints: ${output.summary.unique_mints}`);
    console.log(`Trenches Ranges: ${output.summary.accepted_ranges}`);
    console.log(`Signal Ranges: ${output.summary.accepted_signal_ranges}`);
    console.log(`Elapsed: ${(output.summary.elapsed_ms / 1000).toFixed(2)}s`);
    console.log(`Effective rate: ${output.summary.effective_rps} req/s`);
    console.log(`429: ${output.summary.stopped_by_rate_limit}`);
    console.log(`Unresolved: ${output.summary.unresolved}`);
    console.log(`Completed: ${success && output.summary.completed}`);
    console.log(`Metadata: ${success ? options.out : partialFile}`);
    console.log(`Mint data: ${success ? options.mintsOut : partialMintsFile}`);
    return success;
  }
}

// ============================================================
// Main
// ============================================================

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const apiKey = await loadApiKey();

  console.log("\nGMGN Adaptive Market Cap Collector");
  console.log(`Market Cap range: $${options.minMarketCap} - ${displayCap(options.maxMarketCap)}`);
  console.log(`Total Fee filter >= ${options.minTotalFee}`);
  console.log(`Trenches: limit=${TRENCHES.limit} | target=${TRENCHES.targetMin}-${TRENCHES.limit - 1}`);
  console.log(`Signals: ${ENABLE_SIGNALS ? "enabled" : "disabled"} | limit=${SIGNAL.limit} | target=${SIGNAL.targetMin}-${SIGNAL.limit - 1}`);
  console.log(`Rate: max ${options.rps} req/s`);
  console.log(`Concurrency: ${options.concurrency}`);
  console.log(`Metadata: ${options.out}`);
  console.log(`Mint data: ${options.mintsOut}\n`);

  await runCollector(options, apiKey);
}

main().catch(error => {
  console.error(error?.stack || error?.message || error);
  process.exitCode = 1;
});