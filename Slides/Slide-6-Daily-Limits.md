# Slide 6: Why Daily Limits Aren't Handled Proactively

## The Daily Limit Challenge

### ❌ The Problem: No Daily Limit Headers

**What OpenAI Sends:**
```
x-ratelimit-limit-requests: 3500        ← Minute limit (RPM)
x-ratelimit-remaining-requests: 35      ← Minute remaining
x-ratelimit-reset-requests: 6m0s        ← Minute reset

x-ratelimit-limit-tokens: 90000         ← Minute limit (TPM)
x-ratelimit-remaining-tokens: 10000     ← Minute remaining
x-ratelimit-reset-tokens: 6m0s          ← Minute reset
```

**What OpenAI Does NOT Send:**
```
x-ratelimit-limit-day: 10000            ← Daily limit (RPD) - MISSING
x-ratelimit-remaining-day: 5000         ← Daily remaining - MISSING
x-ratelimit-reset-day: 12h30m0s         ← Daily reset - MISSING
```

### Why We Can't Monitor What We Can't See

**1. Daily Limits Exist But Are Server-Side Only**
- OpenAI enforces RPD (requests per day) and TPD (tokens per day)
- Tier 2: 10,000 requests/day, 5,000,000 tokens/day
- BUT: These values are NOT exposed in API response headers

**2. Cannot Proactively Monitor**
```python
def _discover_all_limits(self, headers):
    # Finds: x-ratelimit-remaining-requests ✅
    # Finds: x-ratelimit-remaining-tokens ✅
    # Finds: x-ratelimit-remaining-day ❌ (doesn't exist in headers)
```

**3. Cannot Prevent Daily 429s**
- ❌ No visibility into daily usage
- ❌ No way to know how many requests left today
- ❌ Cannot calculate when daily limit will be hit
- ❌ Cannot proactively pause before hitting daily limit

### ✅ Fallback Strategy: Garak's @backoff Decorator

**Daily limits handled reactively (same as before):**

```python
@backoff.on_exception(
    backoff.fibo,
    openai.RateLimitError,  ← Catches daily limit 429s
    max_value=70,
)
def _call_model(self, ...):
    # If daily limit hit → 429 error
    # @backoff waits using Fibonacci sequence
    # Retry after backoff period
```

**This works because:**
- ✅ @backoff is still active in wrapper
- ✅ Handles ANY 429 error (minute or daily)
- ✅ Same behavior as original garak
- ✅ No degradation for daily limit handling

### ℹ️ Edge Case Analysis

**When do users hit daily limits?**

| Scan Type | Requests/Day | Hits Daily Limit? |
|-----------|--------------|-------------------|
| Small scan (10 probes, 100 gen) | ~1,000 | ❌ No (10% of 10k) |
| Medium scan (50 probes, 100 gen) | ~5,000 | ❌ No (50% of 10k) |
| Large scan (all probes, 100 gen) | ~20,000+ | ⚠️ Maybe (200% of 10k) |
| Continuous scanning (24/7) | High | ✅ Yes |

**Reality:** Most users won't hit daily limits in a single scan session

### Option 1: Configuration-Based Tracking (NOT IMPLEMENTED)

**Could implement:**
```python
class OpenAIRatedGenerator(OpenAIGenerator):
    def __init__(self, ...):
        self.daily_request_count = 0
        self.daily_token_count = 0
        self.daily_reset_time = time.time() + 86400

    def _check_daily_limits(self):
        if time.time() > self.daily_reset_time:
            self.daily_request_count = 0
            self.daily_token_count = 0
            self.daily_reset_time = time.time() + 86400

        if self.daily_request_count >= 10000:
            wait_time = self.daily_reset_time - time.time()
            time.sleep(wait_time)
```

**Why NOT implemented:**

1. **Over-Engineered for Edge Case**
   - Most scans won't hit 10,000 requests/day
   - Complex state management for rare scenario
   - Violates CLAUDE.md principle: "No Over Engineering"

2. **State Management Complexity**
   - Need persistent storage (config file or database)
   - Handle process restarts, parallel execution
   - Synchronization across multiple instances
   - Daily reset time zone handling

3. **Limited Accuracy**
   - Can't account for requests made from other clients
   - Can't account for requests before garak started
   - OpenAI's daily window may not align with ours
   - Still need @backoff as fallback anyway

4. **Minimal Benefit**
   - @backoff already handles daily 429s
   - Works same as original garak
   - No user complaints about daily limit handling
   - Edge case doesn't justify complexity

### 📋 Decision Matrix

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| **Reactive (@backoff)** | ✅ Simple<br>✅ Already works<br>✅ No state management | ⚠️ Doesn't prevent daily 429s | ✅ **CURRENT** |
| **Config-based tracking** | ✅ Could prevent some daily 429s | ❌ Complex<br>❌ Inaccurate<br>❌ Edge case<br>❌ Over-engineered | ❌ Rejected |
| **Wait for OpenAI headers** | ✅ Accurate<br>✅ Simple if available | ❌ OpenAI doesn't provide<br>❌ Unknown if/when they will | ⏳ Future |

### 🎯 Conclusion

**Decision:** Defer daily limit tracking until proven user need

**Rationale:**
1. OpenAI doesn't expose daily limits in headers → Cannot monitor proactively
2. @backoff already handles daily 429s reactively → No degradation
3. Most scans won't hit 10,000+ requests/day → Edge case
4. Config-based tracking is over-engineered → Violates design principles
5. Complexity not justified by benefit → YAGNI principle

**Future Path:**
- ✅ If OpenAI adds daily limit headers → Automatically detected (dynamic discovery)
- ✅ If users report frequent daily hits → Revisit config-based approach
- ✅ For now → Keep it simple, focus on minute limits (99% of use cases)
