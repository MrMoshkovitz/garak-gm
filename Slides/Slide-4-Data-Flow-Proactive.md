# Slide 4: Data Flow - Proactive Approach (After)

## Enhanced Request Flow with Header Monitoring

### Complete Proactive Flow Diagram

```
Probe
  ↓
_execute_attempt (probes/base.py)
  ↓
_call_model() (generators/openai_rated.py)
  ↓
raw_response = generator.with_raw_response.create(**args)  ← Access both headers + body
  ↓
┌─────────────────────────────────────────┐
│           API Response                  │
│                                         │
│  ┌──────────────┐    ┌───────────────┐ │
│  │   Headers    │    │     Body      │ │
│  │              │    │               │ │
│  │ x-ratelimit- │    │ {choices: []} │ │
│  │  -limit-     │    │               │ │
│  │  -remaining- │    │               │ │
│  │  -reset-     │    │               │ │
│  └──────────────┘    └───────────────┘ │
└─────────────────────────────────────────┘
         ↓                      ↓
         ↓                 response.parse()
         ↓                      ↓
  _discover_all_limits()   [Message(c.text)]
         ↓
  {
    'requests': {limit: 3500, remaining: 35, reset: '6m0s'},
    'tokens': {limit: 90000, remaining: 10000, reset: '6m0s'}
  }
         ↓
  _check_and_handle_rate_limits()
         ↓
  ┌─ IF remaining ≤ (limit * 0.01):  ← 99% threshold check
  │     ↓
  │  _parse_reset_time(reset) → wait_time = 361s
  │     ↓
  │  logging.warning("⏸️ Pausing at 99% usage")
  │     ↓
  │  time.sleep(wait_time)  ← Proactive pause
  │     ↓
  │  logging.info("✅ Resuming after reset")
  │
  └─ ELSE: Continue immediately
         ↓
  Return [Message(...)]
         ↓
  @backoff STILL ACTIVE (handles edge cases: daily limits, network errors)
```

### Real-Time Logging on Every Request

```
INFO: Rate limits - requests: 3498/3500 (0.1% used, resets in 17ms) |
                    tokens: 88773/90000 (1.4% used, resets in 818ms)
```

**What This Tells Us:**
- **requests:** 3498/3500 = 2 requests remaining (0.06% capacity left)
- **tokens:** 88773/90000 = 1,227 tokens remaining (1.4% capacity left)
- **resets in:** How long until limits reset (17ms for requests, 818ms for tokens)

### Header Discovery Process

```
_discover_all_limits(headers_lower)
  ↓
1. Find all "x-ratelimit-remaining-*" keys
   → ["x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens"]
  ↓
2. For each remaining key:
   - Extract type_name ("requests", "tokens")
   - Build limit_key: "x-ratelimit-limit-requests"
   - Build reset_key: "x-ratelimit-reset-requests"
  ↓
3. Parse values:
   - limit: int(headers['x-ratelimit-limit-requests']) → 3500
   - remaining: int(headers['x-ratelimit-remaining-requests']) → 35
   - reset: headers['x-ratelimit-reset-requests'] → "6m0s"
  ↓
4. Return discovered limits dictionary
```

**Future-Proof:** Automatically discovers new limit types (e.g., images-per-minute if OpenAI adds it)

### Reset Time Parser

```
_parse_reset_time("6m0s")
  ↓
1. Regex pattern: r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?'
  ↓
2. Extract components:
   - hours = 0
   - minutes = 6
   - seconds = 0
  ↓
3. Calculate:
   total_seconds = (0 * 3600) + (6 * 60) + 0 = 360
  ↓
4. Add +1 second buffer = 361 seconds
  ↓
5. Return 361
```

**Handles:** "17ms", "818ms", "6m0s", "1h30m0s", etc.

### 99% Threshold Check Logic

```python
# For each limit type (requests, tokens):
limit = 3500
remaining = 35

# Check if at 99% usage:
if remaining <= (3500 * 0.01):  # 35 <= 35
    # YES - pause needed
    wait_time = _parse_reset_time("6m0s")  # 361 seconds
    time.sleep(361)

# Otherwise continue immediately
```

### @backoff Decorator Still Active

```
Proactive monitoring handles:    @backoff handles:
✅ Minute-based limits (RPM/TPM) ✅ Daily limits (429s from RPD/TPD)
✅ Prevents most 429 errors        ✅ Network errors
✅ Optimizes timing                ✅ Server errors
                                   ✅ Any edge cases
```

**Layered Defense:** Proactive prevention + reactive fallback
