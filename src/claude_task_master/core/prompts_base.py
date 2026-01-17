"""Base Prompt Components for Claude Task Master.

This module provides the foundational classes for building prompts:
- PromptSection: A section with title and content
- PromptBuilder: Builds prompts from multiple sections
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromptSection:
    """A section of a prompt with a title and content.

    Attributes:
        title: Section header (will be formatted as ## title).
        content: The content of the section.
        include_if: Optional condition - if False, section is omitted.
    """

    title: str
    content: str
    include_if: bool = True

    def render(self) -> str:
        """Render the section as markdown."""
        if not self.include_if:
            return ""
        return f"## {self.title}\n\n{self.content}"


@dataclass
class PromptBuilder:
    """Builds prompts from sections.

    Attributes:
        intro: Opening text before sections.
        sections: List of prompt sections.
    """

    intro: str = ""
    sections: list[PromptSection] = field(default_factory=list)

    def add_section(
        self,
        title: str,
        content: str,
        include_if: bool = True,
    ) -> PromptBuilder:
        """Add a section to the prompt.

        Args:
            title: Section header.
            content: Section content.
            include_if: Whether to include this section.

        Returns:
            Self for chaining.
        """
        self.sections.append(PromptSection(title, content, include_if))
        return self

    def build(self) -> str:
        """Build the final prompt string.

        Returns:
            Complete prompt as string.
        """
        parts = []
        if self.intro:
            parts.append(self.intro)

        for section in self.sections:
            rendered = section.render()
            if rendered:
                parts.append(rendered)

        return "\n\n".join(parts)
