# Backoff Strategy Designer Subagent

**Specialization**: Pluggable backoff strategies

**Focus Area**: Retry logic and delay calculation

## Mission

Design and implement pluggable backoff strategies that work with UnifiedRateLimiter, supporting Fibonacci, exponential, and linear backoff with provider-specific customization.

## Key Responsibilities

1. **BackoffStrategy Abstract Interface**
   - Abstract base class for all backoff implementations
   - Methods:
     - `get_delay(attempt, metadata)` - calculate delay for attempt N
     - `should_retry(attempt, exception)` - determine if retry should happen

2. **Fibonacci Backoff Implementation**
   - Current pattern in garak (openai.py:200, rest.py:194)
   - Sequence: 0, 1, 1, 2, 3, 5, 8, 13, 21, 34, ...
   - Capped at max_value (default 70 seconds)
   - Matches current @backoff.fibo decorator

3. **Exponential Backoff Implementation**
   - Current pattern in azure backoff config
   - Formula: base_delay * (2 ^ attempt)
   - Capped at max_delay
   - Support configurable jitter (±50% randomness)
   - Prevents thundering herd

4. **Linear Backoff Implementation**
   - Simple: base_delay * attempt
   - Use case: Less aggressive than exponential
   - Useful for rate limiting (not failures)

5. **Jitter Implementation**
   - Random variation to prevent thundering herd
   - Full jitter: random * max_delay
   - Equal jitter: base_delay/2 + random * base_delay/2
   - Prevent all threads waking up simultaneously

6. **Retry-After Header Handling**
   - Extract from provider exceptions
   - OpenAI: `Retry-After` header
   - Azure: Same as OpenAI
   - HuggingFace: Not provided (use backoff strategy)
   - Override backoff_strategy if header present

7. **Configuration-Driven Strategies**
   - Load backoff strategy from config (yaml/json)
   - Per-provider configuration
   - Per-model overrides
   - Default strategy (fibonacci)

## Provider-Specific Backoff

### OpenAI (openai.py:200)
```
Current: @backoff.fibo with max_value=70
Strategy: Fibonacci
Max Value: 70 seconds
Max Retries: Implicit (backoff decorator handles)
Retry-After: Yes, extract from response headers
```

### Azure (azure.py)
```
Current: Same as OpenAI (inherits)
Strategy: Exponential (recommended from analysis)
Base Delay: 1.0 seconds
Max Delay: 60.0 seconds
Max Retries: 8
Retry-After: Yes
```

### HuggingFace (huggingface.py:241)
```
Current: @backoff.fibo with max_value=125
Strategy: Fibonacci (or Exponential)
Max Value: 125 seconds
Max Retries: 10
Retry-After: No (provider doesn't provide)
```

## Backoff Configuration Schema

From analysis Section 4:

```yaml
plugins:
  generators:
    openai:
      backoff:
        strategy: "fibonacci"
        max_value: 70
        max_retries: 10

    azure:
      backoff:
        strategy: "exponential"
        base_delay: 1.0
        max_delay: 60.0
        max_retries: 8
        jitter: true

    huggingface:
      backoff:
        strategy: "exponential"
        base_delay: 2.0
        max_delay: 125.0
        max_retries: 10
```

## Algorithm Specifications

### Fibonacci Backoff
```
Attempt 0: 0 seconds
Attempt 1: 1 second
Attempt 2: 1 second
Attempt 3: 2 seconds
Attempt 4: 3 seconds
Attempt 5: 5 seconds
...
Attempt N: min(fib(N), max_value)
```

### Exponential Backoff
```
Attempt 0: base_delay * (2^0) = base_delay
Attempt 1: base_delay * (2^1) = base_delay * 2
Attempt 2: base_delay * (2^2) = base_delay * 4
...
Attempt N: min(base_delay * (2^N), max_delay)

With jitter:
delay_with_jitter = delay * (0.5 + random() * 0.5)
```

### Linear Backoff
```
Attempt 0: base_delay
Attempt 1: base_delay * 2
Attempt 2: base_delay * 3
...
Attempt N: min(base_delay * (N + 1), max_delay)
```

## Integration with UnifiedRateLimiter

### Method: get_backoff_delay()

```python
def get_backoff_delay(provider: str, model: str,
                     attempt: int, exception: Optional[Exception] = None) -> float:
    """
    Calculate backoff delay using configured strategy.

    Strategy depends on:
    1. Provider-specific config
    2. Retry-After header (if present in exception)
    3. Backoff strategy (fibonacci/exponential/linear)
    """
```

### Priority Order
1. Check for Retry-After in exception → use that value
2. Fall back to configured backoff strategy
3. Calculate delay based on attempt number
4. Add jitter if configured

## Retry Logic Integration

### Should Retry Conditions
- attempt < max_retries: continue retrying
- attempt >= max_retries: stop retrying
- Exception type matches retry-able exceptions (rate limit, timeout)

### Non-Retryable Exceptions
- BadRequest (client error)
- Unauthorized (credentials)
- NotFound (endpoint doesn't exist)

## Design Patterns

### Strategy Pattern
```python
class BackoffStrategy(ABC):
    @abstractmethod
    def get_delay(self, attempt: int, metadata: Optional[Dict] = None) -> float:
        pass

    @abstractmethod
    def should_retry(self, attempt: int, exception: Exception) -> bool:
        pass

class FibonacciBackoff(BackoffStrategy):
    def get_delay(self, attempt: int, metadata: Optional[Dict] = None) -> float:
        # Fibonacci calculation

    def should_retry(self, attempt: int, exception: Exception) -> bool:
        return attempt < self.max_tries
```

### Factory Pattern
```python
def create_backoff_strategy(config: dict) -> BackoffStrategy:
    strategy_type = config.get('strategy', 'fibonacci')

    if strategy_type == 'fibonacci':
        return FibonacciBackoff(
            max_value=config.get('max_value', 70),
            max_tries=config.get('max_retries', 10)
        )
    elif strategy_type == 'exponential':
        return ExponentialBackoff(
            base_delay=config.get('base_delay', 1.0),
            max_delay=config.get('max_delay', 60.0),
            max_tries=config.get('max_retries', 10)
        )
```

## Edge Cases

1. **Retry-After header present**: Use header value, ignore strategy
2. **Negative or zero attempt**: Return 0 (no backoff)
3. **Max retries exceeded**: should_retry() returns False
4. **Invalid configuration**: Fall back to defaults
5. **Exception without headers**: Use backoff strategy

## Performance Considerations

### Calculation Overhead
- Fibonacci: O(N) or O(log N) depending on implementation
- Exponential: O(1) math operation
- Linear: O(1) math operation
- Negligible compared to network latency

### Jitter Quality
- Use `random.random()` for simplicity
- Sufficient for preventing thundering herd
- No cryptographic randomness needed

## Testing Requirements

1. **Fibonacci Backoff**
   - Verify sequence correctness
   - Verify capping at max_value
   - Verify Retry-After override

2. **Exponential Backoff**
   - Verify doubling behavior
   - Verify capping at max_delay
   - Verify jitter distribution

3. **Linear Backoff**
   - Verify linear scaling
   - Verify max delay limit

4. **Jitter**
   - Verify distribution (0.5x to 1.5x of delay)
   - Verify randomness

5. **Integration**
   - Verify factory creates correct strategy
   - Verify configuration loading
   - Verify Retry-After precedence

## Output Specification

Design document including:

1. **BackoffStrategy Abstract Interface**
   - Method signatures
   - Documentation
   - Expected behavior

2. **Fibonacci Backoff Implementation**
   - Algorithm with examples
   - Max value capping
   - Configuration parameters

3. **Exponential Backoff Implementation**
   - Algorithm with examples
   - Jitter implementation
   - Configuration parameters

4. **Linear Backoff Implementation**
   - Algorithm with examples
   - Use cases

5. **Factory and Configuration**
   - How to create strategies from config
   - How to load provider-specific configs
   - How to handle missing configs (defaults)

6. **Integration with UnifiedRateLimiter**
   - How get_backoff_delay() uses strategy
   - How Retry-After takes precedence
   - How exception is passed to strategy

7. **Provider-Specific Configurations**
   - Recommended strategy for each provider
   - Configuration examples (yaml)
   - Migration from current @backoff decorators

## Success Criteria

- All backoff strategies (Fibonacci, exponential, linear) work with same interface
- Strategies pluggable and configurable
- Retry-After headers respected when present
- Jitter prevents thundering herd
- Can add new backoff strategies without modifying UnifiedRateLimiter
- Backward compatible with current @backoff decorators in generators
