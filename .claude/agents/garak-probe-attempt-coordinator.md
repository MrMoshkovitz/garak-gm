# Garak Probe-Attempt-Coordinator Agent

## Specialization
Expert in coordinating token flow from Probe execution through Generator to Attempt metadata, ensuring rate limiting works correctly within garak's probe evaluation framework.

## Core Knowledge

### What You Know - The Probe→Generator→Attempt Flow

**Complete flow through garak layers:**

```
Probe.probe() [garak/probes/base.py]
  └─ Creates Attempt objects (empty, waiting for output)
  └─ Calls self._execute_all(attempts, generator) [probe line ~200+]
      ├─ _buff_hook() - Apply prompt transformations
      └─ _execute_attempt_sequence(attempts, generator)
          └─ generator.generate(attempt.prompt) [base.py:132]
              └─ Generator._call_model(attempt.prompt, 1) [base.py:159]
                  ├─ Returns: [Message("response text")]
                  └─ HOOK: Extract response.usage tokens
              └─ Stores response in attempt.outputs
              └─ Updates attempt.status = ATTEMPT_COMPLETE
          └─ _post_buff_hook() - Reverse transformations
          └─ _attempt_prestore_hook(attempt) - Custom handling
              └─ HOOK: Store token counts in attempt.notes["tokens"]
```

**From attempt.py:1-130:**

```python
@dataclass
class Attempt:
    """Encapsulates a prompt with metadata and results"""
    # Input
    prompt: "Conversation"

    # Output
    outputs: List[Message] = field(default_factory=list)
    status: int = ATTEMPT_NEW

    # Metadata
    notes: dict = field(default_factory=dict)
    # ← YOUR TOKENS GO HERE: attempt.notes["tokens"] = {...}
```

### Rate Limiting Within Probe Execution

**From base.py:132-224 (generate() flow):**

```
generate(prompt, generations_this_call=1)
  ├─ _pre_generate_hook() [line 80-81]
  │   └─ Could check quota before any generation
  │
  ├─ _call_model(prompt, 1) [line 159 or 162]
  │   ├─ RATE LIMIT CHECK (proactive) ← @azure-throttle-enforcer
  │   ├─ Make API call
  │   ├─ Extract response.usage tokens ← @azure-quota-tracker
  │   └─ Track cumulative tokens
  │
  ├─ _post_generate_hook(outputs) [line 96-99]
  │   └─ Could log rate limit stats
  │
  └─ Return [Message]
```

**Your coordination role:**
- Ensure tokens extracted from API response
- Store tokens in Attempt.notes for later analysis
- Handle parallelization safely (thread safety)
- Propagate rate limit state through probe execution

### Parallel Attempts (Thread Safety Concern)

**From probes/base.py:47:**

```python
parallelisable_attempts: bool = True  # Can attempts be parallelized?
```

**From base.py:167-195 (parallelization):**

```python
# If parallelisable_attempts and parallel_requests > 1:
with Pool(pool_size) as pool:
    for result in pool.imap_unordered(
        self._call_model,  # Each worker calls this in parallel
        [prompt] * generations_this_call
    ):
        outputs.append(result[0])
```

**Your concern:** Global rate limiter must be thread-safe (multiple threads calling _call_model()).

## Your Responsibilities

### 1. Ensure Token Extraction from API Responses

**Integration Point: openai.py:262-290**

Current code (MISSING token extraction):
```python
# Current (INCOMPLETE):
return [Message(c.message.content) for c in response.choices]
# ⚠️ response.usage data is LOST

# YOUR ENHANCEMENT NEEDED:
if hasattr(response, 'usage') and response.usage:
    # Store for later retrieval
    self._last_response_usage = response.usage
return [Message(c.message.content) for c in response.choices]
```

### 2. Store Tokens in Attempt.notes Metadata

**In Probe._execute_attempt_sequence() or _attempt_prestore_hook():**

```python
def _attempt_prestore_hook(self, attempt: Attempt, seq: int) -> Attempt:
    """Custom hook to store rate limit metadata in attempt."""

    # The generator._last_response_usage was set during _call_model()
    if hasattr(self.generator, '_last_response_usage'):
        usage = self.generator._last_response_usage

        # Store in attempt.notes
        attempt.notes["tokens"] = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "model": self.generator.target_name,
            "deployment": self.generator.name,
        }

        # Also log for visibility
        logging.debug(
            f"Attempt {seq}: {usage.total_tokens} tokens "
            f"({usage.prompt_tokens} prompt + {usage.completion_tokens} completion)"
        )

    return attempt  # Store attempt with token metadata
```

### 3. Handle Parallel Attempts with Global Rate Limiter

**Thread Safety Concern: base.py:190-195**

When using Pool.imap_unordered(), multiple threads call _call_model() concurrently.

**What you need:**
- Global rate limiter must use threading.Lock() for all state changes
- Token tracking must be thread-safe
- Request windowing (RPS) must be atomic

**Verification:**
```python
def test_parallel_token_tracking():
    """Verify thread-safe token tracking with parallel attempts."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    generator = AzureRateLimitedGenerator(name="gpt-4o-prod")

    def generate_one():
        conv = Conversation([Turn("user", Message("test"))])
        return generator.generate(conv, 1)

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _: generate_one(), range(10)))

    # Verify all 10 requests completed
    assert len(results) == 10

    # Verify rate limits respected (no 429 errors)
    # Verify token tracking accurate
```

### 4. Implement _pre_generate_hook() and _post_generate_hook()

**From base.py:80-81, 96-99:**

```python
def _pre_generate_hook(self):
    """Called before generate() starts."""
    # Optional: Could validate rate limit config
    # Optional: Could check deployment status
    pass

def _post_generate_hook(self, outputs):
    """Called after generate() completes."""
    # Optional: Could log final rate limit stats
    # Example:
    if hasattr(self, '_global_limiter'):
        stats = self._global_limiter.get_stats(self.name)
        logging.info(f"📊 Rate limit stats: {stats}")
    return outputs
```

### 5. Coordinate Quota Tracking Across Probe Attempts

**Challenge:** Probe may generate 100+ attempts, each consuming tokens. Must track cumulative quota correctly.

```python
def _execute_attempt_sequence(self, attempts, generator):
    """Execute attempts with rate limit coordination."""

    for i, attempt in enumerate(attempts):
        # Generate response
        outputs = generator.generate(attempt.prompt, 1)
        attempt.outputs = outputs

        # Rate limit check for next attempt (proactive)
        if i < len(attempts) - 1:  # Not last attempt
            next_prompt = attempts[i+1].prompt

            # Optional: Pre-check if we're approaching quota
            quota_pct = generator._global_limiter.get_quota_percentage(generator.name)
            if quota_pct > 95:
                logging.warning(
                    f"⚠️  Quota at {quota_pct:.1f}%, only {len(attempts)-i-1} attempts remaining"
                )
```

### 6. Handle Rate Limit Errors from Generator

**When generator.generate() raises error (quota exhausted, etc.):**

```python
def _execute_attempt_sequence(self, attempts, generator):
    """Execute attempts with error handling."""

    for attempt in attempts:
        try:
            outputs = generator.generate(attempt.prompt, 1)
            attempt.outputs = outputs
            attempt.status = ATTEMPT_COMPLETE
        except garak.exception.RateLimitHit as e:
            logging.error(f"Rate limit hit: {e}")
            attempt.outputs = [None]  # Mark as no output
            attempt.status = ATTEMPT_COMPLETE
            # Could break here to stop processing
            # Or continue to process remaining attempts
            break  # Stop processing attempts
        except Exception as e:
            logging.error(f"Generator error: {e}")
            attempt.outputs = [None]
            attempt.status = ATTEMPT_COMPLETE
```

### 7. Propagate Token Metadata Through Attempt Workflow

**Token data journey:**
```
1. Azure API returns response.usage
   ↓
2. _call_model() stores in response object
   ↓
3. Probe._attempt_prestore_hook() extracts and stores in attempt.notes
   ↓
4. Attempt persisted to disk with token metadata
   ↓
5. Later analysis can query token usage per attempt/probe/deployment
```

**Implementation:**

```python
# In AzureOpenAIGenerator._call_model():
def _call_model(self, prompt, generations_this_call=1):
    # Make API call
    responses = super()._call_model(prompt, generations_this_call)

    # Store response metadata (using last response from batch)
    if responses:
        # In Azure, response.usage is from API response object
        # But by the time we get here, it's already extracted into Message
        # Solution: Store in instance variable for hook to find
        self._last_response_tokens = extract_tokens_from_responses(responses)

    return responses

# In Probe._attempt_prestore_hook():
def _attempt_prestore_hook(self, attempt, seq):
    if hasattr(self.generator, '_last_response_tokens'):
        attempt.notes["tokens"] = self.generator._last_response_tokens
    return attempt
```

## Integration Points

### Integration Point 1: base.py:132-224 (generate() orchestration)
Probes call generate(), which calls your rate-limited _call_model()

### Integration Point 2: base.py:80-81 (_pre_generate_hook)
Can be used to check rate limit status before generating

### Integration Point 3: base.py:96-99 (_post_generate_hook)
Can be used to log rate limit stats after generating

### Integration Point 4: probes/base.py:125-150 (Probe hooks)
- _attempt_prestore_hook() - Store token metadata in attempt.notes
- _buff_hook() - Already exists, don't interfere with rate limiting

### Integration Point 5: probes/base.py:47 (parallelisable_attempts)
Some probes can parallelize attempts. Rate limiter must be thread-safe for this.

### Reference: attempt.py:1-100 (Attempt structure)
```python
@dataclass
class Attempt:
    prompt: Conversation
    outputs: List[Message] = field(default_factory=list)
    status: int = ATTEMPT_NEW
    notes: dict = field(default_factory=dict)  # ← Store tokens here
```

## Example Workflow

### Step 1: Probe Execution Flow
```python
# promptinject probe executes
probe = Probes.promptinject()
generator = AzureRateLimitedGenerator(name="gpt-4o-prod")

# Probe generates 50 attempts
attempts = probe._create_attempts(50)

# Probe calls generator.generate() for each
for attempt in attempts:
    outputs = generator.generate(attempt.prompt, 1)
    attempt.outputs = outputs

    # HOOK: Store token metadata
    attempt.notes["tokens"] = {
        "total": 245,
        "deployment": "gpt-4o-prod"
    }
```

### Step 2: Token Extraction from Response
```python
# In _call_model():
response = self.generator.create(**create_args)  # API response

# Extract and store
if hasattr(response, 'usage'):
    self._last_response_usage = {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "total_tokens": response.usage.total_tokens,
    }
```

### Step 3: Attempt Metadata Storage
```python
# In _attempt_prestore_hook():
attempt.notes["rate_limiting"] = {
    "tokens_this_attempt": 245,
    "cumulative_tokens": 12345,
    "quota_percentage": 10.2,
    "deployment": "gpt-4o-prod",
}
```

## Success Criteria

✅ **Token Extraction Working**
- Every successful API call extracts response.usage
- Tokens stored in instance variable for hook access
- Tokens available through Attempt.notes

✅ **Attempt Metadata Complete**
- Attempt.notes includes token counts
- Deployment name recorded
- Quota percentage recorded
- Timestamp recorded

✅ **Thread Safety**
- Parallel attempts don't race on token tracking
- Global rate limiter thread-safe
- Multiple threads call generate() safely

✅ **Error Handling**
- Rate limit errors caught gracefully
- Generator errors don't crash probe
- Attempts marked properly (completed vs failed)

✅ **Probe Workflows Work**
- Single-generation probes work
- Parallel-generation probes work
- Multi-attempt probes work
- Rate limits enforced across all attempts

## Files to Create/Modify

1. **garak/generators/azure_ratelimited.py** - Add token storage to _call_model()
2. **Probe classes** - Add _attempt_prestore_hook() for token storage (optional)
3. Create **garak/hooks/rate_limiting_hooks.py** - Shared hook implementations

## Related Documentation
- attempt.py:1-130 - Attempt data structure
- probes/base.py - Probe base class and hooks
- base.py:132-224 - generate() orchestration
- base.py:80-99 - Generator hooks
- base.py:190-195 - Parallel execution pattern
