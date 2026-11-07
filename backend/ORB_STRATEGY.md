# AIR ORB strategy module

The ORB module publishes live trading signals only. It does not place broker orders.

## Morning ORB

- Build the opening range from live ticks between 09:18:00 and 09:22:59 Asia/Kolkata.
- Discard the partial 09:21–09:24 three-minute candle because it overlaps the five-minute opening range.
- Use completed three-minute candles aligned to the NSE 09:15 session open, beginning with 09:24–09:27.
- Require a completed candle close above the opening-range high.
- Then require a later candle to retest the range high (its low reaches or crosses the range high).
- Then require a subsequent completed three-minute candle to close above the range high.
- Entry reference is that confirmation candle's close; initial stop is that candle's low.
- After entry, trail only from completed three-minute candle lows and only raise the stop.
- Exit condition: a completed candle closes below the previous completed candle's open. The first tick in the next candle is recorded as the executable exit reference. A live tick touching the current stop is recorded as a stop exit.

## Afternoon ORB

- Build the range from live ticks between 12:57:00 and 12:59:59 Asia/Kolkata.
- On the first tick strictly above the completed range high at/after 13:00:00, publish the BUY signal immediately. No candle-close confirmation or retest is required.
- Initial stop is the 12:57–13:00 range low. A live tick at or below that stop records an SL exit.
- No additional trailing or time-based exit rule is added unless separately specified.

## Data and execution safety

- ORB requires a verified customer-scoped live broker feed and exact instrument mapping. NSE EOD is never treated as live data.
- The app subscribes to the selected live adapter, and normalized ticks are consumed by the customer's isolated MarketDataHub.
- The mobile screen displays ranges, qualification state and signals. It refreshes status every five seconds.
- The current implementation keeps intraday engine state in process memory. Restarting the API clears the current day's partial ranges and signal monitor state; durable recovery is a follow-up requirement before production deployment.
- Subscribing after a range window has begun captures only ticks received after subscription. The app does not fabricate missing range values from EOD data.
- Signals are informational only. No manual or automatic broker order is sent by this module.
