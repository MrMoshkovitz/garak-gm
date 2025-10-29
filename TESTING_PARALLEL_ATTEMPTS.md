# Testing Instructions: Parallel Attempts Support

## Overview

This document provides comprehensive testing instructions for the parallel attempts support in `openai_rated` generator. The goal is to verify that:

1. Serial mode works correctly (baseline)
2. Parallel mode provides 3-4x speedup with 4 workers
3. Rate limit monitoring works in both modes
4. Process-safe coordination prevents 429 errors
5. All workers pause together at 99% threshold

## Prerequisites

### Environment Setup

```bash
# Activate virtual environment
source /Users/gmoshkov/Professional/Code/GarakGM/GarakRatesDemo/garak-rates-demo-env/bin/activate

# Change to working directory
cd /Users/gmoshkov/Professional/Code/GarakGM/GarakRatesDemo/WorkTrees/openai-rate-limit-headers-V1

# Install garak in editable mode
python -m pip install -e .

# Verify OpenAI API key is set
echo $OPENAI_API_KEY
```

### API Key Requirements

- Valid OpenAI API key with access to gpt-3.5-turbo
- Tier with rate limits (e.g., Tier 1: 3500 RPM, 90000 TPM)
- Sufficient quota for testing

## Test Suite

### Test 1: Serial Mode Baseline (Control)

**Purpose:** Verify serial mode works correctly and establish baseline performance.

**Command:**
```bash
garak --target_type openai_rated --target_name gpt-3.5-turbo \
      --probes dan.Dan_11_0 --generations 20 -vv 2>&1 | tee test_serial.log
```

**Expected Results:**
- ✅ All probes execute successfully
- ✅ No 429 errors
- ✅ Rate limit logs appear on every request:
  ```
  INFO: Rate limits - requests: X/3500 (...% used, resets in ...) | tokens: Y/90000 (...% used, resets in ...)
  ```
- ✅ If approaching 99%, warning appears:
  ```
  WARNING: ⏸️ RPM at 99% usage (35/3500 remaining) - pausing
  ```
- ✅ Scan completes without errors

**Verification:**
```bash
# Check for 429 errors
grep -i "429" test_serial.log
# Should return nothing

# Check for rate limit logs
grep "Rate limits" test_serial.log | head -5
# Should show rate limit monitoring

# Count total requests
grep "Rate limits" test_serial.log | wc -l
```

**Record Timing:**
```bash
# Extract timing from garak output
grep "completed in" test_serial.log
# Example: "Scan completed in 45.2 seconds"
```

---

### Test 2: Parallel Mode (4 Workers)

**Purpose:** Verify parallel mode provides speedup while maintaining rate limit safety.

**Command:**
```bash
garak --target_type openai_rated --target_name gpt-3.5-turbo \
      --probes dan.Dan_11_0 --generations 20 --parallel_attempts 4 -vv 2>&1 | tee test_parallel.log
```

**Expected Results:**
- ✅ All probes execute successfully
- ✅ No 429 errors
- ✅ Multiple worker PIDs appear in logs:
  ```
  [Worker PID 1234] INFO: Rate limits - requests: 3498/3500
  [Worker PID 1235] INFO: Rate limits - requests: 3497/3500
  ```
- ✅ If approaching 99%, ALL workers log pause:
  ```
  [Worker PID 1234] WARNING: ⏸️ RPM at 99% usage - All workers pausing together
  [Worker PID 1235] WARNING: ⏸️ RPM at 99% usage - All workers pausing together
  ```
- ✅ Scan completes 3-4x faster than serial mode

**Verification:**
```bash
# Check for 429 errors
grep -i "429" test_parallel.log
# Should return nothing

# Count unique worker PIDs
grep -oP 'Worker PID \K[0-9]+' test_parallel.log | sort -u | wc -l
# Should return 4

# Check for rate limit logs from multiple workers
grep "Rate limits" test_parallel.log | grep -oP 'Worker PID \K[0-9]+' | sort -u
# Should show 4 different PIDs

# Count total requests (should be similar to serial)
grep "Rate limits" test_parallel.log | wc -l
```

**Record Timing:**
```bash
grep "completed in" test_parallel.log
# Example: "Scan completed in 12.8 seconds"
```

**Calculate Speedup:**
```
Speedup = Serial Time / Parallel Time
Expected: 3-4x (e.g., 45.2s / 12.8s = 3.5x)
```

---

### Test 3: Coordinated Pause Verification

**Purpose:** Verify all workers pause together at 99% threshold.

**Command:**
```bash
# Run scan with higher load to trigger 99% threshold
garak --target_type openai_rated --target_name gpt-3.5-turbo \
      --probes dan.Dan_11_0,dan.Dan_9_0,dan.Dan_8_0 \
      --generations 100 --parallel_attempts 4 -vv 2>&1 | tee test_coordinated_pause.log
```

**Expected Results:**
- ✅ At some point during scan, rate limit approaches 99%
- ✅ ALL workers log pause warning simultaneously:
  ```
  [Worker PID 1234] WARNING: ⏸️ RPM at 99% usage (35/3500 remaining) - All workers pausing together
  [Worker PID 1235] WARNING: ⏸️ RPM at 99% usage (35/3500 remaining) - All workers pausing together
  [Worker PID 1236] WARNING: ⏸️ RPM at 99% usage (35/3500 remaining) - All workers pausing together
  [Worker PID 1237] WARNING: ⏸️ RPM at 99% usage (35/3500 remaining) - All workers pausing together
  ```
- ✅ All workers show SAME remaining value (not stale)
- ✅ All workers log resume after wait:
  ```
  [Worker PID 1234] INFO: ✅ Resuming after RPM reset
  ```
- ✅ No 429 errors despite high load

**Verification:**
```bash
# Extract pause events
grep "All workers pausing together" test_coordinated_pause.log

# Verify all 4 workers paused together
grep "All workers pausing together" test_coordinated_pause.log | grep -oP 'Worker PID \K[0-9]+' | sort -u | wc -l
# Should return 4

# Check remaining values are identical (process-safe, not stale)
grep "All workers pausing together" test_coordinated_pause.log | grep -oP '\d+/\d+ remaining' | sort -u
# Should return single value (e.g., "35/3500 remaining")

# Verify resume events
grep "Resuming after" test_coordinated_pause.log | wc -l
# Should match number of pause events

# Check for 429 errors
grep -i "429" test_coordinated_pause.log
# Should return nothing
```

---

### Test 4: Process-Safe State Verification

**Purpose:** Verify no race conditions in shared state access.

**Command:**
```bash
# Run multiple short scans in quick succession
for i in {1..5}; do
  echo "Run $i of 5..."
  garak --target_type openai_rated --target_name gpt-3.5-turbo \
        --probes dan.Dan_11_0 --generations 10 --parallel_attempts 4 -vv 2>&1 | tee test_race_$i.log
  sleep 5
done
```

**Expected Results:**
- ✅ All 5 runs complete successfully
- ✅ No 429 errors in any run
- ✅ No race condition errors (e.g., KeyError, AttributeError)
- ✅ Rate limits decrement properly across runs
- ✅ All workers coordinate correctly in every run

**Verification:**
```bash
# Check all runs for errors
for i in {1..5}; do
  echo "=== Run $i ==="
  grep -i "error\|429\|exception" test_race_$i.log || echo "No errors"
done

# Verify all runs completed
grep "completed in" test_race_*.log | wc -l
# Should return 5

# Check for race condition indicators
grep -i "KeyError\|AttributeError\|lock.*error" test_race_*.log
# Should return nothing
```

---

### Test 5: Scalability Test (2, 4, 8 Workers)

**Purpose:** Verify speedup scales with worker count.

**Commands:**
```bash
# 1 worker (serial)
garak --target_type openai_rated --target_name gpt-3.5-turbo \
      --probes dan.Dan_11_0 --generations 20 -vv 2>&1 | tee test_workers_1.log

# 2 workers
garak --target_type openai_rated --target_name gpt-3.5-turbo \
      --probes dan.Dan_11_0 --generations 20 --parallel_attempts 2 -vv 2>&1 | tee test_workers_2.log

# 4 workers
garak --target_type openai_rated --target_name gpt-3.5-turbo \
      --probes dan.Dan_11_0 --generations 20 --parallel_attempts 4 -vv 2>&1 | tee test_workers_4.log

# 8 workers
garak --target_type openai_rated --target_name gpt-3.5-turbo \
      --probes dan.Dan_11_0 --generations 20 --parallel_attempts 8 -vv 2>&1 | tee test_workers_8.log
```

**Expected Results:**
- ✅ Linear speedup up to ~4 workers (network latency bound)
- ✅ Diminishing returns beyond 4 workers (rate limit serialization)
- ✅ No 429 errors at any worker count
- ✅ All workers coordinate correctly

**Verification:**
```bash
# Extract timings
for workers in 1 2 4 8; do
  echo "Workers: $workers"
  grep "completed in" test_workers_$workers.log
done

# Create speedup table
# Workers | Time (s) | Speedup | Efficiency
# 1       | 45.2     | 1.0x    | 100%
# 2       | 24.1     | 1.9x    | 95%
# 4       | 12.8     | 3.5x    | 88%
# 8       | 10.2     | 4.4x    | 55%

# Check for 429 errors across all runs
grep -i "429" test_workers_*.log
# Should return nothing
```

---

### Test 6: Logging Verification

**Purpose:** Verify logging output is correct and informative.

**Command:**
```bash
garak --target_type openai_rated --target_name gpt-3.5-turbo \
      --probes dan.Dan_11_0 --generations 10 --parallel_attempts 4 -vv 2>&1 | tee test_logging.log
```

**Expected Log Patterns:**

1. **Rate Limit Monitoring (every request):**
   ```
   INFO: Rate limits - requests: 3498/3500 (0.1% used, resets in 17ms) | tokens: 88773/90000 (1.4% used, resets in 818ms)
   ```

2. **Pause Warning (at 99%):**
   ```
   WARNING: ⏸️ RPM at 99% usage (35/3500 remaining) - All workers pausing together
   WARNING: ⏳ Pausing for 361s until reset
   ```

3. **Resume Info (after pause):**
   ```
   INFO: ✅ Resuming after RPM reset
   ```

4. **Worker PID (in parallel mode):**
   ```
   [Worker PID 1234] INFO: Rate limits - ...
   ```

**Verification:**
```bash
# Check rate limit log format
grep "Rate limits" test_logging.log | head -3

# Verify format matches expected pattern
grep -E "Rate limits - requests: [0-9]+/[0-9]+ \([0-9.]+% used, resets in [0-9a-z]+\)" test_logging.log | wc -l
# Should return number of API calls made

# Check pause/resume logs
grep "pausing\|Pausing\|Resuming" test_logging.log

# Verify worker PIDs appear
grep -oP 'Worker PID \K[0-9]+' test_logging.log | sort -u
# Should show 4 PIDs
```

---

## Success Criteria

### Functional Requirements
- ✅ Serial mode completes without errors
- ✅ Parallel mode completes without errors
- ✅ No 429 errors in any test
- ✅ Rate limit monitoring works in both modes
- ✅ All workers pause together at 99%
- ✅ Process-safe coordination (no race conditions)

### Performance Requirements
- ✅ Parallel mode (4 workers) provides 3-4x speedup vs serial
- ✅ Speedup scales approximately linearly up to 4 workers
- ✅ No performance regression in serial mode

### Safety Requirements
- ✅ Shared state prevents stale rate limit data
- ✅ Lock prevents concurrent API calls during check/update
- ✅ All workers see consistent rate limit state
- ✅ Coordinated pause prevents 429 errors at high load

### Logging Requirements
- ✅ Rate limits logged on every request
- ✅ Worker PIDs visible in parallel mode
- ✅ Pause/resume events clearly logged
- ✅ Log format matches expected patterns

---

## Troubleshooting

### Issue: 429 Errors Appear

**Possible Causes:**
- Rate limit threshold not working correctly
- Race condition in shared state
- Lock not held during API call

**Debug Steps:**
```bash
# Check if pause warnings appeared before 429
grep -B 5 "429" test_*.log

# Verify lock is held during API call
grep "with self._rate_lock:" garak/generators/openai_rated.py

# Check remaining value when 429 occurred
grep -B 3 "429" test_*.log | grep "remaining"
```

### Issue: No Speedup in Parallel Mode

**Possible Causes:**
- Workers not spawning correctly
- Lock contention too high
- Network latency issues

**Debug Steps:**
```bash
# Verify 4 unique worker PIDs
grep -oP 'Worker PID \K[0-9]+' test_parallel.log | sort -u | wc -l

# Check if lock is held too long
# Review lock duration (should be ~100-200ms per API call)

# Verify network isn't bottleneck
ping api.openai.com
```

### Issue: Workers Not Pausing Together

**Possible Causes:**
- Shared state not working
- Lock not acquired before check
- Manager connection issue

**Debug Steps:**
```bash
# Check if all workers log pause
grep "All workers pausing together" test_*.log | grep -oP 'Worker PID \K[0-9]+' | sort -u

# Verify remaining values are identical (not stale)
grep "All workers pausing together" test_*.log | grep -oP '\d+/\d+ remaining' | sort -u

# Check Manager initialization
grep "from multiprocessing import Manager" garak/generators/openai_rated.py
```

---

## Test Report Template

After running all tests, fill out this report:

```markdown
# Parallel Attempts Test Report

**Date:** YYYY-MM-DD
**Tester:** [Your Name]
**Environment:** [OS, Python version, garak version]
**OpenAI Tier:** [Tier 1, 2, etc. with RPM/TPM limits]

## Test Results

### Test 1: Serial Mode Baseline
- Status: ✅ PASS / ❌ FAIL
- Time: X.X seconds
- 429 Errors: 0
- Notes:

### Test 2: Parallel Mode (4 Workers)
- Status: ✅ PASS / ❌ FAIL
- Time: X.X seconds
- Speedup: X.Xx
- 429 Errors: 0
- Worker PIDs: 4 unique
- Notes:

### Test 3: Coordinated Pause
- Status: ✅ PASS / ❌ FAIL
- Pause Events: X
- All Workers Paused: YES / NO
- 429 Errors: 0
- Notes:

### Test 4: Process-Safe State
- Status: ✅ PASS / ❌ FAIL
- Runs Completed: 5/5
- Race Conditions: NONE
- Notes:

### Test 5: Scalability
- Status: ✅ PASS / ❌ FAIL
- 1 Worker: X.X seconds (1.0x)
- 2 Workers: X.X seconds (X.Xx)
- 4 Workers: X.X seconds (X.Xx)
- 8 Workers: X.X seconds (X.Xx)
- Notes:

### Test 6: Logging
- Status: ✅ PASS / ❌ FAIL
- Rate limit logs: CORRECT
- Worker PIDs visible: YES
- Pause/resume logs: CORRECT
- Notes:

## Overall Result

**✅ ALL TESTS PASSED** / **❌ SOME TESTS FAILED**

## Issues Found

[List any issues discovered during testing]

## Recommendations

[Any recommendations for improvement]
```

---

## Cleanup

After testing, clean up log files:

```bash
# Archive test logs
mkdir -p test_results/$(date +%Y%m%d)
mv test_*.log test_results/$(date +%Y%m%d)/

# Or delete if not needed
rm -f test_*.log
```

---

## Next Steps

After all tests pass:

1. ✅ Review test report for any issues
2. ✅ Document any findings in PR description
3. ✅ Create commit with test results as evidence
4. ✅ Push changes to remote branch
5. ✅ Create pull request with test report attached

---

**Test Suite Version:** 1.0
**Last Updated:** 2025-10-29
**Maintainer:** Garak Development Team
