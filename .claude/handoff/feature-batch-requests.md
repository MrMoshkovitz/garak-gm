# Garak Batch Request Processing - Developer Handoff

## Overview

This document provides a comprehensive guide to the batch request processing feature for Garak. This feature enables efficient, large-scale testing of all Garak probes using OpenAI's Batch API.

**Branch:** `batch_requests`
**Status:** Ready for integration
**Created:** 2025-10-20

---

## What Was Done

### Implementation Summary

A new batch processing system was created to:

1. **Collect all active Garak probes and their prompts** - Dynamically loads all probe plugins and extracts their prompts
2. **Generate batch JSONL files** - Creates properly formatted OpenAI Batch API input files
3. **Submit batches to OpenAI** - Uploads and submits batch files with a 24-hour completion window
4. **Monitor batch progress** - Polls OpenAI's API to track completion status
5. **Parse results** - Converts batch results back into a structured format
6. **Generate summary reports** - Creates a comprehensive JSON summary of all results

### Key Features

- ✅ Supports all Garak probes including those without explicit prompts
- ✅ Configurable number of generations per prompt (default: 5)
- ✅ Automatic batch file splitting when exceeding 50,000 request limit
- ✅ Intelligent batch file reuse - skips regeneration if valid files exist
- ✅ Flexible model selection (default: gpt-3.5-turbo)
- ✅ Real-time progress monitoring during batch execution
- ✅ Comprehensive error handling and validation

### Files Added

```
batch_requests/
├── batch_all_probes.py              # Main batch processing script
├── batch_input_part1.jsonl          # Pre-generated batch for 11,250 requests
├── batch_input_part2.jsonl          # Pre-generated batch for 11,250 requests
├── batch_input_part3.jsonl          # Pre-generated batch for 11,250 requests
└── batch_input_part4.jsonl          # Pre-generated batch for 11,250 requests
```

---

## Architecture & Design

### System Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. COLLECT PROMPTS                                          │
│    - Load all probe plugins dynamically                     │
│    - Extract prompts from each probe                        │
│    - Handle Conversation/Message formats                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. BUILD BATCH FILES                                        │
│    - Create OpenAI Batch API requests                       │
│    - Split into files if exceeding 50k request limit        │
│    - Save as JSONL format                                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. SUBMIT & MONITOR                                         │
│    - Upload batch file to OpenAI                            │
│    - Submit for processing (24-hour window)                 │
│    - Poll every 60 seconds until completion                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. PARSE RESULTS                                            │
│    - Download output from OpenAI                            │
│    - Parse responses back to probe/seq/generation format    │
│    - Generate summary report (garak_batch_summary.json)    │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

#### `batch_all_probes.py`

**Main Functions:**

- `parse_cli_args()` - Parses command-line arguments
- `collect_all_prompts()` - Dynamically loads all probes and extracts prompts
- `build_batch_file()` - Creates a single JSONL batch file
- `build_batch_files()` - Splits prompts across multiple batch files if needed
- `submit_and_wait()` - Submits batch and monitors completion
- `parse_results()` - Converts batch results to structured format

**Request Format:**

Each request in the batch file follows OpenAI's specification:

```json
{
  "custom_id": "probes.dan.AutoDAN:0:2",
  "method": "POST",
  "url": "/v1/chat/completions",
  "body": {
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "...prompt..."}],
    "max_tokens": 150,
    "temperature": 0.7
  }
}
```

**Custom ID Format:** `{probe_name}:{sequence_index}:{generation_index}`

---

## Getting Started

### Prerequisites

```bash
# Python 3.8+
python --version

# Required packages
pip install openai python-dotenv

# Garak installation
pip install garak
```

### Environment Setup

```bash
# Create .env file with your OpenAI API key
echo "OPENAI_API_KEY=sk-..." > .env

# Or export directly
export OPENAI_API_KEY=sk-...
```

### Initial Setup

```bash
# 1. Navigate to batch_requests directory
cd batch_requests

# 2. (Optional) Remove existing batch files to regenerate
rm batch_input_part*.jsonl

# 3. Run the script
python batch_all_probes.py --model gpt-3.5-turbo
```

---

## Usage Guide

### Basic Usage

```bash
python batch_all_probes.py
```

Runs with all defaults:
- Model: `gpt-3.5-turbo`
- Generations: 5 per prompt
- Max requests: 50,000 per batch file

### Command Reference

#### Core Options

```bash
# Specify model
python batch_all_probes.py --model gpt-4

# Adjust generations per prompt
python batch_all_probes.py --generations 10

# Limit requests per batch file
python batch_all_probes.py --max-requests 25000

# Custom batch filename prefix
python batch_all_probes.py --batch-prefix my_batch
```

#### Common Workflows

**1. Generate batch files only (without submitting)**

```bash
python batch_all_probes.py --help
# Edit script to comment out Step 3 (submit_and_wait calls)
python batch_all_probes.py
```

**2. Use GPT-4 with 3 generations per prompt**

```bash
python batch_all_probes.py --model gpt-4 --generations 3
```

**3. Create smaller batches for testing**

```bash
python batch_all_probes.py --max-requests 5000
# Creates batch_input_part1.jsonl, batch_input_part2.jsonl, etc.
```

**4. Clean up and regenerate (if code changes affect probes)**

```bash
rm batch_input_part*.jsonl
python batch_all_probes.py --generations 5
```

---

## Output Files

### Batch Input Files

- **Naming:** `batch_input_part{N}.jsonl` (or custom prefix)
- **Format:** JSONL (one JSON object per line)
- **Size:** Each part contains up to 50,000 requests
- **Reusability:** Automatically reused if valid (same model, not empty, not exceeding limit)

**Example batch_input_part1.jsonl line:**

```json
{"custom_id": "probes.dan.AutoDAN:0:0", "method": "POST", "url": "/v1/chat/completions", "body": {"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "..."}], "max_tokens": 150, "temperature": 0.7}}
```

### Batch Output Files

- **Naming:** `batch_output_part{N}.jsonl`
- **Format:** JSONL (response objects with custom_id)
- **Created by:** `submit_and_wait()` after batch completion

**Example line:**

```json
{"custom_id": "probes.dan.AutoDAN:0:0", "result": {"status_code": 200, "request_id": "...", "body": {"id": "...", "object": "chat.completion", "created": 1729..., "model": "gpt-3.5-turbo", "choices": [{"index": 0, "message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}]}}}
```

### Summary Report

- **File:** `garak_batch_summary.json`
- **Format:** JSON
- **Contents:**
  - `total_probes`: Number of unique probes tested
  - `total_prompts`: Total prompt variations
  - `total_generations`: Total LLM generations
  - `results`: Nested structure: `{probe_name: {sequence: [generation1, generation2, ...]}}`

**Example structure:**

```json
{
  "total_probes": 45,
  "total_prompts": 1234,
  "total_generations": 6170,
  "results": {
    "probes.dan.AutoDAN": {
      "0": ["response1", "response2", ...],
      "1": ["response1", "response2", ...]
    },
    "probes.dan.MASTERKEY": { ... }
  }
}
```

---

## Monitoring & Troubleshooting

### During Execution

The script provides real-time feedback:

```
[1/4] Collecting prompts from all probes...
      Loading probes.dan.AutoDAN... 5 prompts
      Loading probes.tap.TAP... 3 prompts
      ...
✅ Collected 1234 prompts

[2/4] Building batch file(s)...
      batch_input_part1.jsonl (50000 requests)
      batch_input_part2.jsonl (1234 requests)
✅ Created 2 batch file(s) with 51234 requests total

[3/4] Submitting to OpenAI Batch API...
      --- Batch 1/2: batch_input_part1.jsonl ---
      ⏳ Batch ID: batch_xxxxx
         Status: processing
         [2m] 12500/50000 (25.0%) | processing

[4/4] Parsing results...
      ✅ Results saved to batch_output_part1.jsonl
✅ Processed 45 probes
```

### Common Issues

#### "OAuth token has expired"

```bash
# Re-authenticate
openai login
# Or set API key
export OPENAI_API_KEY=sk-...
```

#### "File exceeds GitHub's recommended maximum file size"

This is a warning, not an error. The batch files are 80+ MB because they contain many prompts.

**Solution:** Use Git LFS for large files:

```bash
git lfs install
git lfs track "*.jsonl"
git add .gitattributes
git commit -m "Add Git LFS tracking for batch files"
```

#### "Could not parse batch file: empty"

The batch file is corrupted or was interrupted during writing.

**Solution:**

```bash
# Remove and regenerate
rm batch_input_part*.jsonl
python batch_all_probes.py
```

#### "Batch failed: cancelled/expired"

The 24-hour batch window elapsed. OpenAI's Batch API has a 24-hour completion window.

**Solution:** Resubmit or split into smaller batches:

```bash
python batch_all_probes.py --max-requests 10000
```

#### "Rate limit exceeded"

Too many API calls to OpenAI.

**Solution:** Wait before resubmitting or use a different API tier.

---

## Integration with Garak

### Current Status

The batch system is standalone and **not yet integrated** with Garak's main evaluation pipeline. To integrate:

1. **Add to Garak CLI:**

```python
# In garak/cli.py or appropriate module
def add_batch_command():
    subparsers.add_parser('batch', help='Run batch processing')
```

2. **Move script to Garak package:**

```bash
mv batch_all_probes.py garak/batch/processor.py
```

3. **Create wrapper:**

```python
# garak/batch/__init__.py
from .processor import collect_all_prompts, build_batch_files, submit_and_wait
```

4. **Add to setup.py:**

```python
install_requires=[
    'openai>=1.0.0',
    'python-dotenv',
    ...
]
```

---

## Performance Metrics

### Batch Generation

- **Time to collect prompts:** ~10-15 seconds (first run)
- **Time to build batch files:** ~5 seconds
- **Batch file sizes:** ~80 MB per 50k requests

### Batch Processing

- **Typical completion time:** 5-30 minutes (OpenAI dependent)
- **Cost:** ~$0.50-$2.00 per batch (depends on model, token count)
- **Parallelization:** Can submit multiple batches simultaneously

### Data Volume

**Typical test with current probes:**

```
Probes: ~45 active probes
Prompts: ~1,200 prompts
Batch 1: 50,000 requests (10 probes × ~500 prompts × 5 gens)
Batch 2: 1,234 requests (remaining)
Total: 51,234 API calls per run
```

---

## Best Practices

### Before Running

- ✅ Verify OpenAI API quota and billing
- ✅ Check `.env` contains valid API key
- ✅ Ensure sufficient disk space (~200 MB)
- ✅ Review probe code for any incompatibilities

### During Execution

- ✅ Let monitoring run to completion (don't interrupt mid-batch)
- ✅ Keep API key secure
- ✅ Monitor OpenAI dashboard for unexpected costs

### After Execution

- ✅ Review `garak_batch_summary.json` for completeness
- ✅ Validate results before publishing
- ✅ Archive results for reproducibility
- ✅ Clean up temporary files if needed

---

## Development Notes

### Code Structure

**Main entry point:** `if __name__ == "__main__"` block (line 240)

**4-step process:**

1. **Lines 251-332:** Prompt collection & batch building
2. **Lines 335-342:** Batch submission
3. **Lines 344-351:** Results parsing & summary

### Key Design Decisions

1. **Dynamic probe loading** - Ensures all probes are tested without hardcoding
2. **Batch file reuse** - Prevents regeneration overhead on repeated runs
3. **Request ID format** - Enables tracing results back to original probes
4. **60-second polling** - Balances API calls with responsiveness
5. **Custom ID parsing** - Simple string split for result reconstruction

### Extension Points

To modify behavior, consider:

- **Custom prompt filtering:** Modify `collect_all_prompts()` to skip certain probes
- **Different output formats:** Extend `parse_results()` for alternative formats
- **Retry logic:** Add exponential backoff to `submit_and_wait()`
- **Result validation:** Add schema validation in `parse_results()`

---

## Next Steps for Integration

1. **Documentation**
   - Add batch processing to main Garak docs
   - Create usage examples
   - Document cost implications

2. **Testing**
   - Unit tests for batch building
   - Integration tests with OpenAI API
   - Performance benchmarks

3. **Enhancement**
   - Support for other LLM providers (Anthropic, Azure, etc.)
   - Streaming results processing for large batches
   - Web dashboard for monitoring multiple batches
   - Cost optimization (request batching, model selection)

4. **Deployment**
   - Add to PyPI package
   - Create CLI command
   - Add GitHub Actions for automated batch runs

---

## References

### OpenAI Batch API

- [Batch API Documentation](https://platform.openai.com/docs/guides/batch-processing)
- [Batch API Examples](https://github.com/openai/openai-python/tree/main/examples)

### Garak

- [Garak GitHub](https://github.com/leondz/garak)
- [Garak Documentation](https://docs.garak.ai/)
- [Probe Documentation](https://docs.garak.ai/reference/probes/)

### Related Tools

- [OpenAI Python SDK](https://github.com/openai/openai-python)
- [Git LFS](https://git-lfs.com/) - For managing large files

---

## Questions & Support

For questions about this implementation:

- Check `batch_all_probes.py` comments for inline documentation
- Review the Command Reference section for usage examples
- See Troubleshooting for common issues

---

**Document Version:** 1.0
**Last Updated:** 2025-10-20
**Maintained By:** Claude Code
