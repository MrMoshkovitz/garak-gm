# Garak Probe Filtering Process

This document describes the process for filtering and running garak probes, specifically excluding the `atkgen` probe family.

## Overview

The probe filtering process consists of four main steps:
1. List all available probes
2. Create a comma-separated list of all probes
3. Filter out atkgen probes
4. Run garak with the filtered probe list

## Prerequisites

- Garak installed and configured
- OpenAI API key set as environment variable
- Target generator configured (e.g., `openai_rated`)

## Automated Script

Use the provided script for automated execution:

```bash
./run_garak_without_atkgen.sh [target_name]
```

**Parameters:**
- `target_name` (optional): OpenAI model name (default: `gpt-3.5-turbo`)

**Example:**
```bash
./run_garak_without_atkgen.sh gpt-4
```

## Manual Steps

If you need to run the process manually, follow these steps:

### Step 1: List All Available Probes

Generate a complete list of all garak probes:

```bash
garak --list_probes > all_probes.txt
```

**Output:** `all_probes.txt`
- Contains formatted output with ANSI color codes
- Includes probe categories (e.g., `probes: ansiescape 🌟`)
- Includes individual probes (e.g., `probes: ansiescape.AnsiEscaped`)

### Step 2: Create Comma-Separated List of All Probes

Extract probe names and create a comma-separated list:

```bash
sed 's/\x1b\[[0-9;]*m//g' all_probes.txt | \
  awk '/^probes: / && /\./ {print $2}' | \
  tr '\n' ',' | \
  sed 's/,$//' > all_probes_comma_separated.txt
```

**What this does:**
- `sed 's/\x1b\[[0-9;]*m//g'` - Removes ANSI escape codes
- `awk '/^probes: / && /\./ {print $2}'` - Extracts probe names (lines with dots only)
- `tr '\n' ','` - Converts newlines to commas
- `sed 's/,$//'` - Removes trailing comma

**Output:** `all_probes_comma_separated.txt`
- Single line with all probe names separated by commas
- Example: `ansiescape.AnsiEscaped,ansiescape.AnsiRaw,atkgen.Tox,...`

### Step 3: Filter Out Atkgen Probes

Create a filtered list excluding atkgen probes:

```bash
sed 's/\x1b\[[0-9;]*m//g' all_probes.txt | \
  awk '/^probes: / && /\./ {print $2}' | \
  grep -v "atkgen" | \
  tr '\n' ',' | \
  sed 's/,$//' > probes_without_atkgen.txt
```

**What this does:**
- Same as Step 2, but adds `grep -v "atkgen"` to exclude atkgen probes
- Filters out any probe containing "atkgen" in its name

**Output:** `probes_without_atkgen.txt`
- Single line with all probe names except atkgen
- Example: `ansiescape.AnsiEscaped,ansiescape.AnsiRaw,audio.AudioAchillesHeel,...`

### Step 4: Run Garak with Filtered Probes

Execute garak using the filtered probe list:

```bash
PROBES_WITHOUT_ATKGEN=$(cat probes_without_atkgen.txt)
garak --target_type openai_rated --target_name gpt-3.5-turbo --probes $PROBES_WITHOUT_ATKGEN -vv
```

**Parameters:**
- `--target_type openai_rated` - Use the rate-limited OpenAI generator wrapper
- `--target_name gpt-3.5-turbo` - Target model (can be changed to gpt-4, etc.)
- `--probes $PROBES_WITHOUT_ATKGEN` - Comma-separated list from filtered file
- `-vv` - Verbose output (shows rate limit monitoring logs)

## Why Filter Out Atkgen?

The `atkgen` probe family uses conversational attacks that may:
- Generate highly toxic prompts during testing
- Require longer execution time due to multi-turn conversations
- Have specific implementation requirements (e.g., the Turn.content.text bug fix)

For standard vulnerability scanning without conversational attack generation, filtering out atkgen provides:
- Faster execution
- Reduced exposure to toxic content in logs
- Simpler output analysis

## File Descriptions

| File | Description |
|------|-------------|
| `run_garak_without_atkgen.sh` | Automated script for the entire process |
| `all_probes.txt` | Raw output from `garak --list_probes` |
| `all_probes_comma_separated.txt` | All probe names in comma-separated format |
| `probes_without_atkgen.txt` | Filtered probe names (no atkgen) in comma-separated format |
| `PROBE_FILTERING_STEPS.md` | This documentation file |

## Troubleshooting

### Issue: Empty Output Files

**Problem:** `all_probes_comma_separated.txt` or `probes_without_atkgen.txt` are empty

**Solution:** Check that you're using the correct `awk` pattern:
- Must include `/\./ ` to filter only probe names (with dots)
- Must remove ANSI codes before parsing

### Issue: "Unknown probes" Error

**Problem:** Garak reports unknown probes when running

**Causes:**
- Header lines included in probe list (e.g., "garak", "probes:")
- ANSI codes not stripped properly
- Wrong field extracted from probe list

**Solution:** Ensure you're using the exact commands from Step 2 and Step 3

### Issue: Rate Limit Errors

**Problem:** Getting 429 rate limit errors during scan

**Solution:** The `openai_rated` generator should handle this automatically:
- Monitors rate limit headers
- Pauses at 95% usage
- Check logs for rate limit status messages

## Rate Limit Monitoring

When using `--target_type openai_rated` with `-vv` verbosity, you'll see rate limit monitoring:

```
INFO Rate limits - requests: 45/50 (90.0%, resets in 12s) | tokens: 8500/10000 (85.0%, resets in 8s)
```

The wrapper will automatically pause when any limit reaches 95% usage.

## Additional Resources

- Garak documentation: https://github.com/NVIDIA/garak
- OpenAI rate limits: See `OpenAIRates.md`
- Rate limit wrapper implementation: `garak/generators/openai_rated.py`
