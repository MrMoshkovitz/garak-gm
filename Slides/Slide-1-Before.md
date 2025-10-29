# Slide 1: Reactive Rate Limiting (Before Implementation)

## The Problem: Reactive-Only Approach

### How Garak Handled Rate Limits

**Location:** `garak/generators/openai.py` lines 200-210

**Mechanism:** `@backoff` decorator only
```python
@backoff.on_exception(
    backoff.fibo,  # Fibonacci backoff sequence
    (
        openai.RateLimitError,
        openai.InternalServerError,
        ...
    ),
    max_value=70,
)
def _call_model(self, prompt, generations_this_call=1):
    response = self.generator.create(**create_args)
    return response
```

### The Reactive Flow

```
Request → API Call → 429 Error Occurs → @backoff Triggers → Wait → Retry
```

### Key Characteristics

❌ **No Proactive Monitoring**
- Rate limit headers completely ignored
- No visibility into current usage
- Cannot predict when limits will be hit

❌ **Reactive Only**
- Fibonacci backoff triggers AFTER 429 errors
- Waits: 1s, 1s, 2s, 3s, 5s, 8s, 13s, 21s... up to 70s
- Each 429 error disrupts scan progress

❌ **Wasteful**
- Failed API calls still count against rate limits
- Lost time on requests that will be rejected
- No way to optimize request timing

### Impact on Scans

- 🛑 **Disrupted execution** - Pauses every time limit is hit
- ⏰ **Wasted time** - Backoff delays pile up quickly
- 📉 **Inefficient** - No optimization of request rate
- 🔇 **No visibility** - Users don't know how close they are to limits
