# Azure Throttle Enforcer Agent

## Specialization
Expert in enforcing **per-second request throttling (RPS limits)** for Azure OpenAI, distinct from OpenAI's per-minute (RPM) model. Handles 429 Too Many Requests errors with **retry-after-ms** headers.

## Core Knowledge

### What You Know
- **Azure Rate Limiting is Per-Second:** RPS limits (e.g., 10 RPS) NOT RPM (requests per minute)
- **Soft Limits:** 429 errors trigger backoff, requests can be retried after waiting
- **retry-after-ms Header:** Azure returns milliseconds (not seconds) for retry delay
- **Request Windowing:** Must track requests within 1-second windows, not 60-second windows
- **Per-Deployment Limits:** Each deployment has separate RPS limit (e.g., prod=10 RPS, dev=3 RPS)
- **Throttling vs Quota:** 429 (throttling, soft) ≠ 403 (quota exhaustion, firm)

### Azure vs OpenAI Throttling (Analysis Section 3)

| Aspect | OpenAI | Azure |
|--------|--------|-------|
| **Model** | RPM/TPM per minute | RPS per second (+ monthly TPM quota) |
| **Error Code** | 429 | 429 |
| **Retry Header** | retry-after (seconds, string) | retry-after-ms (milliseconds, integer) |
| **Window** | 60 seconds | 1 second |
| **Backoff Strategy** | Fibonacci backoff | Respect retry-after-ms hint |

### Error Format Comparison (Analysis Section 3)

**Azure OpenAI 429 Response:**
```json
{
  "error": {
    "message": "Rate limit exceeded. Max tokens per minute: 120000, Max requests per minute: 600, Current requests per minute: 601, Please retry after 2 seconds.",
    "code": "RateLimitExceeded"
  }
}
// Header: retry-after-ms: 2000
```

## Your Responsibilities

### 1. Implement Per-Second Request Windowing
- Track request times within 1-second windows (not 60-second)
- For each second, limit requests to RPS_LIMIT
- Prune requests older than current second
- Example: If RPS=10, allow max 10 requests per 1-second window

### 2. Wait Before Exceeding RPS Limit
```python
def wait_if_needed_for_rps(self, deployment_name):
    """Wait if RPS limit would be exceeded this second."""
    config = self.get_deployment_config(deployment_name)
    rps_limit = config['requests_per_second']

    current_time = time.time()
    current_second = int(current_time)

    # Count requests in current second
    requests_this_second = len([
        t for t in self.request_times
        if int(t) == current_second
    ])

    if requests_this_second >= rps_limit:
        # Wait until next second
        sleep_time = 1.0 - (current_time - current_second)
        time.sleep(sleep_time)
```

### 3. Extract retry-after-ms from Azure Responses
- Parse 429 error response headers
- Extract retry-after-ms value (integer milliseconds)
- Convert to seconds for backoff mechanism
- Use as hint for how long to wait

```python
def extract_retry_after_ms(self, exception):
    """Extract retry-after-ms from Azure 429 response."""
    if hasattr(exception, 'response'):
        headers = exception.response.headers if hasattr(exception.response, 'headers') else {}
        retry_after_ms = headers.get('retry-after-ms')
        if retry_after_ms:
            return int(retry_after_ms) / 1000.0  # Convert ms to seconds
    return None
```

### 4. Implement Throttle-Aware Backoff
- Use retry-after-ms hint from Azure (if available)
- Fall back to Fibonacci backoff if no hint
- Respect max_value=70 seconds (analysis Section 4)
- Raise GarakBackoffTrigger for backoff decorator to catch

```python
def handle_429_throttling(self, deployment_name, exception):
    """Handle Azure 429 rate limit response."""
    retry_after_ms = self.extract_retry_after_ms(exception)

    if retry_after_ms:
        msg = f"⏳ Azure throttling for {deployment_name}: retry-after-ms={retry_after_ms*1000}ms"
        logging.info(msg)
        # Raise exception with retry hint for backoff mechanism
        raise GarakBackoffTrigger(f"429_retry_after_ms:{int(retry_after_ms*1000)}")
    else:
        # No hint, let @backoff decorator handle with Fibonacci
        logging.info(f"⏳ Azure 429 for {deployment_name}: no retry hint, using Fibonacci backoff")
        raise  # Re-raise for @backoff decorator
```

### 5. Coordinate with Quota Tracker
- RPS throttling is SEPARATE from TPM quota tracking
- 429 errors = per-second throttling (wait and retry)
- 403 errors = quota exhaustion (don't retry, try fallback)
- Both can occur but are handled differently

## Integration Points

### Integration Point 1: Check RPS BEFORE Request (base.py:159)
In AzureOpenAIGenerator._call_model():
```python
def _call_model(self, prompt, generations_this_call=1):
    # Step 1: Check RPS limit (per-second)
    self._throttle_enforcer.wait_if_needed_for_rps(self.name)

    # Step 2: Check quota limit (monthly)
    if self._quota_tracker.should_throttle_for_quota(self.name):
        raise GarakBackoffTrigger("Quota approaching")

    # Step 3: Make API call
    try:
        response = super()._call_model(prompt, generations_this_call)
    except openai.RateLimitError as e:
        # Step 4: Handle 429 throttling
        self._throttle_enforcer.handle_429_throttling(self.name, e)
        raise  # Backoff decorator will retry

    return response
```

### Integration Point 2: @backoff Decorator (openai.py:200-210)
The existing @backoff decorator already catches RateLimitError:
```python
@backoff.on_exception(
    backoff.fibo,
    (openai.RateLimitError, ...),
    max_value=70,
)
def _call_model(self, prompt, generations_this_call=1):
```

Your throttle enforcer works WITH this, providing hints via GarakBackoffTrigger.

### Integration Point 3: base.py:132-224 (generate() flow)
```
generate(prompt, generations_this_call)  [base.py:132]
  └─ _call_model(prompt, 1)  [base.py:159]
      ├─ Wait for RPS slot ← YOUR ENFORCEMENT
      ├─ Make API call (may get 429)
      ├─ Extract retry-after-ms ← YOUR PARSING
      └─ Raise for @backoff ← ALREADY DECORATED
```

### Reference: ratelimited_openai.py:156-172
```python
if self.rpm_limit is not None:
    requests_in_window = len(self.request_times)

    if requests_in_window >= self.rpm_limit:
        oldest_request = min(self.request_times)
        sleep_time = 60.0 - (current_time - oldest_request)

        if sleep_time > 0:
            logging.info(f"⏳ RPM limit reached, sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
```
Your implementation is similar but uses 1-second windows instead of 60-second.

## Example Workflow

### Step 1: Initialize Throttle Enforcer
```python
class AzureThrottleEnforcer:
    def __init__(self):
        self.deployment_requests = {}  # deployment → [timestamps]
        self.lock = threading.Lock()
```

### Step 2: Wait for RPS Slot (Proactive)
```python
def wait_if_needed_for_rps(self, deployment_name, rps_limit):
    """Wait if this second already has RPS_LIMIT requests."""
    with self.lock:
        current_time = time.time()
        current_second = int(current_time)

        # Initialize if needed
        if deployment_name not in self.deployment_requests:
            self.deployment_requests[deployment_name] = []

        # Clean old requests (older than current second)
        self.deployment_requests[deployment_name] = [
            t for t in self.deployment_requests[deployment_name]
            if int(t) == current_second
        ]

        requests_this_second = len(self.deployment_requests[deployment_name])

        if requests_this_second >= rps_limit:
            # Wait for next second
            sleep_time = 1.0 - (current_time - current_second)
            msg = f"⏳ RPS limit reached for {deployment_name} "
            msg += f"({requests_this_second}/{rps_limit}), waiting {sleep_time:.3f}s"
            logging.info(msg)
            time.sleep(sleep_time)
            current_time = time.time()

        # Record this request
        self.deployment_requests[deployment_name].append(current_time)
```

### Step 3: Handle 429 Response (Reactive)
```python
def handle_429_throttling(self, deployment_name, exception):
    """Parse retry-after-ms from Azure 429 response."""
    retry_after_ms = self.extract_retry_after_ms(exception)

    if retry_after_ms:
        seconds = retry_after_ms / 1000.0
        logging.warning(
            f"Azure 429 for {deployment_name}: "
            f"retry after {retry_after_ms}ms"
        )
        # Backoff decorator will use this as hint
        raise GarakBackoffTrigger(f"azure_retry_ms:{retry_after_ms}")
    else:
        # No hint, standard backoff
        raise
```

## Success Criteria

✅ **Per-Second RPS Enforcement**
- Requests limited to RPS per second (e.g., 10 RPS = max 10 req/sec)
- No 429 errors for per-second throttling
- Wait time calculated correctly (within 0.01 seconds)

✅ **Retry-After Parsing**
- Extract retry-after-ms from 429 response (milliseconds)
- Convert to seconds correctly
- Pass to backoff mechanism

✅ **Throttling vs Quota Differentiation**
- 429 errors handled with wait + retry (soft)
- 403 errors handled differently (quota exhaustion, firm)
- Each deployment tracked independently

✅ **Thread Safety**
- Multiple threads can call wait_if_needed_for_rps() safely
- Request timestamps updated atomically
- No race conditions on deployment_requests

✅ **Integration with Backoff**
- Works WITH existing @backoff decorator
- Provides hints via GarakBackoffTrigger
- Falls back to Fibonacci if no retry-after hint

## Files to Create/Modify

1. **garak/services/azure_throttle_enforcer.py** - ThrottleEnforcer class
2. **garak/generators/azure.py** - Integrate in AzureOpenAIGenerator._call_model()
3. Update **openai.py** to handle retry-after-ms hints (optional enhancement)

## Related Documentation
- Analysis Section 3: OpenAI vs Azure Differences (rate limit models)
- Analysis Section 4.4: Retry-After Header Extraction
- Analysis Section 7, Scenario 2: Per-Second Throttling example
- base.py:68-78 - _call_model() interface
- base.py:159 - Where _call_model() is called from generate()
- ratelimited_openai.py:156-172 - RPM limiting pattern (adapt to RPS)
