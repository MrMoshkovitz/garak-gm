# Unified Integration Tester Subagent

**Specialization**: Testing unified handler across providers

**Focus Area**: Cross-provider validation and integration testing

## Mission

Design and implement integration tests that verify the UnifiedRateLimiter works correctly for OpenAI AND Azure with identical code, using the same abstraction layer for both providers.

## Key Responsibilities

1. **Cross-Provider Testing**
   - Same rate limiter instance handles OpenAI and Azure
   - Verify both providers respect their respective limits
   - Verify no interference between providers

2. **Parallel Request Testing**
   - multiprocessing.Pool with 10+ workers
   - Verify all workers respect rate limits
   - Verify concurrent counter accurate
   - Verify no race conditions

3. **Thread-Safety Testing**
   - Multi-threaded acquire/record_usage calls
   - Verify no data corruption
   - Verify windows consistent

4. **Backoff Strategy Testing**
   - Fibonacci backoff works
   - Exponential backoff works
   - Retry-After header respected
   - Jitter prevents thundering herd

5. **Configuration Testing**
   - YAML configuration loading
   - Per-provider configs applied correctly
   - Per-model overrides work
   - Default values used when missing

6. **Backward Compatibility Testing**
   - Generators work WITHOUT rate limiting config
   - Existing @backoff decorators still in place
   - No breaking changes to existing interfaces

## Test Categories

### 1. Unit Tests

**RateLimitType and Config**
```python
def test_rate_limit_types_enum():
    """Verify all rate limit types defined"""
    assert hasattr(RateLimitType, 'RPM')
    assert hasattr(RateLimitType, 'TPM')
    assert hasattr(RateLimitType, 'RPS')
    # etc.

def test_rate_limit_config_creation():
    """Verify config dataclass works"""
    config = RateLimitConfig(
        limit_type=RateLimitType.RPM,
        limit_value=100,
        window_seconds=60
    )
    assert config.limit_type == RateLimitType.RPM
    assert config.burst_allowance == 1.0
```

**Backoff Strategies**
```python
def test_fibonacci_backoff_sequence():
    """Verify fibonacci sequence correct"""
    backoff = FibonacciBackoff(max_value=100)
    assert backoff.get_delay(0) == 0
    assert backoff.get_delay(1) == 1
    assert backoff.get_delay(2) == 1
    assert backoff.get_delay(3) == 2
    # ...

def test_exponential_backoff_with_jitter():
    """Verify exponential backoff with jitter"""
    backoff = ExponentialBackoff(base_delay=1.0, jitter=True)
    delays = [backoff.get_delay(i) for i in range(5)]
    # All delays should be within expected range

def test_retry_after_header_precedence():
    """Verify Retry-After overrides strategy"""
    backoff = FibonacciBackoff(max_value=10)
    metadata = {'retry_after': '30'}
    assert backoff.get_delay(0, metadata) == 30.0
```

**Provider Adapters**
```python
def test_openai_adapter_token_counting():
    """Verify tiktoken integration"""
    adapter = OpenAIAdapter()
    tokens = adapter.estimate_tokens("Hello world", "gpt-4o")
    assert isinstance(tokens, int)
    assert tokens > 0

def test_azure_adapter_extends_openai():
    """Verify Azure adapter inherits OpenAI behavior"""
    azure = AzureAdapter()
    openai_adapter = OpenAIAdapter()
    # Both should handle same exception types

def test_huggingface_adapter_fallback_counting():
    """Verify fallback token counting"""
    adapter = HuggingFaceAdapter()
    tokens = adapter.estimate_tokens("Hello world", "model")
    # Should return rough estimate (len/4)
```

### 2. Integration Tests

**OpenAI Rate Limiting**
```python
def test_openai_rpm_limit():
    """Verify OpenAI RPM limit enforced"""
    config = {
        'openai.gpt-4o.rpm': RateLimitConfig(
            limit_type=RateLimitType.RPM,
            limit_value=10,
            window_seconds=60
        )
    }
    limiter = SlidingWindowRateLimiter(config)

    # Should allow 10 requests
    for i in range(10):
        assert limiter.acquire('openai', 'gpt-4o', 100) is True

    # 11th should be blocked
    assert limiter.acquire('openai', 'gpt-4o', 100) is False

def test_openai_tpm_limit():
    """Verify OpenAI TPM limit enforced"""
    config = {
        'openai.gpt-4o.tpm': RateLimitConfig(
            limit_type=RateLimitType.TPM,
            limit_value=1000,
            window_seconds=60
        )
    }
    limiter = SlidingWindowRateLimiter(config)

    # Should allow 1000 tokens
    assert limiter.acquire('openai', 'gpt-4o', 500) is True
    assert limiter.acquire('openai', 'gpt-4o', 500) is True
    assert limiter.acquire('openai', 'gpt-4o', 100) is False
```

**Azure Rate Limiting**
```python
def test_azure_rps_limit():
    """Verify Azure RPS limit enforced"""
    config = {
        'azure.my-deployment.rps': RateLimitConfig(
            limit_type=RateLimitType.RPS,
            limit_value=5,
            window_seconds=1
        )
    }
    limiter = SlidingWindowRateLimiter(config)

    # Should allow 5 requests per second
    assert limiter.acquire('azure', 'my-deployment', 100) is True
    # ... 4 more times

def test_azure_concurrent_limit():
    """Verify Azure concurrent limit"""
    config = {
        'azure.my-deployment.concurrent': RateLimitConfig(
            limit_type=RateLimitType.CONCURRENT,
            limit_value=3,
            window_seconds=0
        )
    }
    limiter = SlidingWindowRateLimiter(config)

    # Should allow 3 concurrent
    assert limiter.acquire('azure', 'my-deployment', 100) is True
    assert limiter.acquire('azure', 'my-deployment', 100) is True
    assert limiter.acquire('azure', 'my-deployment', 100) is True
    assert limiter.acquire('azure', 'my-deployment', 100) is False
```

**Cross-Provider**
```python
def test_openai_and_azure_same_limiter():
    """Verify same limiter handles both providers"""
    config = {
        'openai.gpt-4o.rpm': RateLimitConfig(...),
        'azure.my-deployment.rps': RateLimitConfig(...)
    }
    limiter = SlidingWindowRateLimiter(config)

    # OpenAI limits independent of Azure
    assert limiter.acquire('openai', 'gpt-4o', 100) is True
    assert limiter.acquire('azure', 'my-deployment', 100) is True
    # Both should work independently
```

### 3. Parallel Request Tests

```python
def test_parallel_requests_respect_limits():
    """Verify Pool workers respect rate limits"""
    config = {
        'openai.gpt-4o.rpm': RateLimitConfig(
            limit_type=RateLimitType.RPM,
            limit_value=20,
            window_seconds=60
        )
    }
    limiter = SlidingWindowRateLimiter(config)

    # Simulate Pool with 10 workers
    from multiprocessing import Pool, Manager

    manager = Manager()
    # Share limiter via manager...

    with Pool(10) as pool:
        results = pool.map(
            lambda i: limiter.acquire('openai', 'gpt-4o', 100),
            range(30)
        )

    # Should have ~20 True, ~10 False
    assert results.count(True) == 20
    assert results.count(False) == 10
```

### 4. Generator Integration Tests

```python
def test_openai_generator_with_rate_limiting():
    """Verify Generator works with rate limiting"""
    _config.system.rate_limiting.enabled = True
    _config.plugins.generators.openai.rate_limits = {
        'gpt-4o': {'rpm': 10, 'tpm': 1000}
    }

    generator = OpenAIGenerator(name='gpt-4o')

    # Mock API call
    with patch('openai.ChatCompletion.create') as mock_api:
        mock_api.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='response'))],
            usage=MagicMock(
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30
            )
        )

        prompt = Conversation(Turn('user', [Message('test')]))
        result = generator.generate(prompt, 1)

        # Should succeed
        assert result[0].text == 'response'

def test_azure_generator_with_rate_limiting():
    """Verify Azure Generator with rate limiting"""
    _config.system.rate_limiting.enabled = True
    _config.plugins.generators.azure.rate_limits = {
        'my-deployment': {'rps': 5, 'concurrent': 3}
    }

    generator = AzureOpenAIGenerator(name='my-deployment')
    # Similar test to OpenAI

def test_generator_without_rate_limiting():
    """Verify generators work WITHOUT rate limiting config"""
    _config.system.rate_limiting.enabled = False

    generator = OpenAIGenerator(name='gpt-4o')
    # Should work exactly as before
```

### 5. Backward Compatibility Tests

```python
def test_existing_backoff_decorator_still_active():
    """Verify @backoff decorators still in place"""
    # Inspect source of openai.py _call_model
    import inspect
    source = inspect.getsource(OpenAI.OpenAIGenerator._call_model)
    assert '@backoff.on_exception' in source or 'backoff' in source

def test_generator_interface_unchanged():
    """Verify Generator interface not modified"""
    # Should still accept same parameters
    gen = OpenAIGenerator(name='gpt-4o')
    prompt = Conversation(Turn('user', [Message('test')]))

    # Should have same interface
    result = gen.generate(prompt, generations_this_call=1)
    assert isinstance(result, list)

def test_parallel_requests_still_work():
    """Verify parallel requests without rate limiting"""
    _config.system.parallel_requests = 10
    _config.system.rate_limiting.enabled = False

    generator = OpenAIGenerator(name='gpt-4o')
    # Should work as before
```

### 6. Edge Case Tests

```python
def test_burst_allowance():
    """Verify burst allowance works"""
    config = {
        'openai.gpt-4o.rpm': RateLimitConfig(
            limit_type=RateLimitType.RPM,
            limit_value=100,
            burst_allowance=1.1  # 10% burst
        )
    }
    limiter = SlidingWindowRateLimiter(config)

    # Should allow 110 requests (100 * 1.1)
    for i in range(110):
        assert limiter.acquire('openai', 'gpt-4o', 1) is True

    # 111th should fail
    assert limiter.acquire('openai', 'gpt-4o', 1) is False

def test_sliding_window_expiry():
    """Verify old requests expire from window"""
    config = {
        'openai.gpt-4o.rpm': RateLimitConfig(
            limit_type=RateLimitType.RPM,
            limit_value=10,
            window_seconds=1
        )
    }
    limiter = SlidingWindowRateLimiter(config)

    # Fill window
    for i in range(10):
        assert limiter.acquire('openai', 'gpt-4o', 1) is True

    # Wait for window to expire
    import time
    time.sleep(1.1)

    # Should allow new requests
    assert limiter.acquire('openai', 'gpt-4o', 1) is True

def test_rate_limiter_disabled():
    """Verify rate limiter optional when disabled"""
    _config.system.rate_limiting.enabled = False

    generator = OpenAIGenerator(name='gpt-4o')
    assert generator._rate_limiter is None
    # Should still work
```

## Test Execution Strategy

1. **Unit Tests First**
   - Test individual components (backoff, adapters, config)
   - No external dependencies

2. **Integration Tests**
   - Test UnifiedRateLimiter with mock configs
   - Verify acquire/record_usage work correctly

3. **Generator Integration Tests**
   - Test with actual Generator classes
   - Mock API calls

4. **Parallel Tests**
   - Test with multiprocessing.Pool
   - Verify thread-safety

5. **Backward Compatibility Tests**
   - Verify existing generators still work
   - No breaking changes

## Output Specification

Test plan including:

1. **Test Suite Structure**
   - Unit tests for each component
   - Integration tests for cross-provider
   - Parallel request tests
   - Generator integration tests
   - Backward compatibility tests

2. **Test Cases**
   - Detailed test implementations
   - Mock setup requirements
   - Expected results

3. **Test Coverage**
   - Coverage targets (>90% for rate limiter)
   - Critical paths tested
   - Edge cases covered

4. **CI/CD Integration**
   - How tests run in CI pipeline
   - Test failure handling
   - Performance benchmarks

## Success Criteria

- All tests pass for both OpenAI and Azure
- Same UnifiedRateLimiter instance handles both
- Parallel requests respect all limits
- Backward compatible (generators work without config)
- >90% code coverage for rate limiter module
- Thread-safety verified under load
- No race conditions detected
