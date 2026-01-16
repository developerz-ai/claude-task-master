"""Utility functions for orchestrator-workers workflow examples.

This module provides helper functions for making LLM calls and parsing XML responses.
Used by the orchestrator-workers notebook examples.
"""

import re

import anthropic


def llm_call(
    prompt: str,
    system_prompt: str = "",
    model: str = "claude-sonnet-4-5",
) -> str:
    """Send a prompt to Claude and return the text response.

    Args:
        prompt: The user message to send to Claude.
        system_prompt: Optional system prompt to set context.
        model: The model ID to use (default: claude-sonnet-4-5).

    Returns:
        The text content from Claude's response.

    Raises:
        anthropic.APIError: If the API call fails.
    """
    client = anthropic.Anthropic()

    messages = [{"role": "user", "content": prompt}]

    kwargs = {
        "model": model,
        "max_tokens": 4096,
        "messages": messages,
    }

    if system_prompt:
        kwargs["system"] = system_prompt

    response = client.messages.create(**kwargs)

    # Extract text from response
    text_blocks = [block.text for block in response.content if hasattr(block, "text")]
    return "\n".join(text_blocks)


def extract_xml(text: str, tag: str) -> str:
    """Extract content from XML tags using regex.

    Args:
        text: The text containing XML tags.
        tag: The tag name to extract (without angle brackets).

    Returns:
        The content between the opening and closing tags,
        or an empty string if not found.

    Example:
        >>> extract_xml("<analysis>Some content</analysis>", "analysis")
        'Some content'
    """
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""
