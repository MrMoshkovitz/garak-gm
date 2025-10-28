# Fix AttributeError in atkgen probe - Update Turn object access pattern

## Summary

Fixes AttributeError crash in `atkgen` probe by updating code to use correct `Turn` object structure (`turns[-1].content.text` instead of `turns[-1].text`).

## Problem

The `atkgen.Tox` probe (and likely other atkgen probes) crashed immediately when attempting to log conversation output:

```python
AttributeError: 'Turn' object has no attribute 'text'
  File "garak/probes/atkgen.py", line 208
    f"atkgen: 🦜 model: {this_attempt.prompt.turns[-1].text}"
```

This prevented the entire atkgen probe family from running.

## Root Cause

The `Turn` object structure changed to use a nested architecture:
- `Turn` has a `.content` attribute (which is a `Message` object)
- `Message` has the `.text` attribute

The code was attempting to access `.text` directly on the `Turn` object, which no longer exists.

## Solution

Updated line 208 in `garak/probes/atkgen.py`:

**Before:**
```python
f"atkgen: 🦜 model: {Style.BRIGHT}{this_attempt.prompt.turns[-1].text}{Style.RESET_ALL}"
```

**After:**
```python
f"atkgen: 🦜 model: {Style.BRIGHT}{this_attempt.prompt.turns[-1].content.text}{Style.RESET_ALL}"
```

## Changes

- **Modified**: `garak/probes/atkgen.py` (1 line changed)
  - Line 208: Changed `.turns[-1].text` to `.turns[-1].content.text`

## Testing

✅ **Verified the fix works:**
1. Ran `garak --target_type openai_rated --target_name gpt-3.5-turbo-instruct --probes atkgen.Tox --generations 10 -vv`
2. Probe executes without AttributeError
3. Conversation output displays correctly: `atkgen: 🦜 model: ...`
4. No other instances of this pattern found in the file

## Impact

- ✅ Fixes crash in atkgen probe family
- ✅ Allows atkgen probes to run successfully
- ✅ No breaking changes to other code
- ✅ Minimal change (1 line)

## Backward Compatibility

✅ Fully compatible - only fixes broken functionality

## Related Issue

Closes #XXXX (you'll fill this in after creating the issue)

---

**Checklist:**
- [x] Bug identified and root cause understood
- [x] Fix implemented with minimal change
- [x] Code tested and verified working
- [x] No other instances of the pattern found in file
- [x] No breaking changes introduced
