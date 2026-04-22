"""
XAUUSD Trading Bot — MT5 + Claude AI
Claude analyses every new H1 bar and decides: BUY / SELL / HOLD
Requires: pip install MetaTrader5 anthropic pandas python-dotenv
Note: MetaTrader5 library works on Windows only (needs MT5 terminal running)
"""

import os
import json
import time
import logging
from datetime import datetime

import pandas as pd
import anthropic
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "MetaQuotes-Demo")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

SYMBOL      = "XAUUSD"
TIMEFRAME   = mt5.TIMEFRAME_H1
LOT_SIZE    = float(os.getenv("LOT_SIZE",   "0.01"))
SL_POINTS   = int(os.getenv("SL_POINTS",   "1500"))   # $15 on XAUUSD
TP_POINTS   = int(os.getenv("TP_POINTS",   "3000"))   # $30 on XAUUSD
MAX_SPREAD  = int(os.getenv("MAX_SPREAD",  "30"))
MAGIC       = 20240101
BARS        = 250   # History bars sent to Claude for context

# ── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("mt5_claude_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# MT5 helpers
# ══════════════════════════════════════════════════════════════════

def connect_mt5() -> bool:
    if not mt5.initialize():
        log.error("MT5 initialize() failed: %s", mt5.last_error())
        return False
    auth = mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
    if not auth:
        log.error("MT5 login failed: %s", mt5.last_error())
        mt5.shutdown()
        return False
    info = mt5.account_info()
    log.info("Connected | Account: %d | Balance: %.2f %s",
             info.login, info.balance, info.currency)
    return True


def get_market_data() -> pd.DataFrame | None:
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, BARS)
    if rates is None or len(rates) == 0:
        log.warning("No market data received")
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)

    # Indicators
    df["ema50"]  = df["close"].ewm(span=50,  adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    delta        = df["close"].diff()
    gain         = delta.clip(lower=0).rolling(14).mean()
    loss         = (-delta.clip(upper=0)).rolling(14).mean()
    rs           = gain / loss.replace(0, 1e-10)
    df["rsi"]    = 100 - (100 / (1 + rs))

    return df.dropna()


def get_open_positions() -> list[dict]:
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return []
    return [
        {
            "ticket": p.ticket,
            "type":   "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
            "volume": p.volume,
            "price_open": p.price_open,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
        }
        for p in positions
        if p.magic == MAGIC
    ]


def open_trade(action: str) -> bool:
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info is None:
        log.error("Symbol %s not found", SYMBOL)
        return False

    if not symbol_info.visible:
        mt5.symbol_select(SYMBOL, True)

    spread = mt5.symbol_info_tick(SYMBOL).ask - mt5.symbol_info_tick(SYMBOL).bid
    spread_points = round(spread / symbol_info.point)
    if spread_points > MAX_SPREAD:
        log.warning("Spread too high (%d pts). Skipping trade.", spread_points)
        return False

    tick  = mt5.symbol_info_tick(SYMBOL)
    point = symbol_info.point

    if action == "BUY":
        price = tick.ask
        sl    = price - SL_POINTS * point
        tp    = price + TP_POINTS * point
        order_type = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl    = price + SL_POINTS * point
        tp    = price - TP_POINTS * point
        order_type = mt5.ORDER_TYPE_SELL

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    SYMBOL,
        "volume":    LOT_SIZE,
        "type":      order_type,
        "price":     price,
        "sl":        round(sl, symbol_info.digits),
        "tp":        round(tp, symbol_info.digits),
        "deviation": 10,
        "magic":     MAGIC,
        "comment":   "claude_ai",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error("%s failed | retcode=%d | %s", action, result.retcode, result.comment)
        return False

    log.info("✅ %s executed | ticket=%d | price=%.2f | SL=%.2f | TP=%.2f",
             action, result.order, price, sl, tp)
    return True


def close_all_positions():
    for pos in get_open_positions():
        tick = mt5.symbol_info_tick(SYMBOL)
        close_type  = mt5.ORDER_TYPE_SELL if pos["type"] == "BUY" else mt5.ORDER_TYPE_BUY
        close_price = tick.bid            if pos["type"] == "BUY" else tick.ask

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       SYMBOL,
            "volume":       pos["volume"],
            "type":         close_type,
            "position":     pos["ticket"],
            "price":        close_price,
            "deviation":    10,
            "magic":        MAGIC,
            "comment":      "claude_close",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            log.info("Closed ticket %d | profit=%.2f", pos["ticket"], pos["profit"])
        else:
            log.error("Close failed for ticket %d | retcode=%d", pos["ticket"], result.retcode)


# ══════════════════════════════════════════════════════════════════
# Claude AI decision engine
# ══════════════════════════════════════════════════════════════════

DECISION_TOOL = {
    "name": "trading_decision",
    "description": "Return a trading decision for XAUUSD based on market analysis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["BUY", "SELL", "HOLD"],
                "description": "The trading action to execute.",
            },
            "confidence": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Confidence level (1=very low, 10=very high).",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief explanation of the decision in Arabic.",
            },
            "close_existing": {
                "type": "boolean",
                "description": "True if any opposite open position should be closed first.",
            },
        },
        "required": ["action", "confidence", "reasoning", "close_existing"],
    },
}


def ask_claude(df: pd.DataFrame, open_positions: list[dict]) -> dict | None:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    last   = df.iloc[-1]
    prev   = df.iloc[-2]
    recent = df.tail(10)[["close", "ema50", "ema200", "rsi"]].round(2).to_string()

    system = (
        "أنت محلل تداول خبير متخصص في الذهب (XAUUSD) على الإطار الزمني H1. "
        "مهمتك تحليل بيانات السوق واتخاذ قرار تداول دقيق. "
        "استخدم دائماً أداة trading_decision لإرجاع قرارك."
    )

    user = f"""
## بيانات السوق الحالية — XAUUSD H1

**الشمعة الأخيرة المغلقة:**
- الوقت:       {last.name}
- السعر:       {last['close']:.2f}
- EMA 50:      {last['ema50']:.2f}
- EMA 200:     {last['ema200']:.2f}
- RSI (14):    {last['rsi']:.1f}
- EMA50 > EMA200: {"نعم (اتجاه صاعد)" if last['ema50'] > last['ema200'] else "لا (اتجاه هابط)"}
- تقاطع جديد: {"EMA50 قطعت لأعلى ✅" if prev['ema50'] <= prev['ema200'] and last['ema50'] > last['ema200']
               else "EMA50 قطعت لأسفل ✅" if prev['ema50'] >= prev['ema200'] and last['ema50'] < last['ema200']
               else "لا يوجد تقاطع"}

**آخر 10 شمعات:**
{recent}

**الصفقات المفتوحة حالياً:**
{json.dumps(open_positions, indent=2, ensure_ascii=False) if open_positions else "لا يوجد"}

## المهمة
حلّل الوضع الحالي واتخذ قراراً: BUY أو SELL أو HOLD.
- BUY:  إذا كان الاتجاه صاعداً وRSI فوق 50 وهناك تقاطع أو زخم واضح
- SELL: إذا كان الاتجاه هابطاً وRSI دون 50 وهناك تقاطع أو ضغط بيع
- HOLD: إذا كانت الإشارات متضاربة أو السوق في منطقة خطر
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system,
        tools=[DECISION_TOOL],
        tool_choice={"type": "tool", "name": "trading_decision"},
        messages=[{"role": "user", "content": user}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "trading_decision":
            return block.input

    return None


# ══════════════════════════════════════════════════════════════════
# Main loop
# ══════════════════════════════════════════════════════════════════

def wait_for_new_bar():
    """Block until the next H1 bar opens."""
    current = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 1)[0]["time"]
    while True:
        time.sleep(15)
        latest = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 1)[0]["time"]
        if latest != current:
            return


def main():
    log.info("═" * 55)
    log.info("  XAUUSD Bot — MT5 + Claude AI")
    log.info("═" * 55)

    if not connect_mt5():
        return

    log.info("Waiting for first H1 bar close …")

    try:
        while True:
            wait_for_new_bar()

            df = get_market_data()
            if df is None or len(df) < BARS // 2:
                log.warning("Insufficient data, skipping this bar.")
                continue

            open_pos = get_open_positions()

            log.info("─" * 45)
            log.info("New H1 bar | Price=%.2f | EMA50=%.2f | EMA200=%.2f | RSI=%.1f",
                     df.iloc[-1]["close"],
                     df.iloc[-1]["ema50"],
                     df.iloc[-1]["ema200"],
                     df.iloc[-1]["rsi"])
            log.info("Asking Claude AI for decision …")

            decision = ask_claude(df, open_pos)
            if decision is None:
                log.error("No decision received from Claude. Skipping.")
                continue

            action       = decision["action"]
            confidence   = decision["confidence"]
            reasoning    = decision["reasoning"]
            close_first  = decision["close_existing"]

            log.info("Claude says: %s (confidence=%d/10)", action, confidence)
            log.info("Reasoning: %s", reasoning)

            # Skip low-confidence decisions
            if confidence < 6:
                log.info("Confidence too low (%d). Holding.", confidence)
                continue

            # Close opposing position if instructed
            if close_first and open_pos:
                log.info("Closing existing positions before new trade.")
                close_all_positions()
                time.sleep(2)

            # Execute
            if action == "BUY":
                has_buy = any(p["type"] == "BUY" for p in open_pos)
                if not has_buy:
                    open_trade("BUY")
                else:
                    log.info("Already have a BUY position. Skipping.")

            elif action == "SELL":
                has_sell = any(p["type"] == "SELL" for p in open_pos)
                if not has_sell:
                    open_trade("SELL")
                else:
                    log.info("Already have a SELL position. Skipping.")

            else:
                log.info("HOLD — no action taken.")

    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        mt5.shutdown()
        log.info("MT5 disconnected.")


if __name__ == "__main__":
    main()
