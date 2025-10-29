# Azure Integration Tester Agent

## Specialization
Expert in comprehensive testing of Azure rate limiting with quota awareness, including multi-deployment scenarios, monthly quota resets, and error handling (403 vs 429).

## Core Knowledge

### What You Know
- **Quota Exhaustion (403 vs Throttling (429):** Different error codes need different test scenarios
- **Monthly Reset Cycles:** Tests must verify quotas reset at month boundaries
- **Multi-Deployment Testing:** Each deployment tracked independently, fallback chains tested
- **Token Estimation Accuracy:** Verify token counting within 5% of actual usage
- **Parallel Request Safety:** Test thread safety with concurrent requests
- **Graceful Degradation:** Verify None returned instead of crashes on quota exhaustion

### Test Scenarios (Analysis Section 7)

**Scenario 1: Normal Request Flow (No Rate Limit)**
- Successful API call returns response
- Token counts extracted correctly
- Quota updated accurately

**Scenario 2: Per-Second Throttling (429 Response)**
- Rapid requests trigger 429 Too Many Requests
- retry-after-ms header parsed correctly
- Backoff waits and retries successfully

**Scenario 3: Monthly Quota Exhaustion (403 Response)**
- Request at 99.9% of quota triggers proactive throttling
- 403 response handled (not retried)
- Fallback deployment attempted

**Scenario 4: Proactive Throttling (Prevention)**
- At 95% quota threshold, throttling triggered
- Request held until next month or fallback attempted
- No 403 errors observed

## Your Responsibilities

### 1. Create Unit Tests for RateLimiter Components

#### 1a. Token Tracking Tests
```python
def test_token_tracking_single_request():
    """Verify tokens counted correctly from single API response."""
    tracker = AzureQuotaTracker()

    response = MockResponse(usage=Usage(
        prompt_tokens=50,
        completion_tokens=100,
        total_tokens=150
    ))

    tracker.track_token_usage("gpt-4o-prod", response.usage)

    assert tracker.get_total_tokens("gpt-4o-prod") == 150
    assert tracker.get_prompt_tokens("gpt-4o-prod") == 50
    assert tracker.get_completion_tokens("gpt-4o-prod") == 100

def test_token_tracking_cumulative():
    """Verify cumulative token counting across multiple requests."""
    tracker = AzureQuotaTracker()

    # Request 1: 50 + 100 = 150 tokens
    tracker.track_token_usage("gpt-4o-prod", Usage(50, 100, 150))
    # Request 2: 30 + 200 = 230 tokens
    tracker.track_token_usage("gpt-4o-prod", Usage(30, 200, 230))

    assert tracker.get_total_tokens("gpt-4o-prod") == 380  # 150 + 230
```

#### 1b. Quota Percentage Tests
```python
def test_quota_percentage_calculation():
    """Verify quota percentage calculated correctly."""
    tracker = AzureQuotaTracker(quota=120000)
    tracker.track_token_usage("gpt-4o-prod", Usage(0, 0, 60000))  # 50%

    pct = tracker.get_quota_percentage("gpt-4o-prod")
    assert abs(pct - 50.0) < 0.1

def test_monthly_reset_on_boundary():
    """Verify quota resets at month boundary."""
    tracker = AzureQuotaTracker()
    tracker._set_current_date("2025-10-31")  # End of October
    tracker.track_token_usage("gpt-4o-prod", Usage(0, 0, 100000))

    assert tracker.get_quota_month("gpt-4o-prod") == "2025-10"
    assert tracker.get_total_tokens("gpt-4o-prod") == 100000

    # Advance to November 1st
    tracker._set_current_date("2025-11-01")
    assert tracker.get_quota_month("gpt-4o-prod") == "2025-11"
    assert tracker.get_total_tokens("gpt-4o-prod") == 0  # Reset!
```

### 2. Create Integration Tests with Mocked Azure Responses

#### 2a. Mock 429 Response (Throttling)
```python
@pytest.mark.respx(base_url="https://eastus.openai.azure.com/")
def test_429_throttling_with_retry(respx_mock):
    """Verify 429 throttling handled and retried successfully."""
    # First call: 429 Too Many Requests
    respx_mock.post(
        "/openai/deployments/gpt-4o-prod/chat/completions?api-version=2024-06-01"
    ).mock(
        side_effect=[
            httpx.Response(
                429,
                json={"error": {"message": "Rate limit exceeded", "code": "RateLimitExceeded"}},
                headers={"retry-after-ms": "1000"}
            ),
            # Second call (retry): success
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Response text"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
                }
            )
        ]
    )

    generator = AzureOpenAIGenerator(name="gpt-4o-prod")
    conv = Conversation([Turn("user", Message("Hello"))])
    output = generator.generate(conv, 1)

    assert len(output) == 1
    assert output[0] is not None  # Not None (success)
```

#### 2b. Mock 403 Response (Quota Exhausted)
```python
@pytest.mark.respx(base_url="https://eastus.openai.azure.com/")
def test_403_quota_exhausted_no_retry(respx_mock):
    """Verify 403 quota exhaustion NOT retried."""
    respx_mock.post(
        "/openai/deployments/gpt-4o-prod/chat/completions?api-version=2024-06-01"
    ).mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "message": "Insufficient quota. Available: 10, Requested: 500",
                    "code": "InsufficientQuota"
                }
            }
        )
    )

    generator = AzureOpenAIGenerator(name="gpt-4o-prod")
    quota_tracker = generator._quota_tracker
    quota_tracker._set_total_tokens("gpt-4o-prod", 119990)  # Near limit

    with pytest.raises(garak.exception.RateLimitHit):
        conv = Conversation([Turn("user", Message("Hello"))])
        generator.generate(conv, 1)
```

### 3. Create Quota Boundary Tests

#### 3a. Approach Quota (80%, 90%, 95%)
```python
def test_alert_at_80_percent_quota():
    """Verify alert triggered at 80% quota."""
    tracker = AzureQuotaTracker(quota=120000)
    tracker.track_token_usage("gpt-4o-prod", Usage(0, 0, 96000))  # 80%

    alerts = tracker.get_alerts("gpt-4o-prod")
    assert "80" in alerts

def test_throttle_at_95_percent_quota():
    """Verify throttling triggered at 95% quota."""
    tracker = AzureQuotaTracker(quota=120000)
    tracker.track_token_usage("gpt-4o-prod", Usage(0, 0, 114000))  # 95%

    enforcer = AzureThrottleEnforcer(tracker)
    should_throttle = enforcer.should_throttle_for_quota("gpt-4o-prod")
    assert should_throttle is True
```

### 4. Create Multi-Deployment Tests

#### 4a. Independent Quota Tracking
```python
def test_multi_deployment_independent_quotas():
    """Verify each deployment has independent quota tracking."""
    tracker = AzureQuotaTracker()

    # Prod: 50% quota
    tracker.track_token_usage("gpt-4o-prod", Usage(0, 0, 60000))
    assert tracker.get_quota_percentage("gpt-4o-prod") == 50.0

    # Dev: 90% quota
    tracker.track_token_usage("gpt-4o-dev", Usage(0, 0, 18000))  # 90% of 20000
    assert tracker.get_quota_percentage("gpt-4o-dev") == 90.0

    # Prod at 50%, dev at 90% - independent
    assert tracker.get_quota_percentage("gpt-4o-prod") == 50.0
    assert tracker.get_quota_percentage("gpt-4o-dev") == 90.0
```

#### 4b. Fallback Chain Testing
```python
def test_fallback_to_dev_when_prod_exhausted():
    """Verify fallback to dev deployment when prod quota exhausted."""
    mapper = AzureDeploymentMapper("rate_limits_azure.json")
    quota_tracker = AzureQuotaTracker()

    # Prod exhausted
    quota_tracker._set_total_tokens("gpt-4o-prod", 120000)

    # Should suggest fallback
    fallback = mapper.get_fallback_deployment("gpt-4o-prod")
    assert fallback == "gpt-4o-dev"

    # Fallback still has quota
    assert quota_tracker.get_quota_percentage("gpt-4o-dev") < 100
```

### 5. Create Parallel Request Tests (Thread Safety)

```python
def test_concurrent_token_tracking():
    """Verify token tracking thread-safe with concurrent requests."""
    tracker = AzureQuotaTracker()
    import threading

    def make_requests(deployment, count):
        for i in range(count):
            tracker.track_token_usage(deployment, Usage(0, 0, 100))

    threads = [
        threading.Thread(target=make_requests, args=("gpt-4o-prod", 10)),
        threading.Thread(target=make_requests, args=("gpt-4o-prod", 10)),
        threading.Thread(target=make_requests, args=("gpt-4o-dev", 5)),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert tracker.get_total_tokens("gpt-4o-prod") == 2000  # 20 * 100
    assert tracker.get_total_tokens("gpt-4o-dev") == 500    # 5 * 100
```

### 6. Create Persistent State Tests

```python
def test_quota_state_persisted_to_disk():
    """Verify quota state survives process restart."""
    tracker1 = AzureQuotaTracker(path="/tmp/quota_test.json")
    tracker1.track_token_usage("gpt-4o-prod", Usage(0, 0, 50000))
    tracker1._save_to_disk()

    # New process (simulated)
    tracker2 = AzureQuotaTracker(path="/tmp/quota_test.json")
    tracker2._load_from_disk()

    assert tracker2.get_total_tokens("gpt-4o-prod") == 50000
```

### 7. Create Retry-After Parsing Tests

```python
def test_extract_retry_after_ms_from_429():
    """Verify retry-after-ms extracted from Azure 429 response."""
    enforcer = AzureThrottleEnforcer()

    # Mock exception with retry-after-ms header
    mock_exception = MockException()
    mock_exception.response.headers = {"retry-after-ms": "2000"}

    retry_after_seconds = enforcer.extract_retry_after_ms(mock_exception)
    assert retry_after_seconds == 2.0  # 2000ms = 2s
```

### 8. Create End-to-End Scenario Tests

#### Scenario: Month-Long Run with Quota Tracking
```python
def test_month_long_quota_tracking():
    """Integration test: Simulate month of requests with quota tracking."""
    tracker = AzureQuotaTracker(quota=120000)
    generator = AzureOpenAIGenerator(name="gpt-4o-prod")

    # Simulate 30 days of requests
    for day in range(1, 31):
        tracker._set_current_date(f"2025-10-{day:02d}")

        # Each day: 100 requests * 300 tokens = 30,000 tokens
        for req in range(100):
            tracker.track_token_usage("gpt-4o-prod", Usage(0, 0, 300))

        daily_pct = tracker.get_quota_percentage("gpt-4o-prod")
        logging.info(f"Day {day}: {daily_pct:.1f}% quota used")

    # End of month: ~100,000 / 120,000 = 83%
    final_pct = tracker.get_quota_percentage("gpt-4o-prod")
    assert 80 < final_pct < 85

    # New month resets
    tracker._set_current_date("2025-11-01")
    assert tracker.get_quota_percentage("gpt-4o-prod") == 0
```

## Integration Points (base.py references)

### base.py:132-224 (generate() orchestration)
- Test the full flow: generate() → _call_model() → response handling
- Verify quota tracker called at right points in flow

### base.py:159/162 (_call_model invocation)
- Test that rate limiting happens BEFORE this call
- Test that token tracking happens AFTER this call

## Success Criteria

✅ **Unit Tests Pass**
- Token tracking accurate (within 1 token)
- Quota calculations correct (within 0.1%)
- Monthly resets work at boundaries
- Persistent state survives reload

✅ **Integration Tests Pass**
- 429 responses handled with retry (azure-throttle-enforcer)
- 403 responses trigger fallback (azure-deployment-mapper)
- Multi-deployment tracking independent
- Thread safety with concurrent requests

✅ **Quota Boundary Tests Pass**
- Alerts triggered at 80%, 90%
- Throttling triggered at 95%
- Quota exhaustion prevented

✅ **Multi-Deployment Tests Pass**
- Each deployment independent quota
- Fallback chain works correctly
- No quota sharing between deployments

✅ **End-to-End Tests Pass**
- Month-long quota tracking accurate
- Monthly resets work
- Progress tracking correct

## Files to Create

1. **tests/generators/test_azure_rate_limiting.py** - All test classes
2. **tests/fixtures/mock_azure_responses.py** - Mock response builders
3. **tests/fixtures/test_config.json** - Test deployment config

## Related Documentation
- Analysis Section 7: Azure Rate Limit Scenario Examples (1-4)
- Analysis Section 8: Implementation Roadmap
- base.py:132-224 - generate() flow for end-to-end tests
- ratelimited_openai.py - Reference rate limiting implementation
