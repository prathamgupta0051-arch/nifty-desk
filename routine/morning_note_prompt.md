You are writing today's **Morning note** for the Nifty Positioning Desk, a personal dashboard about the Indian stock market (Nifty 50). The reader is a student learning to read the market. They want an honest, well-reasoned overview in very simple English before the market opens at 9:15 am IST.

## 1. Get the data

You are in a git checkout of `prathamgupta0051-arch/nifty-desk`. First run `git checkout main && git pull origin main` so you have this morning's data. A GitHub job rebuilds it at 8:00 am IST on weekdays.

Read these files:
- `data/published_data.json`: the six-step positioning framework (Nifty spot, 20/50/200-day moving averages, swing structure, futures price and OI history, FII/DII/Pro/Client index-futures positions, option chain with OI, change in OI and IV pressure by strike, PCR history, India VIX, IV percentile). The field `updated` says when it was built.
- `data/published_context.json`: the other tabs.
  - `macro`: crude, gold, US and India 10-year bond rates, dollar index, USD/INR, S&P 500, US VIX and the Fed rate, with 1-day/1-month/3-month changes, a good/bad-for-India reading, and **flags** (big or unusual changes, including what the market expects from the Fed).
  - `flows`: FII and DII cash buying and selling, FII derivatives positions, FII long % history, and `sectors` (which sectors FIIs bought or sold, from NSDL).
  - `results`: company results filed in the last 7 days, with revenue and profit growth vs last year.
  - `events`: the next 45 days (RBI, Fed, India CPI/GDP, global data releases, F&O expiries, market holidays, big-company results).
- `NIFTY_POSITIONING_DESK.md`: explains every rule the dashboard uses (how scores, flags and readings are calculated). Read section 5 and section 4b so you understand what the numbers mean.

Work out the dashboard's own view by applying those rules to the data: the score for each of the four direction steps, the overall bias score from −100 to +100, how many steps agree, and the volatility level. Use Python if it helps. Don't invent a different method; explain the dashboard's view, then add your own reasoning on top.

Check freshness. If `updated` in `published_data.json` is from before yesterday's market close, say so plainly at the top of the note.

## 2. Research beyond the numbers

Use web search to check and explain what the data shows. Look for the following, and only use what you can confirm from a reliable source:
- How US stocks, crude oil, gold, the dollar and US bond rates moved overnight, and why.
- Any Fed, RBI or government news since yesterday's close: statements, decisions, data releases.
- Why FIIs bought or sold yesterday, if credible reporting explains it.
- News on any big company that reported results, or reports today.
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
