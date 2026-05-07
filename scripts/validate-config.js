const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const isExample = process.argv.includes("--example");
const envPath = path.join(root, isExample ? ".env.example" : ".env");

const requiredKeys = [
  "PRIVATE_KEY",
  "SOLANA_TRACKER_API_KEY",
  "RPC_URL",
  "AMOUNT",
  "SLIPPAGE",
  "MAX_NEGATIVE_PNL",
  "MAX_POSITIVE_PNL",
  "MARKETS",
];

const websocketKeys = ["WS_URL"];
const placeholderPattern = /your_|YOUR_|xxxx|placeholder|change_me/i;

function parseEnv(content) {
  const values = new Map();

  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;

    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match) continue;

    const key = match[1];
    let value = match[2].split(/\s+#/)[0].trim();
    value = value.replace(/^["']|["']$/g, "");
    values.set(key, value);
  }

  return values;
}

function fail(message) {
  console.error(`config validation failed: ${message}`);
  process.exitCode = 1;
}

if (!fs.existsSync(envPath)) {
  fail(`${path.basename(envPath)} was not found`);
  process.exit();
}

const values = parseEnv(fs.readFileSync(envPath, "utf8"));
const missing = [...requiredKeys, ...websocketKeys].filter((key) => !values.get(key));

if (missing.length > 0) {
  fail(`missing required keys: ${missing.join(", ")}`);
}

if (!isExample) {
  const unsafePlaceholders = [...requiredKeys, ...websocketKeys].filter((key) => {
    const value = values.get(key) || "";
    return placeholderPattern.test(value);
  });

  if (unsafePlaceholders.length > 0) {
    fail(`replace placeholder values before live use: ${unsafePlaceholders.join(", ")}`);
  }
}

const amount = Number(values.get("AMOUNT"));
const slippage = Number(values.get("SLIPPAGE"));
const maxNegativePnl = Number(values.get("MAX_NEGATIVE_PNL"));
const maxPositivePnl = Number(values.get("MAX_POSITIVE_PNL"));

if (!Number.isFinite(amount) || amount <= 0) {
  fail("AMOUNT must be a positive number");
}

if (!Number.isFinite(slippage) || slippage <= 0 || slippage > 50) {
  fail("SLIPPAGE must be greater than 0 and no more than 50");
}

if (!Number.isFinite(maxNegativePnl) || maxNegativePnl > 0) {
  fail("MAX_NEGATIVE_PNL must be a negative number or zero");
}

if (!Number.isFinite(maxPositivePnl) || maxPositivePnl <= 0) {
  fail("MAX_POSITIVE_PNL must be a positive number");
}

if (!process.exitCode) {
  console.log(`${path.basename(envPath)} configuration shape is valid`);
}
