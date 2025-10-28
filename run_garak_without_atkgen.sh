#!/bin/bash
#
# run_garak_without_atkgen.sh
#
# This script automates the process of:
# 1. Listing all available garak probes
# 2. Creating comma-separated lists of probes
# 3. Filtering out atkgen probes
# 4. Running garak with the filtered probe list
#
# Usage: ./run_garak_without_atkgen.sh [target_name]
#   target_name: Optional OpenAI model name (default: gpt-3.5-turbo)
#

set -e  # Exit on error

# Configuration
TARGET_TYPE="openai_rated"
TARGET_NAME="${1:-gpt-3.5-turbo}"
VERBOSITY="-vv"

echo "=========================================="
echo "Garak Probe Filter & Run Script"
echo "=========================================="
echo ""

# Step 1: List all available probes
echo "Step 1: Listing all available probes..."
garak --list_probes > all_probes.txt
echo "✓ Saved to all_probes.txt"
echo ""

# Step 2: Create comma-separated list of all probes
echo "Step 2: Creating comma-separated list of all probes..."
sed 's/\x1b\[[0-9;]*m//g' all_probes.txt | \
  awk '/^probes: / && /\./ {print $2}' | \
  tr '\n' ',' | \
  sed 's/,$//' > all_probes_comma_separated.txt
echo "✓ Saved to all_probes_comma_separated.txt"
echo ""

# Step 3: Generate comma-separated list excluding atkgen
echo "Step 3: Filtering out atkgen probes..."
sed 's/\x1b\[[0-9;]*m//g' all_probes.txt | \
  awk '/^probes: / && /\./ {print $2}' | \
  grep -v "atkgen" | \
  tr '\n' ',' | \
  sed 's/,$//' > probes_without_atkgen.txt
echo "✓ Saved to probes_without_atkgen.txt"
echo ""

# Count probes
TOTAL_PROBES=$(sed 's/\x1b\[[0-9;]*m//g' all_probes.txt | awk '/^probes: / && /\./ {print $2}' | wc -l | tr -d ' ')
FILTERED_PROBES=$(sed 's/\x1b\[[0-9;]*m//g' all_probes.txt | awk '/^probes: / && /\./ {print $2}' | grep -v "atkgen" | wc -l | tr -d ' ')
EXCLUDED_PROBES=$((TOTAL_PROBES - FILTERED_PROBES))

echo "Summary:"
echo "  Total probes: $TOTAL_PROBES"
echo "  Excluded (atkgen): $EXCLUDED_PROBES"
echo "  Running with: $FILTERED_PROBES probes"
echo ""

# Step 4: Run garak with filtered probes
echo "Step 4: Running garak with filtered probes..."
echo "  Target Type: $TARGET_TYPE"
echo "  Target Name: $TARGET_NAME"
echo "  Verbosity: $VERBOSITY"
echo ""
echo "=========================================="
echo ""

PROBES_WITHOUT_ATKGEN=$(cat probes_without_atkgen.txt)
garak --target_type "$TARGET_TYPE" --target_name "$TARGET_NAME" --probes "$PROBES_WITHOUT_ATKGEN" $VERBOSITY
