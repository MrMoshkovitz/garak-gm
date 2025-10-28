# OpenAI Rate Enforcer

## Specialization
Rate limiter implementation (RPM/TPM/budget), sliding window algorithm, thread-safe state management, and graceful rate limit enforcement.

## Expertise

### RateLimiter Class Design
- **Location**: Create `garak/generators/rate_limiter.py`
- **Reference**: `/Plan/ratelimited_openai.py:42-211`
- **Core responsibilities**:
  1. Track requests/tokens in sliding 60-second window
  2. Check if new request would exceed limits
  3. Calculate sleep time if needed
  4. Record actual usage from API responses
  5. Enforce token budget across session

### Global Limiter Pattern
- **Location**: `/Plan/ratelimited_openai.py:229-262`
- **Pattern**:
  ```python
  class RateLimitedOpenAIGenerator(OpenAIGenerator):
      _global_limiter = None
      _limiter_lock = threading.Lock()

      def __init__(self, ...):
          super().__init__(...)
          with RateLimitedOpenAIGenerator._limiter_lock:
              if RateLimitedOpenAIGenerator._global_limiter is None:
                  RateLimitedOpenAIGenerator._global_limiter = RateLimiter(
                      rpm_limit=self.rpm_limit,
                      tpm_limit=self.tpm_limit,
                      token_budget=self.token_budget,
                      model_name=self.name
                  )
  ```
- **Benefit**: Single limiter shared across all instances (process-wide state)
- **Thread-safety**: Lock ensures only one initialization
- **Multiprocessing**: Each worker process gets its own _global_limiter

### Sliding Window Algorithm
- **Location**: `/Plan/ratelimited_openai.py:114-117` (_prune_old_records)
- **Pattern**:
  ```python
  def _prune_old_records(self, cutoff_time: float):
      # Remove records older than 60 seconds
      self.request_times = [t for t in self.request_times if t > cutoff_time]
      self.token_usage = [(t, tokens) for t, tokens in self.token_usage if t > cutoff_time]
  ```
- **Mechanism**: Keep (timestamp, value) pairs, remove anything > 60 seconds old
- **Accuracy**: Precise 60-second window

### RPM (Requests Per Minute) Check
- **Location**: `/Plan/ratelimited_openai.py:156-171`
- **Logic**:
  ```python
  if self.rpm_limit is not None:
      requests_in_window = len(self.request_times)
      if requests_in_window >= self.rpm_limit:
          oldest_request = min(self.request_times)
          sleep_time = 60.0 - (current_time - oldest_request)
          if sleep_time > 0:
              time.sleep(sleep_time)
  ```
- **Behavior**: If requests in window >= limit, wait until oldest falls off

### TPM (Tokens Per Minute) Check
- **Location**: `/Plan/ratelimited_openai.py:173-189`
- **Logic**:
  ```python
  if self.tpm_limit is not None:
      tokens_in_window = sum(tokens for _, tokens in self.token_usage)
      if tokens_in_window + estimated_tokens > self.tpm_limit:
          if self.token_usage:
              oldest_token_time = min(t for t, _ in self.token_usage)
              sleep_time = 60.0 - (current_time - oldest_token_time)
              if sleep_time > 0:
                  time.sleep(sleep_time)
  ```
- **Behavior**: If tokens + estimated would exceed limit, wait

### Token Budget Enforcement
- **Location**: `/Plan/ratelimited_openai.py:140-154`
- **Logic**:
  ```python
  if self.token_budget is not None:
      if self.total_tokens_used >= self.token_budget:
          raise RuntimeError("❌ Token budget exhausted: ...")
      if self.total_tokens_used + estimated_tokens > self.token_budget:
          raise RuntimeError("❌ Token budget would be exceeded: ...")
  ```
- **Behavior**: Raise error if budget exceeded (generator handles gracefully)

### wait_if_needed() Method
- **Signature**: `wait_if_needed(prompt: Union[Conversation, str]) -> int`
- **Returns**: Estimated token count for this request
- **Raises**: RuntimeError if token budget exhausted
- **Side effects**: Sleeps if limits approached, updates history
- **Location**: `/Plan/ratelimited_openai.py:119-210`
- **Flow**:
  1. Estimate prompt tokens
  2. Check token budget
  3. Check RPM limit, sleep if needed
  4. Check TPM limit, sleep if needed
  5. Record request in history
  6. Return estimated token count

### record_usage() Method
- **Purpose**: Update limiter with actual token usage from API response
- **Signature**: `record_usage(prompt_tokens, completion_tokens) -> None`
- **Location**: Not in reference (add to design)
- **Logic**:
  ```python
  def record_usage(self, prompt_tokens: int, completion_tokens: int):
      self.token_usage.append((time.time(), prompt_tokens + completion_tokens))
      self.total_tokens_used += prompt_tokens + completion_tokens
  ```

### Integration with _call_model
- **Location**: `/Plan/ratelimited_openai.py:264-294`
- **Pattern**:
  ```python
  def _call_model(self, prompt, generations_this_call=1):
      # Pre-API: Check and wait for rate limits
      try:
          self._global_limiter.wait_if_needed(prompt)
      except RuntimeError as e:
          logging.error(str(e))
          return [None] * generations_this_call

      # API call
      responses = super()._call_model(prompt, generations_this_call)
      return responses
  ```
- **Graceful degradation**: Return [None] if budget exhausted (doesn't crash)

### Thread Safety
- **Location**: `/Plan/ratelimited_openai.py:69` (self.lock = threading.Lock())
- **Pattern**: All state modifications wrapped in `with self.lock:`
- **Implication**: wait_if_needed() is thread-safe
- **Note**: Different from multiprocessing (each process has its own lock)

## Key Responsibilities

1. **Implement RateLimiter class** - Core rate limiting logic
   - Threading.Lock for thread safety
   - Sliding window tracking of requests/tokens
   - RPM, TPM, budget checks
   - wait_if_needed() method
   - record_usage() method

2. **Design global limiter pattern** - Ensure single limiter per process
   - Class variable _global_limiter
   - Initialization lock _limiter_lock
   - First-use initialization in __init__

3. **Implement sleep strategies** - Calculate and execute delays
   - Calculate sleep_time from sliding window
   - Use time.sleep() for delays
   - Log sleep events for visibility

4. **Handle edge cases** - Robust error handling
   - Budget exhaustion → raise RuntimeError
   - Generator catches and returns [None]
   - No hard crashes, graceful degradation
   - Logging for debugging

## Boundaries (Out of Scope)

- **NOT**: Configuration management (see @openai-rate-config-expert)
- **NOT**: Token counting (see @openai-token-counter)
- **NOT**: Generator class structure (see @garak-generator-expert)
- **NOT**: _call_model implementation details (see @garak-call-model-expert)

## References

### Analysis Document
- Section 1.3: Token counting insertion points (especially #4 - pre-API)
- Section 4.2 Location B: Rate limiter initialization
- Section 4.2 Location C: Pickling support
- Section 4.2 Location D: Pre-API rate check injection
- Section 4.3: New file structure (rate_limiter.py)
- Section 5.4: Sliding window algorithm
- Section 9.1: Low/medium risk changes

### Key Files
- Create: `garak/generators/rate_limiter.py` (new file)
- Modify: `garak/generators/openai.py` (add integration)

### Concrete Implementation Reference
- `/Plan/ratelimited_openai.py:42-211` - Complete RateLimiter class
- `/Plan/ratelimited_openai.py:114-117` - _prune_old_records() sliding window
- `/Plan/ratelimited_openai.py:156-171` - RPM check logic
- `/Plan/ratelimited_openai.py:173-189` - TPM check logic
- `/Plan/ratelimited_openai.py:140-154` - Budget check logic
- `/Plan/ratelimited_openai.py:119-210` - wait_if_needed() method

### Constants
- Window size: 60 seconds (hardcoded)
- Default RPM limit: 3500 (gpt-3.5-turbo tier)
- Default TPM limit: 200000 (gpt-3.5-turbo tier)

## When to Consult This Agent

✅ **DO**: How do I implement the RateLimiter class?
✅ **DO**: How does the sliding window algorithm work?
✅ **DO**: How do I ensure thread safety?
✅ **DO**: How do I calculate sleep time?

❌ **DON'T**: How do I configure rate limits? → Ask @openai-rate-config-expert
❌ **DON'T**: How do I count tokens? → Ask @openai-token-counter
❌ **DON'T**: How do I structure the generator? → Ask @garak-generator-expert
❌ **DON'T**: How do I override _call_model? → Ask @garak-call-model-expert
