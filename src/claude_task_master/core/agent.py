"""Agent Wrapper - Encapsulates all Claude Agent SDK interactions."""

from typing import Any, Optional
from enum import Enum
import asyncio
import os


class ModelType(Enum):
    """Available Claude models."""

    SONNET = "sonnet"
    OPUS = "opus"
    HAIKU = "haiku"


class ToolConfig(Enum):
    """Tool configurations for different phases."""

    PLANNING = ["Read", "Glob", "Grep"]
    WORKING = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]


class AgentWrapper:
    """Wraps Claude Agent SDK for task execution."""

    def __init__(self, access_token: str, model: ModelType, working_dir: str = "."):
        """Initialize agent wrapper."""
        self.access_token = access_token
        self.model = model
        self.working_dir = working_dir

        # Import Claude Agent SDK
        try:
            from claude_agent_sdk import query, ClaudeAgentOptions
            self.query = query
            self.options_class = ClaudeAgentOptions
        except ImportError:
            raise RuntimeError(
                "claude-agent-sdk not installed. Install with: pip install claude-agent-sdk"
            )

        # Note: The Claude Agent SDK will automatically use credentials from
        # ~/.claude/.credentials.json if no ANTHROPIC_API_KEY is set

    def run_planning_phase(
        self, goal: str, context: str = ""
    ) -> dict[str, Any]:
        """Run planning phase with read-only tools."""
        # Build prompt for planning
        prompt = self._build_planning_prompt(goal, context)

        # Run async query
        result = asyncio.run(self._run_query(
            prompt=prompt,
            tools=self.get_tools_for_phase("planning"),
        ))

        # Parse result to extract plan and criteria
        return {
            "plan": self._extract_plan(result),
            "criteria": self._extract_criteria(result),
            "raw_output": result,
        }

    def run_work_session(
        self,
        task_description: str,
        context: str = "",
        pr_comments: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run a work session with full tools."""
        # Build prompt for work session
        prompt = self._build_work_prompt(task_description, context, pr_comments)

        # Run async query
        result = asyncio.run(self._run_query(
            prompt=prompt,
            tools=self.get_tools_for_phase("working"),
        ))

        return {
            "output": result,
            "success": True,  # For MVP, assume success
        }

    def verify_success_criteria(
        self, criteria: str, context: str = ""
    ) -> dict[str, Any]:
        """Verify if success criteria are met."""
        prompt = f"""Review the following success criteria and verify if they have been met:

{criteria}

{context}

Respond with:
1. Whether each criterion is met (yes/no)
2. Overall success (all criteria met)
3. Any issues or gaps

Format your response clearly."""

        # Run async query
        result = asyncio.run(self._run_query(
            prompt=prompt,
            tools=self.get_tools_for_phase("planning"),
        ))

        # For MVP, simple check for success indicators
        success = "all criteria met" in result.lower() or "success" in result.lower()

        return {
            "success": success,
            "details": result,
        }

    async def _run_query(self, prompt: str, tools: list[str]) -> str:
        """Run query and collect result."""
        result_text = ""

        # Change to working directory for the query
        import os
        original_dir = os.getcwd()

        try:
            os.chdir(self.working_dir)

            options = self.options_class(
                allowed_tools=tools,
                permission_mode="bypassPermissions",  # For MVP, bypass permissions
            )

            async for message in self.query(prompt=prompt, options=options):
                # Handle different message types from claude-agent-sdk
                message_type = type(message).__name__

                if hasattr(message, "content") and message.content:
                    # Assistant or User messages with content
                    for block in message.content:
                        block_type = type(block).__name__

                        if block_type == "TextBlock":
                            # Claude's text response
                            print(block.text, end="", flush=True)
                            result_text += block.text
                        elif block_type == "ToolUseBlock":
                            # Tool being invoked
                            print(f"\n🔧 Using tool: {block.name}", flush=True)
                        elif block_type == "ToolResultBlock":
                            # Tool result - show completion
                            if block.is_error:
                                print(f"❌ Tool error\n", flush=True)
                            else:
                                print(f"✓ Tool completed\n", flush=True)

                # Collect final result from ResultMessage
                if message_type == "ResultMessage":
                    if hasattr(message, "result"):
                        result_text = message.result
                        print("\n")  # Add newline after completion

        except Exception as e:
            # Print full exception details
            import traceback
            print(f"\n\n❌ Exception in _run_query: {type(e).__name__}: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
            raise

        finally:
            # Always restore original directory
            os.chdir(original_dir)

        return result_text

    def get_tools_for_phase(self, phase: str) -> list[str]:
        """Get appropriate tools for the given phase."""
        if phase == "planning":
            return ToolConfig.PLANNING.value
        else:
            return ToolConfig.WORKING.value

    def _get_model_name(self) -> str:
        """Convert ModelType to API model name."""
        model_map = {
            ModelType.SONNET: "claude-sonnet-4-20250514",
            ModelType.OPUS: "claude-opus-4-20250514",
            ModelType.HAIKU: "claude-3-5-haiku-20241022",
        }
        return model_map.get(self.model, "claude-sonnet-4-20250514")

    def _build_planning_prompt(self, goal: str, context: str) -> str:
        """Build prompt for planning phase."""
        prompt = f"""You are Claude Task Master, an autonomous task orchestration system.

GOAL: {goal}

Your task is to:
1. Analyze the goal and understand what needs to be done
2. Explore the codebase if relevant (use Read, Glob, Grep tools)
3. Create a detailed, well-organized task list with markdown checkboxes
4. Define clear, testable success criteria

IMPORTANT SETUP:
- If the project has a .gitignore file, ensure that .claude-task-master/ is added to it
- This directory contains task state and should not be committed to version control

{context}

Please create a comprehensive plan with:

## Task List

Organize tasks into logical phases if the goal is complex. Each task should be:
- **Specific and actionable** - Clear what needs to be done
- **Testable** - Can verify when complete
- **Appropriately sized** - Not too large or too small
- **Ordered logically** - Dependencies should come first

Use this format:
- [ ] Task description (be specific about what and where)
- [ ] Another task with clear deliverables
...

## Success Criteria

Define 3-5 clear, measurable criteria that indicate complete success:
1. Criterion with specific metric or outcome
2. Another criterion that can be objectively verified
...

Remember: The task list will be executed sequentially, so order matters."""
        return prompt

    def _build_work_prompt(
        self, task_description: str, context: str, pr_comments: Optional[str]
    ) -> str:
        """Build prompt for work session."""
        prompt = f"""You are Claude Task Master working on a specific task.

CURRENT TASK: {task_description}

{context}"""

        if pr_comments:
            prompt += f"""

PR REVIEW COMMENTS TO ADDRESS:
{pr_comments}"""

        prompt += """

Please complete this task using the available tools (Read, Write, Edit, Bash, Glob, Grep).

Important instructions:
- Work autonomously and methodically
- Test your changes to verify they work
- After completing the task, COMMIT your changes with git
- Use a clear, descriptive commit message
- When you complete the task, provide a clear summary of what was done
- Report any blockers or issues encountered

Git commit format:
```bash
git add -A && git commit -m "$(cat <<'EOF'
Brief description of changes

Detailed explanation of what was done and why.

Co-Authored-By: Claude Sonnet 4.5 (1M context) <noreply@anthropic.com>
EOF
)"
```

When done, summarize:
1. What was completed
2. Any tests run and their results
3. Any files modified
4. Git commit made"""

        return prompt

    def _extract_plan(self, result: str) -> str:
        """Extract task list from planning result."""
        # For MVP, return the full result - we'll parse later
        if "## Task List" in result:
            return result

        # If no proper format, wrap it
        return f"## Task List\n\n{result}"

    def _extract_criteria(self, result: str) -> str:
        """Extract success criteria from planning result."""
        # Look for success criteria section
        if "## Success Criteria" in result:
            parts = result.split("## Success Criteria")
            if len(parts) > 1:
                return parts[1].strip()

        # Default criteria if none specified
        return "All tasks in the task list are completed successfully."
