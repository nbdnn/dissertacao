#!/bin/bash

# Configuration file containing satellite IDs (one per line)
CONFIG_FILE="satellites_list.txt"

# Path to python scripts
SCREENING_SCRIPT="app/conjunctions/screening.py"
ANALYSIS_SCRIPT="cenario1/conjunctions_pipeline.py"

# Default simulation days
DAYS=7.0

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file '$CONFIG_FILE' not found."
    exit 1
fi

echo "Starting Conjunction Analysis Campaign..."
echo "Reading IDs from: $CONFIG_FILE"
echo "----------------------------------------"

# Read file line by line
while IFS= read -r SAT_ID || [ -n "$SAT_ID" ]; do
    # Skip empty lines or comments
    [[ -z "$SAT_ID" ]] && continue
    [[ "$SAT_ID" =~ ^#.*$ ]] && continue
    
    # Trim whitespace
    SAT_ID=$(echo "$SAT_ID" | xargs)

    echo "Processing Base ID: $SAT_ID"

    # 1. Run Screening
    # Note: We use 'uv run' to manage python environment/dependencies if needed.
    echo "  > Running screening..."
    uv run "$SCREENING_SCRIPT" --base "$SAT_ID" --days "$DAYS"
    
    if [ $? -ne 0 ]; then
        echo "  ❌ Screening failed for ID $SAT_ID. Skipping analysis."
        continue
    fi

    # 2. Run Analysis Pipeline
    echo "  > Running analysis pipeline..."
    uv run "$ANALYSIS_SCRIPT" --base "$SAT_ID" --days "$DAYS"

    if [ $? -eq 0 ]; then
        echo "  ✅ Completed for ID $SAT_ID"
    else
        echo "  ❌ Analysis failed for ID $SAT_ID"
    fi

    echo "----------------------------------------"

done < "$CONFIG_FILE"

echo "Campaign Finished."
