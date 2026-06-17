#!/bin/bash
# Fix duplicate fetchStability in index.html
# Strategy: find line numbers of all fetchStability defs, delete the first block

cd /home/mrg/dev/games/Forge/hub/static

# Find all lines containing "async function fetchStability"
lines=$(grep -n 'async function fetchStability' index.html | cut -d: -f1)
echo "fetchStability definitions at lines: $lines"

# Find the comment line right before the first definition
first=$(echo "$lines" | head -1)
# Find the comment that precedes it (should be ~2 lines before)
comment_start=$((first - 2))
# Find the closing brace of the first function
# The function body is about 25 lines, ending with a line containing just "}"
first_end=$(sed -n "${first},\$p" index.html | grep -n '^}$' | head -1 | cut -d: -f1)
first_end=$((first + first_end - 1))

echo "Will delete lines $comment_start to $first_end"
sed -i "${comment_start},${first_end}d" index.html
echo "Done. Remaining definitions:"
grep -n 'async function fetchStability' index.html
