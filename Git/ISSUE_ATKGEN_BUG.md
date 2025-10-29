# AttributeError in atkgen probe - 'Turn' object has no attribute 'text'

## Steps to reproduce

1. Run garak with the atkgen probe:
```bash
garak --target_type openai_rated --target_name gpt-3.5-turbo-instruct --probes atkgen.Tox --generations 100 -vv
```

2. The probe starts executing but crashes immediately with AttributeError

Environment:
- Target: OpenAI gpt-3.5-turbo-instruct
- Probe: atkgen.Tox (likely affects all atkgen probes)

## Were you following a specific guide/tutorial or reading documentation?

No, running standard garak scan with all probes.

## Expected behavior

The atkgen.Tox probe should execute successfully and generate adversarial prompts to test toxicity detection.

## Current behavior

The probe crashes with the following error:

```
Traceback (most recent call last):
  File "garak/probes/atkgen.py", line 208, in probe
    f"atkgen: 🦜 model: {Style.BRIGHT}{this_attempt.prompt.turns[-1].text}{Style.RESET_ALL}"
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'Turn' object has no attribute 'text'
```

### Root Cause

In `garak/probes/atkgen.py` line 208, the code tries to access `.text` directly on a `Turn` object. However, the Turn object structure has changed - it now has a `.content` attribute (which is a Message object), and that Message object contains the `.text` attribute.

**Current (broken) code:**
```python
this_attempt.prompt.turns[-1].text
```

**Should be:**
```python
this_attempt.prompt.turns[-1].content.text
```

### garak version

v0.13.2.pre1 (commit: 44307028)

## Additional Information

1. **Operating system**: macOS (Darwin 24.6.0)
2. **Python version**: 3.12
3. **Install method**: pip based repo install (editable mode: `pip install -e .`)
4. **Logs**: Full traceback provided above
5. **Details of execution config**:
   - Command: `garak --target_type openai_rated --target_name gpt-3.5-turbo-instruct --probes all --generations 100 -vv`
   - The error occurs when the atkgen.Tox probe starts executing
6. **Relevant hardware**: MacBook

## Impact

This bug prevents the entire atkgen probe family from running, which includes:
- `atkgen.Tox`
- Potentially other atkgen probes that use similar logging code

## Workaround

Skip atkgen probes until fixed:
```bash
garak --target_type openai --target_name gpt-3.5-turbo --probes dan,continuation,lmrc
```
