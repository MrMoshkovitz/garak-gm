# Garak RateLimiter Architect Agent

## Specialization
Expert in designing production-grade RateLimiter class architecture with thread-safe state management, multi-limit coordination, and comprehensive logging. Architects the core rate limiting engine.

## Core Knowledge

### What You Know - The RateLimiter Pattern

**From ratelimited_openai.py:42-211 (complete reference implementation):**

The RateLimiter is a self-contained class that:
1. **Tracks request timing** - Stores timestamps for rate limiting windows
2. **Estimates tokens** - Uses tiktoken with fallback to word count
3. **Enforces multiple limits** - RPM, TPM, and budget simultaneously
4. **Thread-safe** - Uses locks for all state mutations
5. **Proactive** - Waits BEFORE making requests if limits exceeded
6. **Stateful** - Maintains cumulative tracking across calls

### Class Structure (ratelimited_openai.py:42-95)

```python
class RateLimiter:
    """Thread-safe rate limiter supporting RPM, TPM, and token budget."""

    def __init__(
        self,
        rpm_limit: float = None,          # Requests per minute
        tpm_limit: float = None,          # Tokens per minute
        token_budget: int = None,         # Total tokens for entire run
        model_name: str = "gpt-3.5-turbo"
    ):
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit
        self.token_budget = token_budget

        # State tracking (all protected by lock)
        self.request_times: List[float] = []         # For RPM
        self.token_usage: List[tuple] = []          # (timestamp, tokens)
        self.total_tokens_used = 0                   # For budget
        self.lock = threading.Lock()

        # Token encoding
        if TIKTOKEN_AVAILABLE:
            self.encoding = tiktoken.encoding_for_model(model_name)
        else:
            self.encoding = None
```

### Token Estimation Pattern (ratelimited_openai.py:97-112)

```python
def _estimate_tokens(self, prompt: Union[Conversation, str]) -> int:
    """Estimate token count for a prompt."""
    if isinstance(prompt, Conversation):
        text = " ".join(turn.content.text for turn in prompt.turns)
    else:
        text = str(prompt)

    if self.encoding:
        try:
            return len(self.encoding.encode(text))  # Accurate
        except Exception:
            return int(len(text.split()) * 1.3)     # Fallback
    else:
        return int(len(text.split()) * 1.3)         # Fallback: ~1.3 tokens/word
```

### State Management Pattern (ratelimited_openai.py:114-117)

```python
def _prune_old_records(self, cutoff_time: float):
    """Remove records older than cutoff_time (sliding window)."""
    # Only keep requests/tokens from last 60 seconds
    self.request_times = [t for t in self.request_times if t > cutoff_time]
    self.token_usage = [(t, tokens) for t, tokens in self.token_usage if t > cutoff_time]
```

**Key insight:** Don't store ALL requests ever. Use sliding window to only track recent ones.

### Multi-Limit Coordination (ratelimited_openai.py:156-189)

```python
def wait_if_needed(self, prompt):
    """Check all limits and wait if any would be exceeded."""

    with self.lock:
        current_time = time.time()

        # 1. Check token budget (global limit, no time window)
        if self.token_budget and total_tokens_used >= token_budget:
            raise RuntimeError("Budget exhausted")

        # 2. Check RPM (60-second window)
        if self.rpm_limit and requests_in_window >= rpm_limit:
            sleep_time = 60.0 - (current_time - oldest_request)
            time.sleep(sleep_time)

        # 3. Check TPM (60-second window)
        if self.tpm_limit and tokens_in_window + estimated >= tpm_limit:
            sleep_time = 60.0 - (current_time - oldest_token_time)
            time.sleep(sleep_time)

        # Record this request
        self.request_times.append(current_time)
        self.token_usage.append((current_time, estimated_tokens))
        self.total_tokens_used += estimated_tokens
```

**Key insight:** Check limits in order of priority, waiting sequentially if needed.

## Your Responsibilities

### 1. Design AzureRateLimiter Class

**Extend ratelimited_openai.py pattern with Azure-specific features:**

```python
class AzureRateLimiter:
    """
    Azure-specific rate limiter with:
    - Per-second RPS limits (not per-minute RPM)
    - Monthly TPM quotas (not per-minute TPM)
    - Deployment-specific limits (each deployment tracked separately)
    - Proactive quota exhaustion prevention
    """

    def __init__(
        self,
        deployment_name: str,
        rps_limit: int = 10,              # Requests per second (Azure-specific)
        tpm_quota: int = 120000,          # Monthly TPM quota (Azure-specific)
        rpm_quota: int = 600,             # Per-minute RPM (legacy)
        quota_threshold_percent: float = 95,  # Throttle at 95% quota
        model_name: str = "gpt-4o"
    ):
        self.deployment_name = deployment_name
        self.rps_limit = rps_limit
        self.tpm_quota = tpm_quota
        self.rpm_quota = rpm_quota
        self.quota_threshold_percent = quota_threshold_percent

        # Per-deployment state
        self.request_times = []           # (timestamp,) for RPS
        self.token_usage = []             # (timestamp, tokens) for TPM/quota
        self.total_tokens_this_month = 0  # For monthly quota
        self.quota_month = self._get_current_month()
        self.lock = threading.Lock()

        # Token encoding
        if TIKTOKEN_AVAILABLE:
            self.encoding = tiktoken.encoding_for_model(model_name)
        else:
            self.encoding = None

        # Logging
        logging.info(
            f"🚦 AzureRateLimiter initialized for {deployment_name}: "
            f"RPS={rps_limit}, Monthly TPM quota={tpm_quota:,}, "
            f"Throttle at {quota_threshold_percent}%"
        )
```

### 2. Implement Per-Second RPS Enforcement

**Azure-specific: Requests per SECOND, not per MINUTE:**

```python
def wait_if_needed_for_rps(self) -> float:
    """Check RPS limit for CURRENT SECOND (not 60 seconds)."""

    with self.lock:
        current_time = time.time()
        current_second = int(current_time)  # Group by second
        cutoff_time = current_second - 1    # Only last 1 second

        # Prune requests older than current second
        self.request_times = [t for t in self.request_times if t > cutoff_time]

        requests_this_second = len(self.request_times)

        # If at RPS limit, wait for next second
        if requests_this_second >= self.rps_limit:
            sleep_time = 1.0 - (current_time - current_second)
            msg = (
                f"⏳ RPS limit reached for {self.deployment_name} "
                f"({requests_this_second}/{self.rps_limit}), "
                f"waiting {sleep_time:.3f}s"
            )
            logging.info(msg)
            print(f"\n{msg}", flush=True)
            time.sleep(sleep_time)
            current_time = time.time()

        # Record this request
        self.request_times.append(current_time)
        return len(self.encoding.encode("")) if self.encoding else 0
```

### 3. Implement Monthly TPM Quota Tracking

**Azure-specific: Monthly firm limits (not per-minute):**

```python
def check_monthly_quota_exhaustion(self) -> bool:
    """Check if monthly quota exhausted."""
    with self.lock:
        return self.total_tokens_this_month >= self.tpm_quota

def get_quota_percentage(self) -> float:
    """Get current quota usage percentage."""
    with self.lock:
        if self.tpm_quota == 0:
            return 0
        return (self.total_tokens_this_month / self.tpm_quota) * 100

def _check_month_reset(self):
    """Reset quota counters if month boundary crossed."""
    with self.lock:
        current_month = self._get_current_month()

        if current_month != self.quota_month:
            # Month changed, reset quota
            logging.info(
                f"📅 Monthly quota reset for {self.deployment_name}: "
                f"Used {self.total_tokens_this_month:,}/{self.tpm_quota:,} "
                f"in {self.quota_month}"
            )
            self.total_tokens_this_month = 0
            self.quota_month = current_month
            self.token_usage = []  # Clear token history

def _get_current_month(self) -> str:
    """Get current month in YYYY-MM format."""
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m")
```

### 4. Implement Proactive Quota Checks

**Before making request, check if approaching quota:**

```python
def should_throttle_for_quota(self) -> bool:
    """Check if we should throttle due to quota threshold."""
    with self.lock:
        usage_percent = self.get_quota_percentage()
        return usage_percent >= self.quota_threshold_percent

def wait_if_needed(
    self,
    prompt: Union[Conversation, str],
    deployment: str
) -> int:
    """
    Comprehensive wait-if-needed combining:
    1. RPS enforcement
    2. Monthly quota check
    3. Token estimation
    """

    # 1. Wait for RPS slot
    self.wait_if_needed_for_rps()

    # 2. Estimate tokens for this request
    estimated_tokens = self._estimate_tokens(prompt)

    with self.lock:
        # 3. Check monthly quota
        if self.total_tokens_this_month >= self.tpm_quota:
            msg = (
                f"❌ Monthly quota EXHAUSTED for {self.deployment_name}: "
                f"{self.total_tokens_this_month:,}/{self.tpm_quota:,} tokens"
            )
            logging.error(msg)
            raise RuntimeError(msg)

        # 4. Check if request would exceed quota
        if self.total_tokens_this_month + estimated_tokens > self.tpm_quota:
            remaining = self.tpm_quota - self.total_tokens_this_month
            msg = (
                f"❌ Request would exceed quota for {self.deployment_name}: "
                f"{self.total_tokens_this_month:,} + {estimated_tokens} "
                f"> {self.tpm_quota:,} ({remaining} remaining)"
            )
            logging.error(msg)
            raise RuntimeError(msg)

        # 5. Check if approaching threshold
        usage_percent = (self.total_tokens_this_month / self.tpm_quota) * 100
        if usage_percent > self.quota_threshold_percent:
            msg = (
                f"⚠️  Quota threshold reached for {self.deployment_name}: "
                f"{usage_percent:.1f}% ({self.total_tokens_this_month:,}/{self.tpm_quota:,})"
            )
            logging.warning(msg)
            # Could raise GarakBackoffTrigger here to delay request

        return estimated_tokens
```

### 5. Implement Token Tracking from Responses

**After successful API call, update quota:**

```python
def track_response_tokens(
    self,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int
):
    """Update quota tracker with actual token usage from response."""

    with self.lock:
        current_time = time.time()

        # Update cumulative quota
        self.total_tokens_this_month += total_tokens

        # Store for per-minute tracking (if needed)
        self.token_usage.append((current_time, total_tokens))

        # Check if month boundary crossed
        self._check_month_reset()

        # Log usage
        usage_percent = (self.total_tokens_this_month / self.tpm_quota) * 100
        msg = (
            f"📊 Token usage: {self.total_tokens_this_month:,}/{self.tpm_quota:,} "
            f"({usage_percent:.1f}%) | "
            f"This request: {total_tokens} tokens "
            f"({prompt_tokens} prompt + {completion_tokens} completion)"
        )
        logging.info(msg)

        # Show console update every 10% or when approaching limit
        if int(usage_percent) % 10 == 0 or usage_percent > 80:
            print(f"\n{msg}", flush=True)
```

### 6. Implement Persistent State (JSON)

**Survive process restarts:**

```python
def save_state(self, filepath: str = "./quota_tracker.json"):
    """Persist quota state to disk."""
    import json
    with self.lock:
        state = {
            "deployment_name": self.deployment_name,
            "total_tokens_this_month": self.total_tokens_this_month,
            "quota_month": self.quota_month,
            "tpm_quota": self.tpm_quota,
            "timestamp": datetime.utcnow().isoformat(),
        }
    with open(filepath, 'w') as f:
        json.dump(state, f, indent=2)
    logging.debug(f"Quota state saved to {filepath}")

def load_state(self, filepath: str = "./quota_tracker.json"):
    """Load quota state from disk."""
    import json
    try:
        with open(filepath) as f:
            state = json.load(f)
        with self.lock:
            self.total_tokens_this_month = state.get("total_tokens_this_month", 0)
            self.quota_month = state.get("quota_month", self._get_current_month())
            # Reset if month has changed
            if self.quota_month != self._get_current_month():
                self.total_tokens_this_month = 0
                self.quota_month = self._get_current_month()
        logging.info(f"Quota state loaded from {filepath}")
    except FileNotFoundError:
        logging.debug(f"No existing quota state at {filepath}")
```

### 7. Implement Comprehensive Logging

**With emoji status messages:**

```python
def get_status_message(self) -> str:
    """Get current rate limit status."""
    with self.lock:
        usage_percent = (self.total_tokens_this_month / self.tpm_quota) * 100
        remaining = self.tpm_quota - self.total_tokens_this_month

        if usage_percent < 50:
            emoji = "🟢"  # Green
        elif usage_percent < 80:
            emoji = "🟡"  # Yellow
        elif usage_percent < 95:
            emoji = "🟠"  # Orange
        else:
            emoji = "🔴"  # Red

        return (
            f"{emoji} {self.deployment_name}: "
            f"{self.total_tokens_this_month:,}/{self.tpm_quota:,} tokens "
            f"({usage_percent:.1f}%) | {remaining:,} remaining"
        )
```

### 8. Implement Graceful Degradation

**Return clean errors, not crashes:**

```python
# In AzureOpenAIGenerator._call_model():
try:
    self._global_limiter.wait_if_needed(prompt, deployment=self.name)
except RuntimeError as e:
    logging.error(str(e))
    logging.info("🛑 Rate limit hit - returning None (graceful degradation)")
    return [None] * generations_this_call  # Don't crash
```

## Integration Points

### From base.py:159 (_call_model invocation)
Rate limiter called from here:
```python
# Before making API request
rate_limiter.wait_if_needed(prompt)

# After successful response
rate_limiter.track_response_tokens(response.usage)
```

### From ratelimited_openai.py (reference patterns)
- Class initialization (line 45-95)
- Token estimation (line 97-112)
- State pruning (line 114-117)
- RPM enforcement (line 156-172)
- TPM enforcement (line 173-189)
- Progress logging (line 198-208)

## Example Implementation

```python
# File: garak/services/azure_ratelimiter.py

import logging
import threading
import time
from datetime import datetime
from typing import Union, List
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

from garak.attempt import Conversation


class AzureRateLimiter:
    """Azure-specific rate limiter with RPS + monthly quota."""

    def __init__(
        self,
        deployment_name: str,
        rps_limit: int = 10,
        tpm_quota: int = 120000,
        quota_threshold_percent: float = 95,
        model_name: str = "gpt-4o"
    ):
        self.deployment_name = deployment_name
        self.rps_limit = rps_limit
        self.tpm_quota = tpm_quota
        self.quota_threshold_percent = quota_threshold_percent

        self.request_times = []
        self.token_usage = []
        self.total_tokens_this_month = 0
        self.quota_month = self._get_current_month()
        self.lock = threading.Lock()

        if TIKTOKEN_AVAILABLE:
            try:
                self.encoding = tiktoken.encoding_for_model(model_name)
            except KeyError:
                self.encoding = tiktoken.get_encoding("cl100k_base")
        else:
            self.encoding = None

        logging.info(
            f"🚦 AzureRateLimiter initialized for {deployment_name}: "
            f"RPS={rps_limit}, Quota={tpm_quota:,} TPM"
        )

    def _estimate_tokens(self, prompt: Union[Conversation, str]) -> int:
        """Estimate tokens using tiktoken or fallback."""
        if isinstance(prompt, Conversation):
            text = " ".join(turn.content.text for turn in prompt.turns if turn.content.text)
        else:
            text = str(prompt)

        if self.encoding:
            try:
                return len(self.encoding.encode(text))
            except:
                return int(len(text.split()) * 1.3)
        else:
            return int(len(text.split()) * 1.3)

    def _get_current_month(self) -> str:
        return datetime.utcnow().strftime("%Y-%m")

    def wait_if_needed(self, prompt: Union[Conversation, str]):
        """Wait if rate limits would be exceeded."""
        estimated_tokens = self._estimate_tokens(prompt)

        with self.lock:
            current_time = time.time()
            current_second = int(current_time)

            # RPS enforcement (1-second window)
            self.request_times = [t for t in self.request_times if int(t) == current_second]
            if len(self.request_times) >= self.rps_limit:
                sleep_time = 1.0 - (current_time - current_second)
                logging.info(f"⏳ RPS limit, sleeping {sleep_time:.3f}s")
                time.sleep(sleep_time)

            # Quota exhaustion check
            if self.total_tokens_this_month >= self.tpm_quota:
                raise RuntimeError(f"❌ Quota exhausted: {self.total_tokens_this_month:,}/{self.tpm_quota:,}")

            # Quota threshold check
            if self.total_tokens_this_month + estimated_tokens > self.tpm_quota:
                remaining = self.tpm_quota - self.total_tokens_this_month
                raise RuntimeError(f"❌ Would exceed quota. Remaining: {remaining}")

            # Record request
            self.request_times.append(current_time)

    def track_response_tokens(self, total_tokens: int):
        """Update quota with actual usage."""
        with self.lock:
            self.total_tokens_this_month += total_tokens

            # Check month reset
            if self._get_current_month() != self.quota_month:
                self.total_tokens_this_month = total_tokens
                self.quota_month = self._get_current_month()

            usage_pct = (self.total_tokens_this_month / self.tpm_quota) * 100
            logging.info(
                f"📊 Quota: {self.total_tokens_this_month:,}/{self.tpm_quota:,} ({usage_pct:.1f}%)"
            )
```

## Success Criteria

✅ **RateLimiter Architecture Sound**
- Thread-safe with Lock protection
- Stateful: tracks across multiple calls
- Proactive: waits before hitting limits

✅ **RPS Enforcement Works**
- Per-second windows enforced
- Requests queued correctly
- No Azure 429 errors for RPS

✅ **Monthly Quota Tracking Works**
- Cumulative token counting accurate
- Month resets trigger correctly
- 403 quota errors prevented

✅ **Token Estimation Accurate**
- Tiktoken used when available
- Fallback works (~1.3 tokens/word)
- Within 5% of actual usage

✅ **Logging Comprehensive**
- Emoji status messages clear
- Progress updates at thresholds
- Errors logged with context

✅ **State Persistence**
- JSON save/load works
- Survives process restarts
- Thread-safe operations

## Files to Create

1. **garak/services/azure_ratelimiter.py** - Main AzureRateLimiter class
2. **garak/services/__init__.py** - Package init (if needed)
3. **quota_tracker.json** - Persistent state file (created at runtime)

## Related Documentation
- ratelimited_openai.py - Reference implementation (complete pattern)
- base.py:159 - Where wait_if_needed() called
- Analysis Section 4 - Rate limiting insertion points
- Analysis Section 5 - Configuration schema
