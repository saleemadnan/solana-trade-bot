const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");

test(".env remains ignored and only .env.example is tracked", () => {
  const gitignore = fs.readFileSync(path.join(root, ".gitignore"), "utf8");

  assert.match(gitignore, /^\.env$/m);
  assert.ok(fs.existsSync(path.join(root, ".env.example")));
});

test("runtime files are not checked in", () => {
  for (const filename of [
    "positions.json",
    "sold_positions.json",
    "trading-bot.log",
    "trading-bot-error.log",
  ]) {
    assert.equal(fs.existsSync(path.join(root, filename)), false, `${filename} should not be committed`);
  }
});

test("dry-run mode is the documented default", () => {
  const envExample = fs.readFileSync(path.join(root, ".env.example"), "utf8");
  const index = fs.readFileSync(path.join(root, "index.js"), "utf8");
  const websocket = fs.readFileSync(path.join(root, "websocket.js"), "utf8");

  assert.match(envExample, /^DRY_RUN=true$/m);
  assert.match(index, /dryRun: process\.env\.DRY_RUN !== "false"/);
  assert.match(websocket, /dryRun: process\.env\.DRY_RUN !== "false"/);
});
