# Change 6 — Fix NLQ `debate_query` Temperature (0.5 → 0.2)

## What & Why

`ai_agents/committee.py` has three LLM calls, each with a different temperature setting:

| Function | Current Temp | Purpose |
|---|---|---|
| `get_market_query_response()` | `0.4` | General market chat |
| `evaluate_signal()` | `0.2` ✅ | Signal approve/reject |
| `debate_query()` | `0.5` ❌ | NLQ terminal debate |

**Temperature controls how creative/random the LLM response is.**
- `0.0` = fully deterministic, same answer every time
- `0.2` = tight, factual, consistent — correct for trading decisions
- `0.5` = noticeably random — will hallucinate specific price levels, invent RSI values, fabricate P&L figures and present them as real

`debate_query()` feeds the NLQ terminal in your dashboard. When users ask *"which strategy had the highest win rate?"* or *"how much did I lose on SBIN?"*, the LLM should query the DB context and report facts — not creatively invent them.

`evaluate_signal()` correctly uses `0.2`. `debate_query()` must match.

---

## The Fix

**File:** `ai_agents/committee.py`

**Find (around line 240):**
```python
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a trading firm AI committee. Output only raw JSON, no markdown."},
                {"role": "user", "content": system_prompt}
            ],
            temperature=0.5,
            max_tokens=1000
        )
```

**Replace with:**
```python
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a trading firm AI committee. Output only raw JSON, no markdown."},
                {"role": "user", "content": system_prompt}
            ],
            temperature=0.2,
            max_tokens=1000
        )
```

One line change: `0.5` → `0.2`.

---

## Run Locally to Verify

### 1. Prerequisites

Make sure your `.env` is set up with an LLM key (DeepSeek is cheapest for testing):

```bash
# .env
LLM_API_KEY=your_deepseek_or_openai_key
LLM_BASE_URL=https://api.deepseek.com/v1     # or https://api.openai.com/v1
LLM_MODEL=deepseek-chat                       # or gpt-3.5-turbo
```

### 2. Install dependencies (if not already done)

```bash
pip install openai python-dotenv
```

### 3. Apply the fix

Open `ai_agents/committee.py` in your editor, find line ~240 and change `temperature=0.5` to `temperature=0.2`.

### 4. Test the fix directly

Save this as `test_change_6.py` in your project root and run it:

```python
# test_change_6.py
import sys
sys.path.insert(0, ".")

from ai_agents.committee import debate_query

# Ask the same question 3 times — with 0.2 temp answers should be
# very similar each time. With 0.5 they would diverge significantly.
query = "Should I trade RELIANCE tomorrow? What does the technicals say?"

print("=" * 60)
print(f"Query: {query}")
print("=" * 60)

for i in range(3):
    print(f"\n--- Run {i+1} ---")
    result = debate_query(query)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        break
    print(f"Technical Analyst: {result.get('technical_analyst', {}).get('opinion', 'N/A')[:120]}...")
    print(f"Risk Manager:      {result.get('risk_manager', {}).get('opinion', 'N/A')[:120]}...")
    verdict = result.get('head_quant', {}).get('verdict', 'N/A')
    print(f"Head Quant Verdict: {verdict}")

print("\n✅ If all 3 runs gave the same TRADE/NO TRADE verdict, temperature is consistent.")
```

```bash
python test_change_6.py
```

**Expected output:** All 3 runs should return the same `verdict` (TRADE or NO TRADE) and very similar reasoning. If they flip between TRADE and NO TRADE across runs, temperature is still too high.

### 5. Test via the dashboard

```bash
# Start the API server
python api_server.py

# Open http://localhost:5001 in your browser
# Go to the NLQ terminal panel
# Type: "What is the current market outlook for RELIANCE?"
# Run it 2-3 times — answers should be consistent
```

### 6. Verify via curl

```bash
curl -s -X POST http://localhost:5001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Should I buy TCS today?"}' | python -m json.tool
```

You should see a valid JSON with `technical_analyst`, `risk_manager`, `head_quant` keys and a `verdict` of either `"TRADE"` or `"NO TRADE"`.

---

## Before vs After

| Scenario | Before (temp=0.5) | After (temp=0.2) |
|---|---|---|
| "Win rate this week?" | Might invent 73% win rate | Reports only what's in context |
| Same query run twice | Different price levels each time | Consistent levels |
| "SBIN outlook?" | Hallucinated RSI of 67, 41, 55 on 3 runs | Stable RSI reference |
| JSON structure | Occasionally malformed | Reliably valid JSON |

---

## Related Temperature Reference

For future LLM calls in `committee.py`, use these as a guide:

| Use Case | Recommended Temp |
|---|---|
| Signal approve/reject (structured JSON) | `0.1` – `0.2` |
| Trade debate / NLQ analysis | `0.2` |
| General market chat (exploratory) | `0.3` – `0.4` |
| Creative content / summaries | `0.5`+ |

**Rule of thumb: any call that outputs JSON used in trading logic should be `≤ 0.2`.**
