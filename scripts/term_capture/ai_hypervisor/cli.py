#!/usr/bin/env python3
"""
AI Hypervisor CLI - Entry point for the hypervisor system.

Usage:
    ai-hv run claude                    # Run Claude with full monitoring
    ai-hv run --tool aider -- /path     # Run Aider on specific path
    ai-hv status                        # Show current session stats
    ai-hv logs                          # Show recent session logs
"""

import sys
import argparse
from pathlib import Path

from .hypervisor import AIHypervisor, HypervisorConfig


def cmd_run(args):
    """Run an AI tool or shell session under hypervisor."""
    config = HypervisorConfig(
        log_dir=Path(args.log_dir),
        daily_token_limit=args.token_limit,
        daily_cost_limit=args.cost_limit,
        log_raw_pty=args.log_raw,
        log_text_pty=args.log_text,
    )
    
    with AIHypervisor(config) as hv:
        # Print header
        print(f"[AI-HV] Hypervisor active")
        print(f"[AI-HV] Log dir: {config.log_dir}")
        if config.daily_token_limit:
            print(f"[AI-HV] Token limit: {config.daily_token_limit:,}")
        if config.daily_cost_limit:
            print(f"[AI-HV] Cost limit: ${config.daily_cost_limit:.2f}")
        print("-" * 50)
        
        if args.shell_session:
            # Run full interactive shell session
            exit_code = hv.run_shell_session(args.shell)
        else:
            # Run single tool
            print(f"[AI-HV] Tool: {args.tool}")
            print("-" * 50)
            exit_code = hv.run_ai_tool(args.tool, args.tool_args)
        
        # Print summary
        print("-" * 50)
        stats = hv.get_status()
        print(f"[AI-HV] Session complete")
        print(f"[AI-HV] Prompts: {stats['stats']['prompts_submitted']}")
        print(f"[AI-HV] Tokens: {stats['stats']['total_tokens']:,}")
        print(f"[AI-HV] Est cost: ${stats['stats']['estimated_cost_usd']:.4f}")
        
        return exit_code


def cmd_status(args):
    """Show hypervisor status."""
    log_dir = Path(args.log_dir)
    
    # Find latest session
    sessions = sorted(log_dir.glob("session_*"))
    if not sessions:
        print("No sessions found")
        return 1
    
    latest = sessions[-1]
    summary_file = latest / "session_summary.json"
    
    if summary_file.exists():
        import json
        with open(summary_file) as f:
            data = json.load(f)
        
        print(f"Latest session: {latest.name}")
        print(f"  Tool: {data['stats'].get('commands_executed', 'N/A')} commands")
        print(f"  Prompts: {data['stats']['prompts_submitted']}")
        print(f"  Tokens: {data['stats']['total_tokens']:,}")
        print(f"  Cost: ${data['stats']['estimated_cost_usd']:.4f}")
    else:
        print(f"Session incomplete: {latest.name}")
    
    return 0


def cmd_logs(args):
    """Show session logs."""
    log_dir = Path(args.log_dir)
    
    sessions = sorted(log_dir.glob("session_*"))
    if not sessions:
        print("No sessions found")
        return 1
    
    for session in sessions[-args.n:][::-1]:
        print(f"\n{session.name}")
        
        # Check for various log files
        for log_file in ["commands.jsonl", "usage.jsonl", "network.jsonl"]:
            path = session / log_file
            if path.exists():
                count = sum(1 for _ in open(path))
                print(f"  {log_file}: {count} entries")
        
        # Show text log preview
        text_log = session / "pty_text.log"
        if text_log.exists() and args.verbose:
            print("  Preview (last 5 lines):")
            lines = text_log.read_text().splitlines()
            for line in lines[-5:]:
                print(f"    {line[:100]}")
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog='ai-hv',
        description='AI CLI Hypervisor'
    )
    
    parser.add_argument('--log-dir', default='~/.ai_hypervisor',
                       help='Log directory')
    
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run AI tool or shell session')
    run_parser.add_argument('--tool', '-t', default='claude',
                           help='AI tool to run (default: claude)')
    run_parser.add_argument('--shell', '-s', default='/bin/bash',
                           help='Shell for session mode (default: /bin/bash)')
    run_parser.add_argument('--shell-session', '-S', action='store_true',
                           help='Run full interactive shell session')
    run_parser.add_argument('--token-limit', type=int,
                           help='Daily token limit')
    run_parser.add_argument('--cost-limit', type=float,
                           help='Daily cost limit ($)')
    run_parser.add_argument('--log-raw', action='store_true',
                           help='Log raw PTY output')
    run_parser.add_argument('--log-text', action='store_true',
                           help='Log parsed text')
    run_parser.add_argument('tool_args', nargs='*',
                           help='Arguments to pass to tool')
    run_parser.set_defaults(func=cmd_run)
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show status')
    status_parser.set_defaults(func=cmd_status)
    
    # Logs command
    logs_parser = subparsers.add_parser('logs', help='Show logs')
    logs_parser.add_argument('-n', type=int, default=5,
                            help='Number of sessions')
    logs_parser.add_argument('-v', '--verbose', action='store_true',
                            help='Verbose output')
    logs_parser.set_defaults(func=cmd_logs)
    
    args = parser.parse_args()
    args.log_dir = Path(args.log_dir).expanduser()
    
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
