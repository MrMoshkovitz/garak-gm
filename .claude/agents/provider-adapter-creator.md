# Provider Adapter Creator Subagent

**Specialization**: Create provider-specific rate limit adapters

**Focus Area**: Provider-specific logic encapsulation

## Mission

Design and implement provider-specific adapters that handle OpenAI, Azure, HuggingFace, and future provider differences without modifying the UnifiedRateLimiter base class.

## Key Responsibilities

1. **ProviderAdapter Interface Design**
   - Abstract base class for all provider adapters
   - Methods for extracting provider-specific information:
     - `extract_rate_limit_info(exception)` - from error responses
     - `extract_usage_from_response(response)` - actual token usage
     - `estimate_tokens(prompt, model)` - client-side token counting
     - `get_retry_after(exception)` - backoff delay from headers

2. **OpenAI Adapter Implementation**
   - Handle: `openai.RateLimitError`, `openai.InternalServerError`, etc.
   - Extract headers: `x-ratelimit-limit-requests`, `x-ratelimit-remaining-tokens`
   - Token counting: Use `tiktoken` with proper model mapping
   - Rate limit types: RPM, TPM, Image RPM
   - Response parsing: `response.usage.prompt_tokens`, `response.usage.completion_tokens`

3. **Azure Adapter Implementation**
   - Extend OpenAI adapter (reuse exception handling)
   - Handle deployment-specific configuration (`target_name`)
   - Extract Azure-specific headers: `x-ms-region`, quota headers
   - Model mapping: `openai_model_mapping` (gpt-4 → gpt-4-turbo-2024-04-09)
   - Rate limit types: TPM quota (monthly), RPS, concurrent
   - Special handling: Monthly quota window vs. rolling windows

4. **HuggingFace Adapter Implementation**
   - Handle: `HFRateLimitException`, `HFLoadingException`, `HFInternalServerError`
   - Rate limit types: Generic rate limiting (RPM)
   - Token counting: Rough estimation (no reliable provider counts)
   - Response parsing: Depends on endpoint (InferenceAPI vs. InferenceEndpoint)
   - Error detection: Parse error messages for rate limit indication

5. **Adapter Registry**
   - Pattern: Provider name → Adapter class mapping
   - Factory function: `get_adapter_for_provider(provider_name)`
   - Registration function: `register_adapter(provider_name, adapter_class)`
   - Extensibility: Easy to add new providers without modifying existing code

## Provider-Specific Details

### OpenAI (openai.py:200-210)
```
Rate Limit Types: RPM, TPM
Token Counting: tiktoken (client-side)
Error Codes: RateLimitError, InternalServerError, APITimeoutError, APIConnectionError
Response Headers: x-ratelimit-limit-requests, x-ratelimit-remaining-requests,
                  x-ratelimit-limit-tokens, x-ratelimit-remaining-tokens, Retry-After
Response Format: response.usage.prompt_tokens, completion_tokens, total_tokens
Backoff: Fibonacci (max_value=70)
```

### Azure (azure.py:32-115)
```
Rate Limit Types: TPM quota (monthly), RPS, concurrent
Token Counting: tiktoken (same as OpenAI) + Azure headers
Error Codes: Same as OpenAI (uses same SDK)
Response Headers: Same as OpenAI + x-ms-region
Deployment: target_name parameter specifies deployment
Model Mapping: gpt-35-turbo → gpt-3.5-turbo-0125
Backoff: Exponential (base_delay=1.0, max_delay=60.0)
```

### HuggingFace (huggingface.py:211-335)
```
Rate Limit Types: Generic RPM, concurrent
Token Counting: No reliable counts (estimate 1 token = 4 chars)
Error Codes: HFRateLimitException, HFLoadingException, HFInternalServerError
Response Headers: Generic HTTP headers
Endpoints: InferenceAPI (public), InferenceEndpoint (private)
Backoff: Fibonacci (max_value=125) or Exponential
```

## Abstraction Pattern

Each adapter MUST:
1. Extract provider-specific error info without raising provider-specific exceptions
2. Return normalized dictionaries (not provider objects)
3. Handle missing data gracefully (fallback estimates)
4. Be stateless (no side effects)

Example:
```python
# OpenAI adapter doesn't raise openai.RateLimitError
# Instead, extracts rate limit info into a dict:
{
    'limit_requests': '3500',
    'remaining_requests': '1234',
    'limit_tokens': '90000',
    'remaining_tokens': '45000',
    'retry_after': '30'
}
```

## Design Constraints

- Adapters MUST NOT contain business logic (rate limiting, backoff calculation)
- Adapters MUST NOT modify UnifiedRateLimiter behavior
- Adapters MUST handle missing/inconsistent provider responses
- Each adapter is stateless and reusable

## Output Specification

Implementation guide including:

1. **ProviderAdapter Abstract Base Class**
   - Complete interface definition
   - Documentation for each method
   - Expected return types

2. **OpenAIAdapter Implementation**
   - Exception handling
   - Token counting (tiktoken integration)
   - Response parsing

3. **AzureAdapter Implementation**
   - Inheritance from OpenAIAdapter
   - Azure-specific header handling
   - Deployment-specific logic

4. **HuggingFaceAdapter Implementation**
   - Generic rate limit handling
   - Token estimation fallback
   - Error message parsing

5. **Adapter Registry**
   - Registry data structure
   - Factory function
   - Registration mechanism

6. **Extension Guide**
   - How to add adapters for new providers (Anthropic, Gemini, etc.)
   - Required methods to implement
   - Testing checklist

## Success Criteria

- OpenAI and Azure both use same UnifiedRateLimiter with different adapters
- Adding new provider requires ONLY: (1) new adapter class, (2) registry entry
- No provider-specific code in UnifiedRateLimiter
- Adapters handle missing/invalid provider data gracefully
- All provider differences encapsulated in adapters
