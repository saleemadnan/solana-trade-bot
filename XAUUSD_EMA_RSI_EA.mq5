//+------------------------------------------------------------------+
//|  XAUUSD EMA Crossover + RSI Filter EA                           |
//|  Strategy : EMA 50/200 crossover confirmed by RSI               |
//|  Symbol   : XAUUSD  |  Timeframe : H1                           |
//+------------------------------------------------------------------+
#property copyright "Trading Bot"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

//--- Input parameters
input int    FastEMA_Period    = 50;       // Fast EMA period
input int    SlowEMA_Period    = 200;      // Slow EMA period
input int    RSI_Period        = 14;       // RSI period
input double RSI_BuyLevel      = 50.0;    // RSI minimum for buy
input double RSI_SellLevel     = 50.0;    // RSI maximum for sell
input double LotSize           = 0.01;    // Lot size
input int    StopLoss_Points   = 1500;    // Stop Loss in points ($15 on XAUUSD)
input int    TakeProfit_Points = 3000;    // Take Profit in points ($30 on XAUUSD)
input int    MaxSpread_Points  = 30;      // Max allowed spread in points
input long   MagicNumber       = 20240101;

//--- Global variables
int    g_ema_fast_handle;
int    g_ema_slow_handle;
int    g_rsi_handle;
datetime g_last_bar_time = 0;
CTrade g_trade;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   g_ema_fast_handle = iMA(_Symbol, PERIOD_H1, FastEMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   g_ema_slow_handle = iMA(_Symbol, PERIOD_H1, SlowEMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   g_rsi_handle      = iRSI(_Symbol, PERIOD_H1, RSI_Period, PRICE_CLOSE);

   if(g_ema_fast_handle == INVALID_HANDLE ||
      g_ema_slow_handle == INVALID_HANDLE ||
      g_rsi_handle      == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create indicator handles.");
      return INIT_FAILED;
   }

   g_trade.SetExpertMagicNumber(MagicNumber);
   g_trade.SetDeviationInPoints(10);

   Print("EA initialized on ", _Symbol, " H1");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(g_ema_fast_handle);
   IndicatorRelease(g_ema_slow_handle);
   IndicatorRelease(g_rsi_handle);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Only act on new H1 bar
   if(!IsNewBar()) return;

   // Check spread
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > MaxSpread_Points)
   {
      Print("Spread too high: ", spread, " points. Skipping.");
      return;
   }

   // Read indicator values (index 1 = last closed bar, index 2 = bar before that)
   double ema_fast[], ema_slow[], rsi[];
   ArraySetAsSeries(ema_fast, true);
   ArraySetAsSeries(ema_slow, true);
   ArraySetAsSeries(rsi,      true);

   if(CopyBuffer(g_ema_fast_handle, 0, 0, 3, ema_fast) < 3) return;
   if(CopyBuffer(g_ema_slow_handle, 0, 0, 3, ema_slow) < 3) return;
   if(CopyBuffer(g_rsi_handle,      0, 0, 2, rsi)      < 2) return;

   bool bullish_cross = (ema_fast[1] > ema_slow[1]) && (ema_fast[2] <= ema_slow[2]);
   bool bearish_cross = (ema_fast[1] < ema_slow[1]) && (ema_fast[2] >= ema_slow[2]);
   bool rsi_bullish   = (rsi[1] > RSI_BuyLevel);
   bool rsi_bearish   = (rsi[1] < RSI_SellLevel);

   int buy_positions  = CountPositions(POSITION_TYPE_BUY);
   int sell_positions = CountPositions(POSITION_TYPE_SELL);

   // Buy signal
   if(bullish_cross && rsi_bullish && buy_positions == 0)
   {
      ClosePositionsByType(POSITION_TYPE_SELL);
      OpenTrade(ORDER_TYPE_BUY);
   }

   // Sell signal
   if(bearish_cross && rsi_bearish && sell_positions == 0)
   {
      ClosePositionsByType(POSITION_TYPE_BUY);
      OpenTrade(ORDER_TYPE_SELL);
   }
}

//+------------------------------------------------------------------+
//| Open a new trade                                                 |
//+------------------------------------------------------------------+
void OpenTrade(ENUM_ORDER_TYPE order_type)
{
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double ask   = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid   = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl, tp, price;

   if(order_type == ORDER_TYPE_BUY)
   {
      price = ask;
      sl    = price - StopLoss_Points   * point;
      tp    = price + TakeProfit_Points * point;
      g_trade.Buy(LotSize, _Symbol, price, sl, tp, "EMA_RSI_BUY");
      Print("BUY  opened | Price:", price, " SL:", sl, " TP:", tp);
   }
   else
   {
      price = bid;
      sl    = price + StopLoss_Points   * point;
      tp    = price - TakeProfit_Points * point;
      g_trade.Sell(LotSize, _Symbol, price, sl, tp, "EMA_RSI_SELL");
      Print("SELL opened | Price:", price, " SL:", sl, " TP:", tp);
   }
}

//+------------------------------------------------------------------+
//| Count open positions for this EA by type                        |
//+------------------------------------------------------------------+
int CountPositions(ENUM_POSITION_TYPE pos_type)
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
      {
         if(PositionGetInteger(POSITION_MAGIC)        == MagicNumber &&
            PositionGetString(POSITION_SYMBOL)        == _Symbol     &&
            (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == pos_type)
            count++;
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Close all positions of a given type for this EA                 |
//+------------------------------------------------------------------+
void ClosePositionsByType(ENUM_POSITION_TYPE pos_type)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
      {
         if(PositionGetInteger(POSITION_MAGIC)        == MagicNumber &&
            PositionGetString(POSITION_SYMBOL)        == _Symbol     &&
            (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == pos_type)
         {
            g_trade.PositionClose(ticket);
            Print("Closed position ticket: ", ticket);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Returns true only on the first tick of a new H1 bar             |
//+------------------------------------------------------------------+
bool IsNewBar()
{
   datetime current_bar = iTime(_Symbol, PERIOD_H1, 0);
   if(current_bar != g_last_bar_time)
   {
      g_last_bar_time = current_bar;
      return true;
   }
   return false;
}
//+------------------------------------------------------------------+
