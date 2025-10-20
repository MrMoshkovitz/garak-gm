#!/usr/bin/env python3
"""
Standalone script to batch all Garak probes × prompts × 5 generations
Usage: python batch_all_probes.py --model gpt-3.5-turbo

No Prompts:
=============
1. probes.atkgen.Tox
2. probes.dan.AutoDAN
3. probes.fileformats.HF_Files
4. probes.suffix.GCG
5. probes.suffix.GCGCached
6. probes.tap.PAIR
7. probes.tap.TAP
8. Loading probes.topic.WordnetAllowedWords

"""
import argparse
import json
import time
import sys
from pathlib import Path
import openai
from dotenv import load_dotenv

# Import Garak components
from garak import _config, _plugins
from garak._plugins import enumerate_plugins

load_dotenv()

MAX_REQUESTS_PER_BATCH = 50_000
DEFAULT_BATCH_PREFIX = "batch_input"

def parse_cli_args():
    parser = argparse.ArgumentParser(
        description="Batch all Garak probes × prompts × N generations via OpenAI Batch API."
    )
    parser.add_argument(
        "--model",
        default="gpt-3.5-turbo",
        help="Model name to use for chat completions (default: gpt-3.5-turbo).",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=5,
        help="Number of generations per prompt (default: 5).",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=MAX_REQUESTS_PER_BATCH,
        help=f"Maximum requests per batch file (default: {MAX_REQUESTS_PER_BATCH}).",
    )
    parser.add_argument(
        "--batch-prefix",
        default=DEFAULT_BATCH_PREFIX,
        help=f"Filename prefix for batch input files (default: {DEFAULT_BATCH_PREFIX}).",
    )
    return parser.parse_args()

def collect_all_prompts():
    """Extract all prompts from all active probes"""
    all_prompts = []
    
    for probe_name, _ in enumerate_plugins("probes"):
        try:
            print(f"Loading {probe_name}...", end=" ")
            probe = _plugins.load_plugin(probe_name)
            
            # Skip if no prompts or inactive
            if not hasattr(probe, 'prompts') or not probe.prompts:
                print("no prompts")
                continue
            
            for seq, prompt in enumerate(probe.prompts):
                # Convert Conversation to messages
                if hasattr(prompt, 'turns'):
                    messages = [{"role": t.role, "content": t.content.text} 
                               for t in prompt.turns]
                elif hasattr(prompt, 'text'):
                    messages = [{"role": "user", "content": prompt.text}]
                else:
                    messages = [{"role": "user", "content": str(prompt)}]
                
                all_prompts.append({
                    "probe": probe_name,
                    "seq": seq,
                    "messages": messages,
                    "triggers": getattr(probe, 'triggers', [None])[seq] if hasattr(probe, 'triggers') else None
                })
            
            print(f"{len(probe.prompts)} prompts")
            
        except Exception as e:
            print(f"SKIP: {e}")
            continue
    
    print(f"======================\nALL PROMPTS\n====================\n")
    # print(all_prompts)
    return all_prompts

def build_batch_file(prompts, model_name, generations=5, output_file="batch_input.jsonl"):
    """Generate OpenAI batch JSONL"""
    requests = []
    
    for prompt_data in prompts:
        for gen_idx in range(generations):
            req_id = f"{prompt_data['probe']}:{prompt_data['seq']}:{gen_idx}"
            requests.append({
                "custom_id": req_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model_name,
                    "messages": prompt_data["messages"],
                    "max_tokens": 150,
                    "temperature": 0.7,
                }
            })
    
    with open(output_file, "w") as f:
        for req in requests:
            f.write(json.dumps(req) + "\n")
            # print(f"\n====REQUEST\n====")
            # print(json.dumps(req) + "\n")
    
    requests_count = len(requests)
    print(f"\n=====\nLen Requests: {requests_count}")
    return requests_count, output_file

def build_batch_files(prompts, model_name, generations=5, output_prefix=DEFAULT_BATCH_PREFIX, max_requests_per_batch=MAX_REQUESTS_PER_BATCH):
    """Split prompts across multiple batch files to respect request limits"""
    if not prompts:
        return []

    requests_per_prompt = max(generations, 1)
    max_prompts_per_batch = max_requests_per_batch // requests_per_prompt
    if max_prompts_per_batch == 0:
        max_prompts_per_batch = 1

    if len(prompts) <= max_prompts_per_batch:
        count, path = build_batch_file(prompts, model_name, generations, f"{output_prefix}.jsonl")
        return [(count, path)]

    batches = []
    for idx, start in enumerate(range(0, len(prompts), max_prompts_per_batch), start=1):
        chunk = prompts[start:start + max_prompts_per_batch]
        filename = f"{output_prefix}_part{idx}.jsonl"
        count, path = build_batch_file(chunk, model_name, generations, filename)
        batches.append((count, path))
    
    return batches

def submit_and_wait(batch_file, output_file=None):
    """Submit batch and wait for completion"""
    client = openai.OpenAI()
    
    # Upload
    print("📤 Uploading batch file...")
    with open(batch_file, "rb") as f:
        uploaded_file = client.files.create(file=f, purpose="batch")
    
    # Submit
    print("🚀 Submitting batch...")
    batch = client.batches.create(
        input_file_id=uploaded_file.id,
        endpoint="/v1/chat/completions",
        completion_window="24h"
    )
    
    print(f"⏳ Batch ID: {batch.id}")
    print(f"   Status: {batch.status}")
    print(f"   Waiting (checks every 60s)...\n")
    
    # Poll
    start_time = time.time()
    while batch.status not in ["completed", "failed", "cancelled"]:
        time.sleep(60)
        batch = client.batches.retrieve(batch.id)
        elapsed = int(time.time() - start_time)
        completed = batch.request_counts.completed
        total = batch.request_counts.total
        percent = (completed / total * 100) if total > 0 else 0
        print(f"   [{elapsed//60}m] {completed}/{total} ({percent:.1f}%) | {batch.status}")
    
    if batch.status != "completed":
        print(f"❌ Batch failed: {batch.status}")
        return None
    
    # Download
    print("\n📥 Downloading results...")
    result_file = client.files.content(batch.output_file_id)
    batch_path = Path(batch_file)
    if output_file:
        output_path = Path(output_file)
    else:
        stem = batch_path.stem.replace("input", "output") if "input" in batch_path.stem else f"{batch_path.stem}_output"
        output_path = batch_path.with_name(f"{stem}.jsonl")
    with open(output_path, "wb") as f:
        f.write(result_file.read())
    
    print(f"✅ Results saved to {output_path}")
    return str(output_path)

def parse_results(result_files):
    """Convert batch results to Garak report format"""
    results = {}
    
    if isinstance(result_files, (str, Path)):
        result_files = [result_files]

    for result_file in result_files:
        with open(result_file) as f:
            for line in f:
                res = json.loads(line)
                probe, seq, gen = res["custom_id"].split(":")
                
                if probe not in results:
                    results[probe] = {}
                if seq not in results[probe]:
                    results[probe][seq] = []
                
                content = res["response"]["body"]["choices"][0]["message"]["content"]
                results[probe][seq].append(content)
    
    # Write summary
    with open("garak_batch_summary.json", "w") as f:
        json.dump({
            "total_probes": len(results),
            "total_prompts": sum(len(seqs) for seqs in results.values()),
            "total_generations": sum(len(gens) for seqs in results.values() for gens in seqs.values()),
            "results": results
        }, f, indent=2)
    
    print(f"📊 Summary written to garak_batch_summary.json")
    return results

if __name__ == "__main__":
    args = parse_cli_args()
    model = args.model
    generations = max(args.generations, 1)
    max_requests = max(args.max_requests, 1)
    batch_prefix = args.batch_prefix or DEFAULT_BATCH_PREFIX
    
    print("=" * 70)
    print(f"GARAK BATCH EXECUTOR - All Probes × All Prompts × {generations} Generations")
    print("=" * 70)
    
    existing_batch_files = sorted(Path(".").glob(f"{batch_prefix}*.jsonl"))
    batch_files = []
    should_cleanup_existing = False

    if existing_batch_files:
        reusable_files = []
        needs_rebuild = False
        for file_path in existing_batch_files:
            try:
                with open(file_path) as f:
                    try:
                        first_line = next(f)
                    except StopIteration:
                        print(f"\n[1/4] {file_path.name} is empty. Rebuilding batches.")
                        needs_rebuild = True
                        should_cleanup_existing = True
                        break
                    try:
                        first_req = json.loads(first_line)
                    except json.JSONDecodeError as exc:
                        print(f"\n[1/4] Could not parse {file_path.name}: {exc}. Rebuilding batches.")
                        needs_rebuild = True
                        should_cleanup_existing = True
                        break
                    file_model = first_req.get("body", {}).get("model")
                    file_model_display = file_model if file_model else "<unknown>"
                    if file_model != model:
                        print(f"\n[1/4] Existing {file_path.name} targets model '{file_model_display}', expected '{model}'. Rebuilding batches.")
                        needs_rebuild = True
                        should_cleanup_existing = True
                        break
                    line_count = 1 + sum(1 for _ in f)
            except OSError as exc:
                print(f"\n[1/4] Could not inspect {file_path}: {exc}. Rebuilding batches.")
                needs_rebuild = True
                should_cleanup_existing = True
                break
            if line_count > max_requests:
                print(f"\n[1/4] Existing {file_path.name} exceeds {max_requests} requests ({line_count}). Rebuilding batches.")
                needs_rebuild = True
                should_cleanup_existing = True
                break
            reusable_files.append(str(file_path))

        if not needs_rebuild and reusable_files:
            print(f"\n[1/4] Found {len(reusable_files)} existing batch file(s), skipping prompt collection.")
            for idx, fname in enumerate(reusable_files, start=1):
                print(f"    [{idx}] {fname}")
            print(f"[2/4] Reusing existing batch file(s)\n")
            batch_files = reusable_files

    if not batch_files:
        if existing_batch_files and should_cleanup_existing:
            for stale_file in existing_batch_files:
                try:
                    stale_file.unlink()
                except OSError as exc:
                    print(f"Warning: could not remove {stale_file}: {exc}")

        print("\n[1/4] Collecting prompts from all probes...")
        prompts = collect_all_prompts()
        print(f"✅ Collected {len(prompts)} prompts\n")

        print("[2/4] Building batch file(s)...")
        batch_info = build_batch_files(
            prompts,
            model,
            generations=generations,
            output_prefix=batch_prefix,
            max_requests_per_batch=max_requests,
        )

        if not batch_info:
            print("No prompts collected; exiting.")
            sys.exit(0)

        total_requests = sum(count for count, _ in batch_info)
        print(f"✅ Created {len(batch_info)} batch file(s) with {total_requests} requests total")
        for idx, (count, batch_path) in enumerate(batch_info, start=1):
            print(f"    [{idx}] {batch_path} ({count} requests)")

        batch_files = [path for _, path in batch_info]
        print()
    
    # Step 3: Submit
    print("[3/4] Submitting to OpenAI Batch API...")
    result_files = []
    for idx, batch_file in enumerate(batch_files, start=1):
        print(f"\n--- Batch {idx}/{len(batch_files)}: {batch_file} ---")
        result_file = submit_and_wait(batch_file)
        if result_file:
            result_files.append(result_file)

    if result_files:
        # Step 4: Parse
        print("\n[4/4] Parsing results...")
        results = parse_results(result_files)
        print(f"✅ Processed {len(results)} probes")
        print("\nDone! Check garak_batch_summary.json for results.")
    else:
        print("\n❌ Batch failed. Check OpenAI dashboard.")
