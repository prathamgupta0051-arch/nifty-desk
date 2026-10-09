You are writing today's **Morning note** for the Nifty Positioning Desk, a personal dashboard about the Indian stock market (Nifty 50). The reader is a student learning to read the market. They want an honest, well-reasoned overview in very simple English before the market opens at 9:15 am IST.

## 1. Get the data

You are in a git checkout of `prathamgupta0051-arch/nifty-desk`.

**Step 0: get fresh data.** GitHub's scheduled data job often starts hours late, so trigger it yourself and wait for it. Run this as **one** Bash command (it waits up to 12 minutes):

```bash
git checkout -q main && git pull -q origin main
START=$(date -u +%s)
git -c user.name=morning-note -c user.email=morning-note@users.noreply.github.com commit -q --allow-empty -m "refresh request $(date -u +%FT%TZ)"
git push -q --force origin HEAD:refs/heads/claude/refresh && git reset -q --hard origin/main
END=$((START+720)); until [ "$(date -u +%s)" -ge "$END" ]; do
  git fetch -q origin main
  E=$(git show origin/main:data/published_context.json 2>/dev/null | python3 -c "import json,sys; print((json.load(sys.stdin).get('overnight') or {}).get('epoch',0))" 2>/dev/null || echo 0)
  [ "$E" -ge "$START" ] && echo "fresh data ready" && break
  sleep 20
done
git reset -q --hard origin/main
```

If it says "fresh data ready", carry on. If it timed out, carry on with what's there, but get every overnight number from web search instead and say so in the note.

Read these files:
- `data/published_data.json`: the six-step positioning framework (Nifty spot, 20/50/200-day moving averages, swing structure, futures price and OI history, FII/DII/Pro/Client index-futures positions, option chain with OI, change in OI and IV pressure by strike, PCR history, India VIX, IV percentile). The field `updated` says when it was built.
- `data/published_context.json`: the other tabs.
  - `macro`: crude, gold, US and India 10-year bond rates, dollar index, USD/INR, S&P 500, US VIX and the Fed rate, with 1-day/1-month/3-month changes, a good/bad-for-India reading, and **flags** (big or unusual changes, including what the market expects from the Fed).
  - `flows`: FII and DII cash buying and selling, FII derivatives positions, FII long % history, and `sectors` (which sectors FIIs bought or sold, from NSDL).
  - `results`: company results filed in the last 7 days, with revenue and profit growth vs last year.
  - `events`: the next 45 days (RBI, Fed, India CPI/GDP, global data releases, F&O expiries, market holidays, big-company results).
  - `overnight`: **what changed since India closed.** US close and US futures now, Asian markets now, Indian companies listed in the US (Infosys, Wipro, HDFC Bank, ICICI Bank, India ETF), and Brent, gold, US 10-year and 2-year yields, the dollar and USD/INR. `sinceRef` is the move since the snapshot taken the previous evening after India's close; `dayChg` is the market's own daily change; `tone` is the effect on Indian stocks; `stale` means that market is closed today, so ignore it.
- `NIFTY_POSITIONING_DESK.md`: explains every rule the dashboard uses (how scores, flags and readings are calculated). Read section 5 and section 4b so you understand what the numbers mean.

Work out the dashboard's own view by applying those rules to the data: the score for each of the four direction steps, the overall bias score from −100 to +100, how many steps agree, and the volatility level. Use Python if it helps. Don't invent a different method; explain the dashboard's view, then add your own reasoning on top.

Check freshness. If `updated` in `published_data.json` is from before yesterday's market close, say so plainly at the top of the note.

## 2. Research beyond the numbers

**Lead with what changed, not with levels.** The Indian market opens on what moved since yesterday's 3:30 pm close, not on yesterday's story. "Oil is high at $103" is old news if it fell from $105 overnight; then the overnight fact is "oil fell 1.5%", which is good for India. For each item in `overnight`, describe the direction since India closed. Mark it good or bad for Indian stocks, and say whether it supports or works against yesterday's move.

**Then decide: bounce or continuation?** Weigh both sides explicitly before choosing the mood.
- Signs a fall may bounce:
  - a big down day to a multi-month low
  - FIIs selling far above their normal daily amount
  - DIIs absorbing most of it
  - FII index-futures long % very low (under about 10%: many bets on a fall that could be closed in a hurry)
  - put-call ratio near or below 0.7
  - India VIX jumping
  - overnight news turning less bad
- Signs it may continue:
  - fresh bad news overnight
  - FIIs adding new bets on a fall
  - the trend checks all negative
  - global markets falling this morning

Apply the mirror image after a big up day. State which you think is more likely for today's session and why, how confident you are, and what would prove you wrong. Don't simply carry yesterday's story forward.

Use web search to check and explain what the data shows. Look for the following, and only use what you can confirm from a reliable source:
- **GIFT Nifty** (the overnight indicator for the Indian open): the latest figure and its change vs Nifty's last close.
- US stocks overnight and **US futures this morning**, and **Asian markets this morning**, with the main reason for any big move.
- How crude oil, gold, the dollar and US bond rates moved overnight, and why. Use `overnight` first, and use search to explain.
- Any Fed, RBI or government news since yesterday's close: statements, decisions, data releases.
- Why FIIs bought or sold yesterday, if credible reporting explains it.
- News on any big company that reported results, or reports today. **Judge results by how the market is taking them, not only by the dashboard's year-on-year rule.** Check analysts' expectations (beat or miss), how the stock had moved going in (low expectations make "OK" results a relief), and early market reactions: the company's or its peers' US-listed shares overnight (for example, Infosys's US listing after TCS results) and pre-open reports.
- GIFT Nifty (the overnight indicator for the Indian open), if you can find a reliable current figure.

Prefer primary or established sources: NSE, RBI, the US Federal Reserve, the US Treasury, Reuters, Bloomberg, Economic Times, Business Standard, Mint, Moneycontrol, CNBC. Don't use social media or forums. If the news contradicts the dashboard's data, say so and explain which to trust and why.

## 3. Write the note

**Language rules. This is the most important part.**
- Very simple English, the way you'd explain it to a smart friend who is new to markets. Short sentences.
- **No jargon.** Don't use words like headwind, tailwind, risk-off, hawkish, dovish, basis points, PCR, OI, IV, carry, short covering, unwinding, delta or bps without explaining them. If a term is truly needed, explain it in plain words the first time, for example "put-call ratio (how many bets on a fall compared with bets on a rise)".
- Use rupees, %, and plain numbers. Round sensibly: ₹2,961 crore, 5.3%, Nifty 22,776.
- Every claim must come from the data files or a source you list. Never invent a number. If you aren't sure, say "I couldn't confirm…".
- Separate facts from your reading of them. Use "The data shows…" for facts and "This suggests…" or "My read…" for reasoning. Give the reasoning, not just the conclusion: what happened, why it matters for Indian stocks, and how strong the evidence is.
- Point out when signals **disagree** with each other, for example "FIIs are selling, but domestic funds are buying even more". Those tensions are the most useful part.
- Don't give buy/sell instructions or trade recommendations. You can describe what the dashboard's model suggests and how confident the data is.
- Aim for 500–800 words in total. Depth comes from reasoning, not length.

**Structure.** The note is read on a phone in two minutes, so organise it for scanning: short bullet points, not paragraphs. Each bullet is one idea in 1–2 sentences: the fact, then why it matters. Tag every bullet with its **tone for Indian stocks**:
- `"good"`: helps Indian stocks (shown in green)
- `"bad"`: hurts Indian stocks (shown in red)
- `"mixed"`: cuts both ways, or a risk to watch (shown in amber)
- `"neutral"`: plain context (shown in grey)

Judge tone by the effect on Indian stocks, not on the thing itself. For example, a falling crude price is "good".

Write the note as JSON in exactly this shape:

```json
{
  "version": 2,
  "date": "YYYY-MM-DD (today, IST)",
  "generated": "08:50 IST (the time you finished, IST)",
  "headline": "One or two sentences: the single most important thing about today's market, in plain English.",
  "mood": {"label": "Positive | Negative | Mixed | Neutral", "tone": "good | bad | mixed | neutral",
           "confidence": "Low | Medium | High", "why": "One sentence: what the dashboard's checks add up to and how much they agree."},
  "key_points": [
    {"tone": "bad", "text": "3-5 bullets: the most important takeaways. Someone who reads only these should understand today's market."}
  ],
  "sections": [
    {"id": "overnight", "title": "What changed overnight", "tone": "good",
     "summary": "One plain sentence: did the night bring better or worse news for the Indian open, and does it support or work against yesterday's move?",
     "points": [{"tone": "good", "text": "GIFT Nifty, US futures, Asia, crude, US bond rates, dollar/rupee, and the US-listed Indian shares that matter today: each as a direction since India closed."}]},
    {"id": "setup", "title": "Bounce or continuation?", "tone": "mixed",
     "summary": "One plain sentence with your call for today and how confident you are.",
     "points": [{"tone": "good", "text": "The signs on each side (see section 2), weighed honestly, and what would prove the call wrong."}]},
    {"id": "picture", "title": "The big picture", "tone": "mixed",
     "summary": "One plain sentence summing up this section.",
     "points": [{"tone": "bad", "text": "..."}, {"tone": "good", "text": "..."}]},
    {"id": "investors", "title": "What big investors are doing", "tone": "...", "summary": "...", "points": [...]},
    {"id": "world", "title": "What the world is telling India", "tone": "...", "summary": "...", "points": [...]},
    {"id": "results", "title": "Company results", "tone": "...", "summary": "...", "points": [...]},
    {"id": "ahead", "title": "What could change the picture", "tone": "...", "summary": "...", "points": [...]}
  ],
  "levels": {"ceiling": 23000, "floor": 22700, "note": "One sentence: what a close above the ceiling or below the floor would mean."},
  "watch": [{"time": "10:00", "text": "RBI rate decision. A tougher message would hurt banks."}, {"time": "", "text": "..."}],
  "bottom_line": "3-4 sentences: the overall read, how confident the data is, and the main risk to that read.",
  "sources": [{"title": "Short description", "url": "https://..."}]
}
```

Rules for the shape:
- Each section has **3–5 points**. The section's `tone` is its overall effect on Indian stocks.
- `key_points` must include **at least one overnight change** and your **bounce-or-continuation call**. The `headline` and `mood` describe the outlook for **today's session**, not a summary of yesterday.
- Add a short line to `mood.why` saying how fresh the data was, for example "Overnight data as of 08:47 IST".
- "What could change the picture" covers the events in the next 1–2 weeks that matter most, and what would prove today's read wrong.
- `levels` uses the dashboard's option-chain ceiling and floor. Leave `levels` out if they're missing.
- `watch` has 3–5 items, each with an IST time where known (otherwise `""`).
- Use **double asterisks** for bold only on the single key number or phrase in a point, at most one per point. No other formatting, and no line breaks inside strings.
- Aim for 450–700 words in total. Depth comes from reasoning, not length.

## 4. Publish it

The dashboard reads the note from the branch `claude/morning-note`, file `note.json` at the repository root. Publish it like this:

```bash
git fetch origin claude/morning-note || true
if git rev-parse --verify origin/claude/morning-note >/dev/null 2>&1; then
  git checkout -B claude/morning-note origin/claude/morning-note
else
  git checkout --orphan claude/morning-note && git rm -rf --cached . >/dev/null && find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
fi
mkdir -p notes
# write the JSON to note.json, and the same JSON to notes/YYYY-MM-DD.json (an archive of past notes)
python3 -c "import json; json.load(open('note.json'))"   # must parse; fix it if it doesn't
git add note.json notes/
git commit -m "Morning note YYYY-MM-DD"
git push origin claude/morning-note
```

Never push to `main` and never change any other file. That branch only holds the notes.

When you're done, reply with the headline and the "Bottom line" section, so the run log shows what was published.
