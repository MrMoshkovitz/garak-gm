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

---

## Parallel Workers Flow (--parallel_attempts)

### Independent Worker Monitoring (No Shared State)

```
Main Process spawns N workers (e.g., 50)
  ↓
┌─────────────┬─────────────┬─────────────┬─────────────┐
│  Worker 1   │  Worker 2   │  Worker 3   │  Worker 50  │
│ (isolated)  │ (isolated)  │ (isolated)  │ (isolated)  │
└─────────────┴─────────────┴─────────────┴─────────────┘
      ↓              ↓              ↓              ↓
Each worker INDEPENDENTLY executes:
      ↓
  Make API call:
    raw_response = generator.with_raw_response.create(**args)
      ↓
  Extract headers from THIS worker's response:
    x-ratelimit-remaining-requests: 4999
    x-ratelimit-limit-requests: 5000
    x-ratelimit-reset-requests: 12ms
      ↓
  _check_and_handle_rate_limits(headers)
      ↓
  IF remaining ≤ (limit * 0.01):  ← 99% threshold
    THIS worker pauses (others may continue)
    time.sleep(wait_time)
      ↓
  Return response
```

**Key:** No coordination, no shared state, no locks!

### Why Independent Monitoring Works

**1. 99% Buffer Provides Safety:**
- At 5000 RPM: 99% threshold = 50 request buffer
- Even if all 50 workers fire simultaneously, buffer absorbs them
- Workers get fresh headers after each call and quickly learn threshold

**2. API Latency Natural Spacing:**
- Each request takes ~1-2 seconds (network latency)
- Workers naturally stagger their requests over time
- Not all workers check at exact same millisecond

**3. Workers Self-Correct:**
- Worker makes request → Gets back "remaining: 48"
- Worker sees 48 < 50 (99% threshold) → Pauses
- After pause, gets fresh headers → Resumes

### Parallel vs Serial Performance

| Mode | Workers | Throughput | Coordination | Tested |
|------|---------|------------|--------------|--------|
| Serial | 1 | 1x baseline | N/A | ✅ |
| **Parallel (independent)** | **4** | **~3-4x** | **None needed** | **✅** |
| **Parallel (independent)** | **50** | **~20-30x** | **None needed** | **✅** |

**Tested:** 50 workers, 20K+ prompts, zero 429 errors

### Actual Logging Output (50 Workers)

```
2025-10-29 10:29:24,567  INFO  Rate limits - RPM: 4999/5000 (0.0% used, resets in 12ms)
2025-10-29 10:29:24,609  INFO  Rate limits - RPM: 4999/5000 (0.0% used, resets in 12ms)
2025-10-29 10:29:24,715  INFO  Rate limits - RPM: 4999/5000 (0.0% used, resets in 12ms)
2025-10-29 10:29:24,744  INFO  Rate limits - RPM: 4999/5000 (0.0% used, resets in 12ms)
```

**Notice:**
- Each worker logs independently (not coordinated)
- Fresh headers show current state
- All workers stay well below 99% threshold
