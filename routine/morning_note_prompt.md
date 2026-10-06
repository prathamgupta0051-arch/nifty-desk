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

**Structure.** Write the note as JSON in exactly this shape:

```json
{
  "date": "YYYY-MM-DD (today, IST)",
  "generated": "08:50 IST (the time you finished, IST)",
  "headline": "One or two sentences: the single most important thing about today's market, in plain English.",
  "sections": [
    {"title": "The big picture", "body": "2-3 short paragraphs separated by \n. What the dashboard's six checks say overall, how strongly they agree, and what that means."},
    {"title": "What big investors are doing", "body": "FII and DII money yesterday, which sectors FIIs are moving in and out of, and FII positions in futures. Is it a one-day blip or a trend?"},
    {"title": "What the world is telling India", "body": "Crude, dollar, rupee, US bond rates, the Fed, US stocks, overnight moves and every active flag, explained simply, with why each matters for Indian stocks."},
    {"title": "Company results", "body": "Notable results from the last few days (especially Nifty 50 companies): what was strong, what was weak, and any pattern across sectors. Say so briefly if there were none."},
    {"title": "What could change the picture", "body": "The upcoming events that matter most in the next 1-2 weeks, and the levels or signals that would show the current view is wrong."},
    {"title": "Bottom line", "body": "3-4 sentences tying it together: the overall read, how confident the data is, and the main risk to that read."}
  ],
  "watch": ["3-5 short bullets: specific things to watch today, with times in IST where known"],
  "sources": [{"title": "Short description", "url": "https://..."}]
}
```

You may use **double asterisks** for bold on a few key phrases; no other formatting. Use `\n` only to separate paragraphs inside a body.

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
