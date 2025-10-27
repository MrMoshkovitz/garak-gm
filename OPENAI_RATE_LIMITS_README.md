# OpenAI Rate Limited Generator

## Overview

This branch implements a **reactive rate limiting wrapper** for garak's OpenAI generator. The wrapper monitors rate limit headers from OpenAI API responses and automatically pauses execution when usage approaches limits (at 95% threshold).

## Features

- **Non-invasive**: Zero modifications to existing garak code
- **Drop-in replacement**: Change only the generator name in config
- **Reactive monitoring**: Uses actual rate limit headers from OpenAI responses
- **Dual limit handling**: Monitors both request-based (RPM) and token-based (TPM) limits
- **Smart pausing**: Waits for exact reset time indicated by OpenAI headers
- **Graceful degradation**: Warns if headers missing but doesn't fail

## Implementation

**File**: `garak/generators/openai_rated.py`

**Approach**: Inherits from `OpenAIGenerator` and overrides only `_call_model()` to:
1. Use `with_raw_response` pattern to access HTTP headers
2. Extract rate limit information from response headers
3. Check if usage is at 95% threshold (5% remaining)
4. Pause execution if threshold exceeded
5. Return identical response format as parent class

## Rate Limit Headers Used

The wrapper monitors these OpenAI response headers:

- `x-ratelimit-remaining-requests`: Requests left before RPM limit
- `x-ratelimit-limit-requests`: Total RPM limit
- `x-ratelimit-reset-requests`: Time until RPM limit resets (e.g., "1s", "6m0s")
- `x-ratelimit-remaining-tokens`: Tokens left before TPM limit
- `x-ratelimit-limit-tokens`: Total TPM limit
- `x-ratelimit-reset-tokens`: Time until TPM limit resets (e.g., "6m0s")

## Usage

### Command Line

Replace `openai` with `openai_rated` in your garak command:

```bash
# Original command
garak -m openai.OpenAIGenerator --target_name gpt-3.5-turbo --probes dan.Dan_11_0

# With rate limiting
garak -m openai_rated.OpenAIRatedGenerator --target_name gpt-3.5-turbo --probes dan.Dan_11_0
```

### Configuration File

In your probe configuration, change the generator:

```yaml
# Before
generator: openai

# After
generator: openai_rated
```

### Example Output

When rate limits are approached, you'll see warnings:

```
WARNING: Token rate limit at 95% usage (250/5000 remaining)
WARNING: Pausing for 61s until reset
```

## Behavior

### Trigger Logic

The wrapper pauses when **either** limit reaches 95% usage:

- **Token limit**: `remaining_tokens <= (limit_tokens * 0.05)`
- **Request limit**: `remaining_requests <= (limit_requests * 0.05)`

### Wait Duration

The wrapper sleeps for the exact duration specified in the reset header plus 1 second buffer:

- `x-ratelimit-reset-tokens: "6m0s"` → sleep 361 seconds
- `x-ratelimit-reset-requests: "1s"` → sleep 2 seconds

### Error Handling

- **Missing headers**: Logs warning but continues (some models/tiers may not return all headers)
- **Parse errors**: Logs warning but continues
- **Other errors**: Passes through to parent class's error handling

## Testing

To test the rate limit handling:

1. **Use free tier model** (lower limits): `gpt-3.5-turbo`
2. **Run high-volume probe**: Use probes that generate many requests
3. **Monitor logs**: Watch for rate limit warnings
4. **Verify pause behavior**: Confirm execution pauses and resumes

Example test command:

```bash
# This will trigger rate limits on free tier
garak -m openai_rated.OpenAIRatedGenerator \
  --target_name gpt-3.5-turbo \
  --probes dan.Dan_11_0 \
  --config generations=10
```

## Verification Checklist

- ✅ No modifications to existing garak files
- ✅ File created: `garak/generators/openai_rated.py`
- ✅ Syntax valid: Python compilation succeeds
- ✅ Drop-in replacement: Only generator name changes
- ✅ Rate limit monitoring: Uses OpenAI response headers
- ✅ 95% threshold: Pauses at 5% remaining
- ✅ Dual limits: Handles both RPM and TPM
- ✅ Smart waiting: Uses reset time from headers
- ✅ Return type compatible: Returns `List[Message]` like parent
- ✅ Error handling: Graceful degradation on missing headers

## Architecture Decisions

### Why `with_raw_response`?

The OpenAI Python SDK v1+ wraps responses in Pydantic models that don't expose headers by default. The `with_raw_response` pattern provides access to the underlying HTTP response while maintaining SDK convenience.

### Why 95% threshold?

- Provides safety margin before hard limit
- Allows completion of in-flight requests
- Reduces chance of 429 errors
- Conservative approach for production use

### Why reactive vs. proactive?

**Reactive** (this implementation):
- ✅ Uses actual limits from API responses
- ✅ Handles varying limits across tiers/models
- ✅ No estimation errors
- ✅ Simpler implementation

**Proactive** (not implemented):
- ❌ Requires knowing limits in advance
- ❌ Must estimate token usage before requests
- ❌ Complex across different models/tiers
- ❌ Out of scope for this task

### Why not modify existing generator?

**Wrapper approach**:
- ✅ Zero risk to existing functionality
- ✅ Easy to enable/disable (just change name)
- ✅ Can be tested independently
- ✅ Clear separation of concerns
- ✅ Follows open/closed principle

## Limitations

This implementation intentionally does NOT include:

- ❌ Proactive rate limit prediction
- ❌ Token estimation before requests
- ❌ Multi-model rate limit coordination
- ❌ Persistent state across sessions
- ❌ Complex retry strategies
- ❌ Rate limit distribution across parallel workers

These features are out of scope and can be added in future iterations if needed.

## Dependencies

Requires OpenAI Python SDK v1+:
- Uses `with_raw_response` pattern
- Expects rate limit headers in responses

## Compatibility

- **OpenAI SDK**: v1.0+
- **Python**: 3.7+
- **garak**: Current version (tested with main branch)
- **Models**: All OpenAI models (GPT-3.5, GPT-4, GPT-4o, etc.)

## Future Enhancements

Possible future improvements (not in scope):

1. **Persistent state**: Save rate limit status across sessions
2. **Proactive estimation**: Estimate tokens before requests
3. **Multi-worker coordination**: Share rate limits across parallel workers
4. **Custom thresholds**: Allow configuring threshold percentage
5. **Metrics collection**: Track rate limit statistics
6. **Adaptive strategies**: Learn optimal request patterns

## Support

For issues or questions:
1. Check that OpenAI SDK version is v1.0+
2. Verify API key has proper permissions
3. Check model/tier supports rate limit headers
4. Review garak logs for warnings/errors

## License

Same as garak project.
