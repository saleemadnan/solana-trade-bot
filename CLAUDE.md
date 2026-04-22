# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Bot

```bash
# HTTP polling mode
node index.js

# WebSocket real-time mode (recommended for production)
node websocket.js
```

Bun is preferred over Node.js (`bun index.js` / `bun websocket.js`).

There is no test suite and no build step — this is plain CommonJS JavaScript that runs directly.

## Setup

```bash
npm install        # or: bun install
cp .env.example .env
# Fill in .env before running
```

## Architecture

The project has two self-contained entry points that each define and instantiate a `TradingBot` class:

**`index.js` — HTTP polling mode**
Runs two concurrent infinite loops via `Promise.allSettled`:
- `buyMonitor()`: Polls `dataClient.getLatestTokens()` every `DELAY` ms, filters results, fires parallel buys.
- `positionMonitor()`: Every `MONITOR_INTERVAL` ms, checks each open position via `dataClient.getTokenInfo()` and triggers a sell if PnL thresholds are breached.

**`websocket.js` — WebSocket mode**
Uses `Datastream` from `@solana-tracker/data-api` with two subscription types:
- `dataStream.subscribe.latest()` → `handleNewToken()`: Receives new token events in real time, runs the filter, and buys immediately.
- `dataStream.subscribe.price.token(address)` → `handlePriceUpdate()`: Per-position price feed; triggers sell when PnL thresholds are hit. Subscriptions are created on buy and torn down on sell.
- `statusMonitor()` is the only polling loop — it just logs stats and wallet balance.

**Shared internals (identical in both files):**
- `filterToken(s)`: Validates liquidity, market cap, risk score, holder count, social data, and allowed markets. Uses `seenTokens`, `buyingTokens`, `sellingPositions` Sets to prevent races.
- `performSwap(token, isBuy)`: Calls `solanaTracker.getSwapInstructions()` then `solanaTracker.performSwap()` from the `solana-swap` package. Buys use the configured SOL `AMOUNT`; sells use the token quantity stored in the position.
- `handleSuccessfulBuy`: Waits 5 s for chain confirmation, queries on-chain token balance, records position to `this.positions` Map.
- `handleSuccessfulSell`: Calculates PnL, appends to `this.soldPositions`, removes from Map.
- Positions are persisted to `positions.json` and `sold_positions.json` on every change and reloaded on startup. `seenTokens` is reconstructed from loaded positions so the bot never re-enters a token it already traded in a previous session.

## Environment Variables

Required for HTTP mode: `PRIVATE_KEY`, `SOLANA_TRACKER_API_KEY`  
Also required for WebSocket mode: `WS_URL`

Key trading knobs:

| Variable | Effect |
|---|---|
| `AMOUNT` | SOL per buy (default 0.01) |
| `MAX_POSITIONS` | Concurrent position cap (default 10) |
| `MAX_NEGATIVE_PNL` | Stop-loss % — must be negative (default -50) |
| `MAX_POSITIVE_PNL` | Take-profit % — must be positive (default 100) |
| `MARKETS` | Comma-separated allowlist: `raydium`, `orca`, `pumpfun`, `moonshot`, `raydium-cpmm`, `raydium-launchpad`, `meteora-dlmm`, `meteora-curve`, `meteora-dyn`, `meteora-dyn-v2` |
| `DEBUG` | Set `true` to log per-token filter pass/fail details |
| `JITO` | Set `true` to enable Jito bundle submission |

## Logging

Winston writes to three sinks simultaneously: console (colour-coded, timestamps only on errors), `trading-bot.log` (all levels), and `trading-bot-error.log` (errors only). Enable `DEBUG=true` to surface `logger.debug()` calls that explain why each token was filtered in or out.
