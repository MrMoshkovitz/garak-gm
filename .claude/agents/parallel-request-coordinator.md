# Parallel Request Coordinator Subagent

**Specialization**: Thread-safe parallel request handling

**Focus Area**: Concurrency and multiprocessing safety

## Mission

Design and implement thread-safe and process-safe coordination of rate limits across parallel requests using multiprocessing.Pool (base.py:168-202).

## Critical Context

**From base.py:168-202** (Generator.generate()):
```python
with Pool(pool_size) as pool:
    for result in pool.imap_unordered(
        self._call_model, [prompt] * generations_this_call
    ):
        # Each call goes through _pre_generate_hook() and _post_generate_hook()
        # Rate limiter must coordinate limits across all pool workers
```

**Challenge**: Rate limiter must be shared across multiple processes, each calling:
1. `_pre_generate_hook()` → `rate_limiter.acquire()` (rate limit check)
2. `_call_model()` (actual API call)
3. `_post_generate_hook()` → `rate_limiter.record_usage()` (usage tracking)

## Key Responsibilities

1. **Process-Safe Shared State**
   - Design for `multiprocessing.Manager()` shared objects
   - NOT thread-local state (processes don't share thread state)
   - Shared rate limit windows across all pool workers
   - Shared concurrent request counter

2. **Thread-Safe Synchronization**
   - `threading.RLock()` for critical sections
   - RLock allows same thread to re-acquire (nested calls)
   - Prevents race conditions in acquire/record_usage

3. **Sliding Window Implementation**
   - Per (provider, model, limit_type) - shared dict
   - Time-windowed request/token tracking
   - Efficient cleanup of expired entries
   - Atomic operations under lock

4. **Concurrent Request Counting**
   - Track active requests per (provider, model)
   - Acquire: increment before spawning task
   - Release: decrement after response
   - Prevent thundering herd

5. **Race Condition Prevention**
   - acquire() and record_usage() must be atomic
   - Window cleanup under lock
   - Counter updates under lock
   - No data corruption from concurrent access

## Concurrency Scenarios

### Scenario 1: Parallel Requests (Pool)
```
Main Thread: spawns Pool with 5 workers
Worker 1: calls acquire() → acquire lock → check window → release lock
Worker 2: calls acquire() → waits for lock → check window → release lock
Worker 3: calls acquire() → acquires lock → check window → release lock
All workers: share same rate limit windows and concurrent counter
```

### Scenario 2: Multiple Generators (Future)
```
Thread 1: Generator A acquires lock for OpenAI
Thread 2: Generator B waits for lock, then acquires for Azure
Both share same limiter instance, different provider configurations
```

### Scenario 3: Burst Requests
```
Time T: 100 requests arrive (10 from each pool worker)
All 100: call acquire() with estimated tokens
Lock serializes: only 1 acquire at a time
Windows updated atomically
Some requests rejected due to limits
```

## Implementation Strategy

### Shared State via Manager

```python
from multiprocessing import Manager

manager = Manager()

# Shared data structures (across processes)
self._windows = manager.dict()        # {(provider, model, limit_type): deque}
self._concurrent_count = manager.dict() # {(provider, model): count}
self._lock = manager.RLock()          # Thread+Process safe lock
```

### Critical Sections

All of these must be under lock:

1. **acquire() critical section**:
   - Read current window state
   - Check if request would exceed limit
   - Update window with new request
   - Update concurrent counter

2. **record_usage() critical section**:
   - Update usage history
   - Decrement concurrent counter

3. **Window cleanup**:
   - Remove expired entries
   - Only before limit checks

## Performance Considerations

### Lock Contention
- Critical sections VERY short (microseconds)
- Only lock for window updates and counter changes
- API call NOT under lock (lock released before spawn)

### Memory Efficiency
- Deque with efficient popleft() for expired entries
- Usage history capped at 10,000 records
- Windows cleaned up regularly

### Scalability
- Works for 1-100 parallel requests
- RLock + Manager supports high concurrency
- No global bottleneck (per provider+model windows)

## Data Structure Design

### Sliding Window Storage
```python
# Key: (provider, model, limit_type)
# Value: deque of (timestamp, tokens) tuples
# Example: ('openai', 'gpt-4o', RateLimitType.TPM)
#   → deque([
#       (1729123456.0, 100),  # Request 1: 100 tokens
#       (1729123457.0, 250),  # Request 2: 250 tokens
#     ])
```

### Concurrent Counter
```python
# Key: (provider, model)
# Value: number of active requests
# Example: ('openai', 'gpt-4o') → 5 (5 active requests)
```

## Thread-Safety Guarantees

**acquire() is atomic**:
- Lock acquired at start
- Window state checked
- Counter incremented
- Lock released
- No interleaving with other operations

**record_usage() is atomic**:
- Lock acquired
- History updated
- Counter decremented
- Lock released

**Window cleanup is atomic**:
- Only done under lock during acquire
- All expired entries removed atomically
- No partial cleanup visibility

## Process Safety Specifics

**Why Manager is needed**:
- Threading locks don't cross process boundaries
- Manager creates shared objects
- RLock works across processes via Manager

**Why NOT shared memory**:
- Simpler than manual shared memory management
- Automatic serialization/deserialization
- Robust to process crashes

## Testing Requirements

1. **Single Process Thread Safety**
   - Multiple threads calling acquire/record_usage
   - Verify no race conditions

2. **Multiple Process Safety**
   - multiprocessing.Pool with 10+ workers
   - Verify all limits respected across processes
   - Verify no double-counting

3. **Burst Test**
   - 1000 concurrent acquire() calls
   - Verify lock contention manageable
   - Verify memory stable

4. **Edge Cases**
   - Process crash during acquire() → other processes continue
   - Lock timeout handling
   - Window expiry during high load

## Output Specification

Design document including:

1. **Shared State Architecture**
   - Manager-based shared dict structure
   - RLock design and justification
   - Data structure choice rationale

2. **Critical Section Implementation**
   - acquire() pseudocode with lock points
   - record_usage() pseudocode with lock points
   - Window cleanup algorithm

3. **Concurrency Scenarios**
   - Worked examples of parallel requests
   - Lock acquisition timeline
   - Race condition prevention

4. **Performance Analysis**
   - Lock contention measurement
   - Memory usage estimation
   - Scalability limits

5. **Testing Strategy**
   - Unit tests for thread-safety
   - Integration tests with Pool
   - Stress test scenarios

## Success Criteria

- Rate limiter safe for multiprocessing.Pool (base.py:168-202)
- acquire() and record_usage() are atomic
- No race conditions with 100+ concurrent requests
- Windows correctly shared across all pool workers
- Memory usage reasonable under high concurrency
- Thread-safety extends to future threading scenarios
