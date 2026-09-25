#!/usr/bin/env python3
"""Estimate token counts for files and text."""
import sys
import argparse

def estimate_tokens(text):
    """Rough token estimation: ~4 chars per token."""
    return len(text) // 4

def format_number(n):
    return f"{n:,}"

def main():
    parser = argparse.ArgumentParser(description='Estimate token counts')
    parser.add_argument('file', nargs='?', help='File to analyze')
    parser.add_argument('--text', '-t', help='Text to analyze')
    parser.add_argument('--max', '-m', type=int, default=0, 
                        help='Only analyze first N lines')
    args = parser.parse_args()
    
    if args.text:
        content = args.text
        source = "text argument"
    elif args.file:
        try:
            with open(args.file, 'r', encoding='utf-8', errors='replace') as f:
                if args.max:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= args.max:
                            break
                        lines.append(line)
                    content = ''.join(lines)
                    source = f"{args.file} (first {args.max} lines)"
                else:
                    content = f.read()
                    source = args.file
        except Exception as e:
            print(f"Error reading {args.file}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Read from stdin
        content = sys.stdin.read()
        source = "stdin"
    
    chars = len(content)
    tokens = estimate_tokens(content)
    lines = content.count('\n')
    pct = (tokens / 26000) * 100
    
    print(f"Source: {source}")
    print(f"Lines: {format_number(lines)}")
    print(f"Characters: {format_number(chars)}")
    print(f"Estimated tokens: {format_number(tokens)}")
    print(f"Context usage: {pct:.1f}% of 26k")
    
    if tokens > 20000:
        print("⚠️  WARNING: Very large, will likely trigger compaction")
    elif tokens > 10000:
        print("⚠️  Large file, consider using a subagent")
    elif tokens > 5000:
        print("ℹ️  Medium size, read selectively")
    else:
        print("✓ Safe size for direct reading")

if __name__ == "__main__":
    main()
