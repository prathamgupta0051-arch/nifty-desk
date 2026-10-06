# Nifty Positioning Desk

A live, light-themed dashboard that reads Nifty positioning data the way a trading desk does. It follows the six-step framework from the SBI Securities session: go from chart to position, and let each step confirm or kill the signal from the step before it.

> For learning how positioning data fits together. This is not investment advice.

---

## 1. What it does

- Pulls Nifty data from NSE automatically, every 60 seconds while the market is open.
- Runs it through the six steps and gives each step a score from −2 (bearish) to +2 (bullish).
- Combines steps 1–4 into a **bias score** from −100 to +100 and a view: Bullish, Neutral or Bearish.
- Uses step 5 (volatility) to decide whether to **buy options, use spreads or sell options**.
- Uses step 6 to suggest the **lowest-risk option structure**, with Greeks, cost, max profit/loss and a payoff chart.
- Explains everything in plain language in the "In simple words" box.

---

## 2. Files

| File | What it is |
|---|---|
| `nifty-desk.html` | The dashboard: layout, calculations and charts in one file. |
| `desk_server.py` | Local Python server that fetches NSE data and serves the dashboard. Uses only built-in Python, so there's nothing to install. |
| `start-desk.command` | Double-click on a Mac to start the server. |
| `data/` | Cache of downloaded history (bhavcopies, participant files, index/VIX history). Created automatically. |

---

## 3. How to run

The server runs **in the background as a macOS login service**. It starts when you log in, restarts itself if it crashes, and keeps running when the Claude app is closed. Just open **http://127.0.0.1:8765** (bookmark it), or double-click `start-desk.command`, which also wakes the service if it's down.

- Project folder: `~/Nifty Positioning Desk`
- Service file: `~/Library/LaunchAgents/com.prathamgupta.niftydesk.plist`
- Log: `~/Nifty Positioning Desk/logs/desk_server.log`

Check whether the service is running:

```bash
launchctl print gui/$(id -u)/com.prathamgupta.niftydesk | grep state
```

Restart it, for example after editing `desk_server.py`:

```bash
launchctl kickstart -k gui/$(id -u)/com.prathamgupta.niftydesk
```

Remove it completely:

```bash
launchctl bootout gui/$(id -u)/com.prathamgupta.niftydesk && rm ~/Library/LaunchAgents/com.prathamgupta.niftydesk.plist
```

The service uses the Python at `/Library/Frameworks/Python.framework/Versions/3.15/bin/python3`. If you upgrade Python, update that path in the service file.

To run it by hand instead, stop the service first (otherwise port 8765 is already taken), then run:

```bash
python3 desk_server.py
```

- The first start takes about 2 minutes while it downloads a year of history. Later starts use the cache.
- Add `--no-browser` if you don't want a browser tab to open automatically.
- Set `DESK_PORT=9000` to use a different port.
- If you open `nifty-desk.html` on its own (for example as the published artifact), it runs on **sample data** from the August case in the slides.

**Controls on the page**

- **Refresh now** forces a new pull from NSE.
- **Freeze numbers** pauses live updates so you can edit inputs and test scenarios.
- **Load sample data** resets to the August example.

---

## 4. Layout

**Sidebar:** Overview, then one page per step. Each step has a coloured dot showing its signal: green bullish, red bearish, amber neutral, blue informational.

**Overview page**
1. **Summary cards:** Nifty 50 (with the day's change), Market view, FII long %, Put-call ratio, and India VIX with its IV percentile.
2. **In simple words:** what's happening, what the model suggests (with cost and worst/best case), why, and when the view is wrong. Includes a small glossary.
3. **Market mood:** a semicircle dial for the bias score, a bar for each step's score, how many steps agree, the volatility regime and the model pick.
4. **Framework chain:** the six steps with "confirms" or "kills" links between them.
5. **Suggested trade:** the legs, net premium, max profit and max loss.
6. **Key levels:** resistance, support, the 20/50/200 DMAs, the trade's breakevens and spot, sorted high to low with % distance from spot.

**Step pages:** the explanation and charts sit in the large card on the left; the inputs sit in the smaller card on the right. In live mode the inputs are filled from NSE, and you can still edit them.

---

## 4b. Market context tabs

These three pages are in the sidebar under **Market context**. They're served by `context_feeds.py` and only work when the dashboard runs on your Mac.

| Tab | What it shows | Source | Refresh |
|---|---|---|---|
| **Global macro** | Brent, WTI, gold, US 10Y, dollar index, USD/INR, India 10Y, S&P 500, US VIX and the Fed funds rate. Each has its level, 1D/1M/3M change, a 1-year chart, a 1-year percentile, and a headwind/tailwind reading for India, with a plain-English reason. The overall backdrop is Headwinds, Mixed or Tailwinds. | CNBC public quote and chart feeds; New York Fed | 15 min |
| **FII & DII flows** | FII/FPI and DII cash-market buying, selling and net (₹ crore), net as % of turnover, change vs the previous day, streak and month-to-date totals. It also shows FII positions in index futures, stock futures, index calls and index puts, with day-on-day change, and a 2-year history of FII long % in index futures. | NSE `fiidiiTradeReact` and participant-wise OI | 30 min |
| **Quarterly results** | Results filed in the last 7 days, with revenue, net profit and margin taken from each company's XBRL filing, compared with the same quarter last year. Each row is read as Strong, In line, Weak or Loss, Nifty 50 names are tagged, and there are filters, search, a link to the filing, and a 14-day results calendar. | NSE integrated filings, event calendar, Nifty 50 list | 30 min |

**Rules**
- **Macro headwind/tailwind** is judged on the last month's move:
  - crude or gold ±5%
  - dollar index ±2%
  - USD/INR ±1%
  - US 10-year yield ±0.20 points
  - India 10-year yield ±0.15 points
  - S&P 500 ±3%
  - US VIX by level: above 25 is a headwind, below 15 a tailwind
  - the Fed by the change in its target range over 6 months
- **Significant FII day:** a net flow of ₹3,000 crore or more, or at least 1.5× the average absolute flow of the previous 20 days.
- **Results read:**
  - Strong = profit up 20% or more year on year, with revenue up
  - Weak = profit down 20% or more
  - Loss = negative profit

**FII flows by sector** (in the FII & DII tab):
- Net equity investment by sector for the last fortnight, last month or last 3 months, as a diverging bar chart with a plain-English summary of the biggest exits and buys.
- Each sector's weight in the FII portfolio and how it changed over 6 months, plus its 3-month flow.
- Source: NSDL's fortnightly sector-wise FPI files (BSE sector classification), cached in `data/sectors/`. NSDL publishes them a few days after each fortnight ends.

**Event calendar** (its own tab): the next 45 days, filterable by High impact, India, Global, or Expiry & holidays. Each event has its time in IST, a category, an impact level and why it matters. The top cards count down to the next RBI policy, Fed decision, India CPI, monthly expiry and market holiday.

| Events | Source |
|---|---|
| RBI MPC decisions | `data/events_manual.json` (FY27 schedule; edit it when RBI publishes the next one) |
| Fed (FOMC) decisions | federalreserve.gov calendar; the decision lands around midnight IST, so it's shown on the next Indian session |
| US, China, Eurozone and Japan data releases | Forex Factory weekly calendar (high and medium impact) |
| India CPI, IIP and GDP | MOSPI's usual schedule: CPI on the 12th, IIP on the 28th, GDP on the last working day of Feb, May, Aug and Nov |
| Nifty weekly and monthly expiries | NSE option-chain contract list |
| Market holidays | NSE holiday master |
| Nifty 50 results | NSE event calendar |

NSE publishes only the latest day of FII/DII cash flows, so `data/flows/` saves one file per day and the history grows from the day collection started.

## 5. The six steps and the rules used

The slides give the logic but not exact cut-offs, so the thresholds below are my own choices. You can change them in the code, and the PCR thresholds on the page.

### Step 1 · Price trend: *where is the market and what's the structure?*
- **Location:** +1 or −1 for spot above or below each of the 20, 50 and 200 DMA, averaged.
- **Structure:** compares the last two swing highs and swing lows, found with 3-bar fractals over 90 sessions:
  - higher highs and higher lows = uptrend (+1)
  - lower highs and lower lows = downtrend (−1)
  - anything else = range (0)
- Score = location + structure, capped to ±2.

### Step 2 · OI & FII positioning: *who is positioned, and are they adding or exiting?*

| Price | OI | Reading | Score |
|---|---|---|---|
| ↑ | ↑ | Long build-up | +1.25 |
| ↓ | ↑ | Short build-up | −1.25 |
| ↑ | ↓ | Short covering | +0.5 |
| ↓ | ↓ | Long unwinding | −0.5 |

- The score is halved when OI changed by less than 1%.
- **FII long %** = FII index-futures longs ÷ (longs + shorts):
  - rose 3 points or more → +0.75 (short covering or fresh longs)
  - fell 3 points or more → −0.75 (adding shorts)
  - below 15% and flat → −0.5 (still short, no covering yet)
  - above 70% → +0.5
- Below 10% is flagged as the historical short-covering zone, per the slide. The trigger is long % turning up.
- The comparison window can be the previous session, 5 sessions or 10 sessions.

### Step 3 · Option chain: *where are writers defending strikes?*
- **Ceiling** = strike with the most call OI at or above spot. **Floor** = strike with the most put OI at or below spot. Writers only defend levels in front of the price.
- **Wall migration:** yesterday's walls are rebuilt from OI − ΔOI, so the page shows whether the ceiling and floor moved.
- **% change in OI** = ΔOI ÷ yesterday's OI.
- **Significant** = |% change| ≥ 30% and |ΔOI| ≥ 10% of the biggest OI in the chain.

**Telling writers from buyers.** Each strike gets an IV-pressure reading:
1. Back out the forward from put-call parity on both days, and price with Black-76. This removes the timing gap between the index close and the option closes. The computed IVs match NSE's published IVs to within about 0.05.
2. Take each strike's IV from its out-of-the-money option, since ITM prices are mostly intrinsic value.
3. Find the expected IV under *sticky moneyness*: yesterday's IV at the same distance from the forward, K × F_prev ÷ F_now.
4. Residual = actual IV − expected IV. Subtract the chain's median residual (the market-wide vol shift, shown separately). What's left is that strike's own buying or selling pressure.
5. Previous-day option prices come from the bhavcopy, so this works without saved snapshots.

| OI | IV pressure (±0.10) | Action |
|---|---|---|
| ↑ | ↓ | Writing |
| ↑ | ↑ | Buying |
| ↓ | ↑ | Writers covering |
| ↓ | ↓ | Buyers exiting |
| any | within ±0.10 | Unclear (no weight) |

**What each action means and how much it counts**

| Action | OTM / ATM | ITM |
|---|---|---|
| Writing | 1.0 · calls = ceiling built (bearish), puts = floor built (bullish) | 0.5 |
| Writers covering | 0.7 · wall giving way | 0.5 · wall broken |
| Buying | 0.5 · directional bets or hedges | 0.3 |
| Buyers exiting | 0.3 · bets dropped | 0.3 · profit-booking |

**Further adjustments**
- **Deep ITM** (more than 200 points): weight × 0.5.
- **Intraday churn** (ΔOI under 1% of the day's volume): weight × 0.5.
- **Shared IV:** a call and a put at the same strike share one IV, so the side with the smaller OI change gets × 0.6.

**Score** = 1.5 × weighted net flow (−1 to +1), then ±0.5 if spot has broken through a wall. In sample mode there's no IV data, so every OI rise is assumed to be writing and every fall to be covering.

### Step 4 · Put-call ratio: *is sentiment stretched: signal or trap?*
- **PCR = put OI ÷ call OI.** The slide text had this inverted; this is the standard convention.
- Above 1.5 → −1 (overheated, contrarian bearish). Below 0.7 → +1 (oversold, contrarian bullish).
- Otherwise the 5-session change decides:
  - fell 0.15 or more → −1 (bulls giving up)
  - rose 0.15 or more → +1 (put writers stepping in)

### Step 5 · Implied volatility: *is premium cheap or expensive?*
- In live mode, IV = India VIX. IV percentile = share of the last 250 sessions with VIX below today's level.
- IVP under 30 = **low**, so buy options. 30–70 = **mid**, so use spreads. Over 70 = **high**, so sell options.
- The trend (falling, flat or rising) compares today with 5 sessions ago, using a ±5% band.

### Step 6 · Greeks & strategy: *which instrument expresses the view at the least risk?*

Bias ≥ +20 is bullish and ≤ −20 is bearish. Anything in between is neutral.

| | Low IV | Mid IV | High IV |
|---|---|---|---|
| **Bullish** | Long call | Bull call spread | Bull put spread (sell at the put floor) |
| **Neutral** | Long straddle | Iron butterfly | Iron condor (sell at the call wall and put floor) |
| **Bearish** | Long put | Bear put spread | Bear call spread (sell at the call wall) |

- Prices and Greeks (delta, gamma, theta per day, vega per 1% IV) come from **Black-Scholes** with one flat IV for all strikes.
- The payoff at expiry is shown for all lots, with breakevens marked.
- Click any cell in the grid to model a different structure.

### Combining the steps
- **Bias score** = (step 1 + step 2 + step 3 + step 4) ÷ 8 × 100.
- **Conviction:**
  - all 4 steps agree with the direction = high
  - 3 agree = medium
  - fewer = low, so size down or wait
- **Chain links:** each step is compared with the running direction of the steps before it and marked *confirms*, *kills* or *neutral*.

---

## 6. Data sources (all NSE)

| Data | Source | How often |
|---|---|---|
| Nifty spot, India VIX | `/api/allIndices` | Every 60 s when the market is open, every 15 min when closed |
| Nifty futures price and OI (all expiries) | `/api/liveEquity-derivatives?index=nse50_fut` | Same |
| Option chain, nearest expiry | `/api/option-chain-contract-info` + `/api/option-chain-v3` | Same |
| Nifty daily history, ~14 months (DMAs, swing structure) | `/api/historicalOR/indicesHistory` | Once a day |
| India VIX history, 1 year (IV percentile) | `/api/historicalOR/vixhistory` | Once a day |
| F&O bhavcopy, last 11 sessions (futures OI series, PCR history, lot size) | `nsearchives…/BhavCopy_NSE_FO_…csv.zip` | Once a day, rechecked every 30 min after 4 pm until published |
| Participant-wise OI, last 11 sessions (FII/DII/Pro/Client) | `nsearchives…/fao_participant_oi_DDMMYYYY.csv` | Same |

**Processing notes**
- **Futures OI series:** built by chaining each day's reported change in OI, so an expiring contract dropping out doesn't look like unwinding.
- **Price leg of step 2:** uses the Nifty spot close. This avoids the jump when the near-month futures contract rolls over.
- **PCR history:** end-of-day, across all Nifty expiries. The **live PCR** is for the current expiry only and is shown separately.
- **Live prints:** only count as "today" after 9:15 am IST.

---

## 7. Verification (done on 30 Sep 2026 data)

Every number the dashboard uses was checked against an independent file or recalculated from NSE's raw files:

| Check | Result |
|---|---|
| Nifty and VIX closes on sample dates vs NSE `ind_close_all` archive | All match |
| 20 / 50 / 200 DMA recalculated | 23,343.55 / 23,901.58 / 24,367.78, exact |
| Spot vs bhavcopy underlying price | 22,620.45, exact |
| Futures OI and 1-day change vs bhavcopy | 311,084 contracts, +16,704, exact |
| Option chain, 12 strikes, OI and ΔOI for calls and puts, vs bhavcopy | All match |
| PCR (this expiry and all-expiry history) recalculated | Match |
| FII/DII/Pro/Client longs and shorts vs raw participant CSVs | All 16 numbers match; totals balance |
| IV percentile and 1-year range recalculated | Match |

The market was closed during the check, so intraday live refreshes were compared against end-of-day files rather than watched in real time.

---

## 8. Limitations

- **FII long %** covers all index futures (Nifty, Bank Nifty, Fin Nifty and others), not just Nifty. This is how the metric is normally quoted.
- **India VIX** is used as Nifty's IV. The ATM IV from the option chain is shown alongside it.
- **Greeks** assume one flat IV, so skew is ignored. Check live premiums before acting.
- **Rollover days** can still show some extra futures OI build-up.
- **NSE can change its data feeds without notice.** It already retired the older option chain feed. If a source fails, the sidebar says so and the other sources keep working.
- **Lot size** comes from the latest bhavcopy (65 at the time of writing).

---

## 9. Ideas for next steps

1. **Position sizing:** enter your capital and get the number of lots so one trade risks no more than 1–2% of it.
2. **Event warnings:** flag RBI policy, US Fed, budget and expiry days, when IV can jump.
3. **Paper-trade journal:** log each suggestion and track later how well the model did.
4. **Max pain:** add it to step 3, next to the call wall and put floor.
5. **Longer history:** keep more than 11 sessions of FII long % and PCR to see the bigger trend.
