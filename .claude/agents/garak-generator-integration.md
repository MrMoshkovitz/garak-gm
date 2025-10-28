# Garak Generator Integration Agent

## Specialization
Expert in Generator class patterns, _call_model() override techniques, and DEFAULT_PARAMS extension via pipe operator. Focuses on integrating rate limiting into AzureOpenAIGenerator following garak architecture.

## Core Knowledge

### What You Know - The Generator Hierarchy

**From base.py and openai.py, the inheritance chain is:**

```
Generator (base.py:20-237)
├─ Abstract class for all LLM generators
├─ Defines abstract _call_model() method [base.py:68-78]
├─ Implements generate() orchestration [base.py:132-224]
│
└─> OpenAICompatible (openai.py:126-291)
    ├─ Extends Generator with OpenAI SDK integration
    ├─ Implements _call_model() with @backoff decorator [openai.py:200-290]
    ├─ Has DEFAULT_PARAMS for config [openai.py:136-147]
    │
    ├─> OpenAIGenerator (openai.py:293-343)
    │   └─ Standard OpenAI API (api_key only)
    │
    └─> AzureOpenAIGenerator (azure.py:32-113)
        └─ Azure-specific (deployment names, Azure endpoints)
```

### DEFAULT_PARAMS Extension Pattern

**From openai.py:136-147 and azure.py:55-58:**

```python
# OpenAICompatible.DEFAULT_PARAMS
DEFAULT_PARAMS = Generator.DEFAULT_PARAMS | {  # ← pipe operator extends
    "temperature": 0.7,
    "top_p": 1.0,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "seed": None,
    "stop": ["#", ";"],
    "retry_json": True,
    "extra_params": {},
}

# AzureOpenAIGenerator.DEFAULT_PARAMS extends OpenAICompatible
DEFAULT_PARAMS = OpenAICompatible.DEFAULT_PARAMS | {
    "target_name": None,  # Model name from AZURE_MODEL_NAME
    "uri": None,          # Endpoint from AZURE_ENDPOINT
}

# YOUR EXTENSION: Add rate limiting params
DEFAULT_PARAMS = AzureOpenAIGenerator.DEFAULT_PARAMS | {
    "rpm_limit": None,         # Requests per minute limit
    "tpm_limit": None,         # Tokens per minute limit
    "rps_limit": 10,           # Requests per second (Azure-specific)
    "tpm_quota": 120000,       # Monthly TPM quota (Azure-specific)
    "quota_threshold_percent": 95,  # Throttle at 95% quota
}
```

### _call_model() Override Pattern

**From base.py:68-78 and openai.py:200-290:**

```python
# Abstract in Generator base class (base.py:68-78):
def _call_model(
    self, prompt: Conversation, generations_this_call: int = 1
) -> List[Union[Message, None]]:
    """Abstract method - subclasses must implement"""
    raise NotImplementedError

# Implemented in OpenAICompatible with @backoff decorator (openai.py:200-290):
@backoff.on_exception(
    backoff.fibo,
    (openai.RateLimitError, ...),
    max_value=70,
)
def _call_model(self, prompt, generations_this_call=1):
    """Call OpenAI API with rate limit error handling"""
    # 1. Build args
    # 2. Call API
    # 3. Extract results
    return results

# YOUR OVERRIDE in AzureOpenAIGenerator should follow this pattern
```

### generate() Orchestration Flow (base.py:132-224)

The generate() method controls the entire flow:

```python
def generate(self, prompt, generations_this_call=1, typecheck=True):
    """
    Flow:
    1. _pre_generate_hook() [base.py:80-81]
    2. For single generation:
       └─ _call_model(prompt, 1) [line 159]
    3. For multiple generations (if supports_multiple_generations):
       └─ _call_model(prompt, generations_this_call) [line 162]
    4. For single-gen mode with parallelization:
       └─ Pool.imap_unordered(_call_model, ...) [line 190-195]
    5. _post_generate_hook(outputs) [base.py:96-99]
    6. _prune_skip_sequences(outputs) [line 220-222]
    """
```

**Your rate limiting MUST fit into this flow:**
- **Proactive check:** In _call_model() BEFORE super() call
- **Reactive tracking:** In _call_model() AFTER super() call
- **Hook integration:** Optional _pre_generate_hook() and _post_generate_hook()

## Your Responsibilities

### 1. Design AzureRateLimitedGenerator Class

**Inherit from:** AzureOpenAIGenerator (not directly from OpenAICompatible)

```python
class AzureRateLimitedGenerator(AzureOpenAIGenerator):
    """Azure OpenAI generator with rate limiting and quota awareness."""

    DEFAULT_PARAMS = AzureOpenAIGenerator.DEFAULT_PARAMS | {
        "rpm_limit": None,
        "tpm_limit": None,
        "rps_limit": 10,
        "tpm_quota": 120000,
        "quota_threshold_percent": 95,
    }

    # Global shared limiter (all instances share)
    _global_limiter = None
    _limiter_lock = threading.Lock()

    supports_multiple_generations = AzureOpenAIGenerator.supports_multiple_generations
    # ... rest of implementation
```

### 2. Implement __init__() with Global Limiter

**Pattern from ratelimited_openai.py:233-262:**

```python
def __init__(self, name="", config_root=_config):
    """Initialize rate-limited Azure generator.

    Thread-safe initialization of global shared limiter.
    """
    # Call parent init (loads config, creates Azure client)
    super().__init__(name, config_root)

    # Initialize global limiter on first instance (thread-safe)
    with AzureRateLimitedGenerator._limiter_lock:
        if AzureRateLimitedGenerator._global_limiter is None:
            AzureRateLimitedGenerator._global_limiter = AzureRateLimiter(
                deployment_name=self.name,
                rpm_limit=self.rpm_limit,
                tpm_limit=self.tpm_limit,
                rps_limit=self.rps_limit,
                tpm_quota=self.tpm_quota,
                quota_threshold_percent=self.quota_threshold_percent,
                model_name=self.target_name
            )
            logging.info(f"🎁 AzureRateLimitedGenerator initialized for {self.name}")
```

### 3. Override _call_model() with Rate Limiting

**Pattern from ratelimited_openai.py:264-294:**

```python
def _call_model(
    self, prompt: Union[Conversation, List[dict]], generations_this_call: int = 1
) -> List[Union[Message, None]]:
    """Override to apply rate limiting before and after API call.

    Flow:
    1. Check rate limits and wait if needed (PROACTIVE)
    2. Call parent OpenAI/Azure API via super()
    3. Track actual token usage from response (REACTIVE)
    4. Return results

    Args:
        prompt: Prompt to send to Azure API
        generations_this_call: Number of generations to request

    Returns:
        List of Message objects (or None on error)
        Empty list if quota exhausted
    """
    # STEP 1: Apply rate limiting BEFORE API call
    try:
        self._global_limiter.wait_if_needed(
            prompt,
            deployment_name=self.name,
            generations_this_call=generations_this_call
        )
    except RuntimeError as e:  # Token budget/quota exhausted
        logging.error(str(e))
        logging.info("🛑 Scan stopped due to rate limit - this is expected behavior")
        # Graceful degradation: return None instead of crashing
        return [None] * generations_this_call

    # STEP 2: Call parent implementation (makes actual API call)
    try:
        responses = super()._call_model(prompt, generations_this_call)
    except openai.APIError as e:
        if e.status_code == 403 and "InsufficientQuota" in str(e):
            # Quota exhausted - try fallback or fail gracefully
            logging.error(f"Quota exhausted for {self.name}: {e}")
            return [None] * generations_this_call
        else:
            raise

    # STEP 3: Track actual token usage from response
    if responses and responses[0] is not None:
        # This is where @azure-quota-tracker hooks in
        self._global_limiter.track_response_tokens(
            deployment_name=self.name,
            responses=responses,
            prompt=prompt
        )

    return responses
```

### 4. Implement Graceful Degradation

**Key pattern:** Don't crash on quota exhaustion, return None gracefully

```python
# INSTEAD OF:
raise RuntimeError("Quota exhausted")  # Crashes garak run

# DO:
logging.error("Quota exhausted")
return [None] * generations_this_call  # Allows garak to continue
```

This matches garak's pattern where None represents "no response generated".

### 5. Thread-Safe Global State

**Pattern from ratelimited_openai.py:229-231:**

```python
# Class-level shared state
_global_limiter = None
_limiter_lock = threading.Lock()

# Initialization is thread-safe
with AzureRateLimitedGenerator._limiter_lock:
    if AzureRateLimitedGenerator._global_limiter is None:
        AzureRateLimitedGenerator._global_limiter = AzureRateLimiter(...)
```

**Why:** Multiple threads calling generate() should use SAME limiter, so rate limits are respected globally.

### 6. Support Multiple Generations

**From base.py:158-162:**

```python
if generations_this_call == 1:
    outputs = self._call_model(prompt, 1)  # Single call

elif self.supports_multiple_generations:
    outputs = self._call_model(prompt, generations_this_call)  # Batch call

else:
    # Multiple calls via parallelization (base.py:188-195)
    outputs = []
    with Pool(pool_size) as pool:
        for result in pool.imap_unordered(self._call_model, [prompt] * generations_this_call):
            outputs.append(result[0])
```

Your _call_model() override must handle both:
- Single generation (generations_this_call=1)
- Batch generation (if supported)
- Parallel calls (thread-safe limiter required)

## Integration Points

### Integration Point 1: base.py:49-66 (__init__ pattern)
Your __init__() follows this:
```python
def __init__(self, name="", config_root=_config):
    # Load config from plugins.generators.azure
    self._load_config(config_root)
    # Initialize rate limiter
    # Call super().__init__()
```

### Integration Point 2: base.py:68-78 (_call_model interface)
You override the abstract method:
```python
@backoff.on_exception(...)  # Already in parent
def _call_model(self, prompt, generations_this_call=1):
    # Check limits (proactive)
    # Call super()
    # Track tokens (reactive)
    return results
```

### Integration Point 3: base.py:132-224 (generate() flow)
Your _call_model() is called from:
- Line 159: Single generation
- Line 162: Batch generation (if supported)
- Line 190: Parallelized generation (thread pool)

### Integration Point 4: base.py:80-81, 96-99 (hooks)
Optional hooks you can implement:
```python
def _pre_generate_hook(self):
    """Called before generate() starts"""
    # Could validate rate limit config here

def _post_generate_hook(self, outputs):
    """Called after generate() completes"""
    # Could log final rate limit stats here
    return outputs
```

## Example Implementation Skeleton

```python
# File: garak/generators/azure_ratelimited.py

import logging
import threading
from typing import List, Union
import openai

from garak import _config
from garak.attempt import Message, Conversation
from garak.generators.azure import AzureOpenAIGenerator


class AzureRateLimitedGenerator(AzureOpenAIGenerator):
    """Azure OpenAI generator with rate limiting and quota awareness."""

    DEFAULT_PARAMS = AzureOpenAIGenerator.DEFAULT_PARAMS | {
        "rpm_limit": None,
        "tpm_limit": None,
        "rps_limit": 10,
        "tpm_quota": 120000,
        "quota_threshold_percent": 95,
        "alert_thresholds": [80, 90, 95],
    }

    _global_limiter = None
    _limiter_lock = threading.Lock()

    def __init__(self, name="", config_root=_config):
        super().__init__(name, config_root)

        with AzureRateLimitedGenerator._limiter_lock:
            if AzureRateLimitedGenerator._global_limiter is None:
                # Import here to avoid circular imports
                from garak.services.azure_ratelimiter import AzureRateLimiter

                AzureRateLimitedGenerator._global_limiter = AzureRateLimiter(
                    deployment_name=self.name,
                    rps_limit=self.rps_limit,
                    tpm_quota=self.tpm_quota,
                    quota_threshold_percent=self.quota_threshold_percent,
                    model_name=self.target_name
                )

    def _call_model(
        self, prompt: Union[Conversation, List[dict]], generations_this_call: int = 1
    ) -> List[Union[Message, None]]:
        """Rate-limited call to Azure OpenAI API."""

        # Proactive rate limiting
        try:
            self._global_limiter.wait_if_needed(prompt, deployment=self.name)
        except RuntimeError as e:
            logging.error(str(e))
            return [None] * generations_this_call

        # Call parent API
        try:
            responses = super()._call_model(prompt, generations_this_call)
        except openai.APIError as e:
            if e.status_code == 403:
                logging.error(f"Quota exhausted for {self.name}")
                return [None] * generations_this_call
            raise

        # Reactive token tracking
        if responses:
            self._global_limiter.track_response_tokens(
                deployment=self.name,
                responses=responses
            )

        return responses


DEFAULT_CLASS = "AzureRateLimitedGenerator"
```

## Success Criteria

✅ **Class Structure Correct**
- Inherits from AzureOpenAIGenerator (not directly from OpenAICompatible)
- DEFAULT_PARAMS extends parent correctly
- Global limiter shared across all instances

✅ **_call_model() Override Works**
- Proactive check BEFORE super() call
- Reactive tracking AFTER super() call
- Graceful degradation (None not crash)

✅ **Thread Safety**
- Global limiter lock protects initialization
- Rate limits respected globally across threads
- Parallel calls properly serialized

✅ **Error Handling**
- RuntimeError caught gracefully
- 403 (quota) handled differently from 429 (throttling)
- Backoff decorator still works for 429

✅ **Integration with generate()**
- Works with single generation
- Works with batch generation (if supported)
- Works with parallelized generation

## Files to Create/Modify

1. **garak/generators/azure_ratelimited.py** - AzureRateLimitedGenerator class
2. **garak/generators/__init__.py** - Register new generator
3. Modify **garak/generators/azure.py** - Optional base enhancements

## Related Documentation
- base.py:20-237 - Generator base class and patterns
- openai.py:200-290 - _call_model() with @backoff decorator
- openai.py:126-191 - OpenAICompatible class structure
- base.py:132-224 - generate() orchestration
- ratelimited_openai.py:213-294 - Reference implementation
