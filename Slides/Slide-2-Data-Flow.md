# Slide 2: Data Flow - Reactive Approach (Before)

## Request Flow in Original Implementation

### Complete Flow Diagram

```
Probe
  ↓
_execute_attempt (probes/base.py)
  ↓
_call_model() (generators/openai.py)
  ↓
generator.create(**create_args)  ← Standard OpenAI SDK call
  ↓
┌─────────────────────────┐
│   API Response          │
│                         │
│   Headers (IGNORED):    │
│   x-ratelimit-limit-    │
│   x-ratelimit-remaining-│
│   x-ratelimit-reset-    │
│                         │
│   Body:                 │
│   {choices: [...]}      │
└─────────────────────────┘
  ↓
Return [Message(c.text)]  ← Headers discarded here
  ↓
IF 429 Error:
  @backoff decorator catches → Fibonacci wait → Retry
```

### Key Issues

**1. Headers Available But Ignored**
```python
# Standard SDK response object
response = self.generator.create(**create_args)

# This returns parsed response only
# Headers are in response object but never accessed
```

**2. No Rate Limit Tracking**
- RPM (requests per minute): ❌ Unknown
- TPM (tokens per minute): ❌ Unknown
- Time to reset: ❌ Unknown
- Usage percentage: ❌ Unknown

**3. Reactive Error Handling Only**
```python
@backoff.on_exception(backoff.fibo, openai.RateLimitError, ...)
def _call_model(...):
    # Only handles errors AFTER they occur
    # Cannot prevent errors from happening
```

### The Core Problem

**Rate limit information flows through the system but is never captured:**

```
OpenAI API → Response Headers → SDK Response Object → DISCARDED → 429 Error → React
                    ↓
              [Lost Information]
```

### What We're Missing

| Information | Available in Headers? | Used by Garak? |
|-------------|----------------------|----------------|
| Requests remaining | ✅ Yes | ❌ No |
| Tokens remaining | ✅ Yes | ❌ No |
| Reset time | ✅ Yes | ❌ No |
| Limit values | ✅ Yes | ❌ No |
| Usage percentage | ❓ Can be calculated | ❌ No |

**Result:** Blind execution until hitting 429 errors
