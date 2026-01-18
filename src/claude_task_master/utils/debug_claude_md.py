#!/usr/bin/env python3
"""Debug script to verify CLAUDE.md detection when changing directories for queries.

This script performs a simple query in a specified directory and asks Claude
to report what code style instructions it can see, which would come from CLAUDE.md.

Usage:
    # From project root (uses current directory)
    uv run python -m claude_task_master.utils.debug_claude_md

    # Specify a different directory
    uv run python -m claude_task_master.utils.debug_claude_md /path/to/project
"""

import asyncio
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()


async def debug_claude_md_detection(working_dir: str | None = None) -> bool:
    """Run a simple query to test CLAUDE.md detection.

    Args:
        working_dir: Directory to use for the query. Defaults to current directory.

    Returns:
        True if CLAUDE.md appears to be detected, False otherwise.
    """
    # Use current directory if not specified
    target_dir = Path(working_dir).resolve() if working_dir else Path.cwd()

    console.print(
        Panel.fit(
            f"[bold blue]Debug: CLAUDE.md Detection[/bold blue]\n\n"
            f"Target directory: [cyan]{target_dir}[/cyan]",
            border_style="blue",
        )
    )

    # Check if CLAUDE.md exists
    claude_md_path = target_dir / "CLAUDE.md"
    if claude_md_path.exists():
        console.print(f"[green]✓[/green] CLAUDE.md exists at {claude_md_path}")
        console.print(f"  Size: {claude_md_path.stat().st_size} bytes")
    else:
        console.print(f"[yellow]![/yellow] CLAUDE.md not found at {claude_md_path}")

    # Try to import the SDK
    try:
        import claude_agent_sdk

        console.print("[green]✓[/green] claude_agent_sdk imported successfully")
    except ImportError as e:
        console.print(f"[red]✗[/red] Failed to import claude_agent_sdk: {e}")
        return False

    # Check credentials
    creds_path = Path.home() / ".claude" / ".credentials.json"
    if not creds_path.exists():
        console.print(f"[red]✗[/red] Credentials not found at {creds_path}")
        console.print("  Run: [cyan]claude[/cyan] to authenticate first")
        return False
    console.print("[green]✓[/green] Credentials found")

    console.print("\n[bold]Running test query...[/bold]")
    console.print("Asking Claude: 'What code style instructions do you see?'\n")

    # Store original directory
    original_dir = os.getcwd()

    try:
        # Change to target directory (simulating what agent_query.py does)
        os.chdir(target_dir)
        console.print(f"[dim]Changed to: {os.getcwd()}[/dim]")

        # Create options with cwd and setting_sources
        options = claude_agent_sdk.ClaudeAgentOptions(
            allowed_tools=["Read"],  # Minimal tools for test
            permission_mode="bypassPermissions",
            model="claude-haiku-4-5-20251001",  # Use Haiku for speed/cost
            cwd=str(target_dir),
            setting_sources=["user", "local", "project"],  # Load CLAUDE.md
        )

        prompt = """You are being tested to verify CLAUDE.md loading.

Please answer these questions briefly:
1. Do you see any code style instructions (e.g., max lines per file, SRP)?
2. Do you see any project-specific commands (e.g., for running tests)?
3. What is the project name mentioned in your context?

If you see a "Code Style" or project-specific section, quote 1-2 key lines from it.
If you don't see any project context, just say "No CLAUDE.md context detected."
"""

        result_text = ""
        async for message in claude_agent_sdk.query(prompt=prompt, options=options):
            message_type = type(message).__name__

            if message_type == "ResultMessage":
                if hasattr(message, "result"):
                    result = getattr(message, "result", None)
                    if isinstance(result, str):
                        result_text = result
            elif hasattr(message, "content"):
                for block in message.content:
                    block_type = type(block).__name__
                    if block_type == "TextBlock" and hasattr(block, "text"):
                        text = getattr(block, "text", "")
                        # Print streaming output
                        console.print(text, end="", style="dim")
                        result_text += text

        console.print()  # Newline after streaming

    except Exception as e:
        console.print(f"\n[red]✗[/red] Query failed: {type(e).__name__}: {e}")
        return False
    finally:
        # Always restore original directory
        os.chdir(original_dir)
        console.print(f"[dim]Restored to: {os.getcwd()}[/dim]")

    # Analyze result
    console.print("\n[bold]Analysis:[/bold]")

    result_lower = result_text.lower()
    detected_indicators = []

    if "claude task master" in result_lower or "task master" in result_lower:
        detected_indicators.append("Project name 'Claude Task Master'")
    if "max 500 loc" in result_lower or "500 lines" in result_lower:
        detected_indicators.append("Code style: max 500 LOC per file")
    if "single responsibility" in result_lower or "srp" in result_lower:
        detected_indicators.append("Code style: Single Responsibility Principle")
    if "pytest" in result_lower or "ruff" in result_lower:
        detected_indicators.append("Development commands (pytest, ruff)")
    if "no claude.md" in result_lower or "no context" in result_lower:
        console.print("[yellow]⚠[/yellow] Claude did not detect CLAUDE.md context")
        return False

    if detected_indicators:
        console.print("[green]✓[/green] CLAUDE.md appears to be loaded! Detected:")
        for indicator in detected_indicators:
            console.print(f"  • {indicator}")
        return True
    else:
        console.print("[yellow]?[/yellow] Unable to confirm CLAUDE.md loading from response")
        console.print(
            "[dim]This could mean the context was loaded but Claude didn't cite specific content[/dim]"
        )
        return True  # Assume success if no explicit denial


def main() -> None:
    """Main entry point."""
    # Get working directory from args or use current
    working_dir = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        success = asyncio.run(debug_claude_md_detection(working_dir))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(2)


if __name__ == "__main__":
    main()
