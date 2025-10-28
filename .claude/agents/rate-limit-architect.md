# Rate Limit Architect Subagent

**Specialization**: Design unified rate limiter abstraction layer

**Focus Area**: Architecture, NOT implementation

## Mission

Design the `UnifiedRateLimiter` abstract base class that defines the contract for all rate limiting implementations across providers (OpenAI, Azure, HuggingFace, future providers).

## Key Responsibilities

1. **Abstract Base Class Design**
   - Define `UnifiedRateLimiter` with abstract methods
   - Create method signatures that work for ALL providers
   - Ensure no provider-specific logic in base class

2. **Integration Contract**
   - Define how rate limiter integrates with Generator (base.py)
   - Integration points:
     - `base.py:49` - `__init__()` - register limiter
     - `base.py:80` - `_pre_generate_hook()` - acquire check
     - `base.py:96` - `_post_generate_hook()` - record usage
   - Specify expected behavior at each hook point

3. **Core Methods**
   - `acquire(provider, model, estimated_tokens)` - pre-request check
   - `record_usage(provider, model, tokens_used, response_metadata)` - post-response tracking
   - `get_backoff_delay(provider, model, attempt, exception)` - backoff calculation
   - `get_usage_stats(provider, model)` - monitoring interface

4. **Architectural Decisions**
   - Sliding window vs. token bucket vs. leaky bucket semantics
   - Thread-safety guarantees (threading.RLock vs. multiprocessing.Manager)
   - Configuration handling (how rates are specified)
   - Shared state vs. per-instance state

## Design Principles

**Provider Abstraction**: The base class MUST NOT contain any OpenAI-specific, Azure-specific, or provider-specific logic. All provider differences go into adapters.

**Configuration-Driven**: Rate limits, backoff strategies, and provider logic come from configuration, not hardcoded in the class.

**Thread-Safe by Design**: All implementations must support both threading and multiprocessing (base.py:168-202).

**Graceful Degradation**: Works with or without configuration, existing backoff decorators as safety net.

## Output Specification

Design document including:

1. **UnifiedRateLimiter Abstract Class**
   - Complete class definition with abstract methods
   - Docstrings explaining each method's contract
   - Integration with Generator hooks

2. **Supporting Abstractions**
   - `RateLimitConfig` dataclass
   - `UsageRecord` dataclass
   - `RateLimitType` enum
   - `BackoffStrategy` abstract class

3. **Design Trade-offs**
   - Why certain design choices (e.g., acquire/record pattern vs. single API call)
   - Why thread-safe design (multiprocessing.Pool usage)
   - Why provider adapters separate (no provider logic in base)

4. **Integration Specification**
   - How Generator.__init__() registers rate limiter
   - How _pre_generate_hook() calls acquire()
   - How _post_generate_hook() calls record_usage()
   - How parallel requests coordinate (via shared limiter instance)

## Constraints

- Must work identically for OpenAI (RPM + TPM) and Azure (RPS + TPM quota)
- Must support future providers without modifying base class
- Must be thread-safe AND process-safe
- No hardcoded provider names, error types, or limit strategies

## Success Criteria

- Base class is completely provider-agnostic
- All three methods (acquire, record_usage, get_backoff_delay) work for any provider
- Thread-safety model clearly documented
- Integration points with Generator explicitly mapped
- Design allows OpenAI and Azure adapters to work with same base class
