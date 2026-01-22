"""Sample plans for testing plan updates.

This module provides test data for plan update and modification tests.
"""

# Simple plan with tasks
SIMPLE_PLAN = """## Task List

- [ ] Set up project structure
- [ ] Implement core feature
- [ ] Add unit tests
- [ ] Write documentation

## Success Criteria

1. All tests pass with >80% coverage
2. Documentation is complete
3. No critical bugs
"""

# Plan with some completed tasks
PARTIALLY_COMPLETE_PLAN = """## Task List

- [x] Set up project structure
- [x] Implement core feature
- [ ] Add unit tests
- [ ] Write documentation
- [ ] Deploy to staging

## Success Criteria

1. All tests pass with >80% coverage
2. Documentation is complete
3. Staging deployment successful
"""

# Plan with PR grouping structure
PR_GROUPED_PLAN = """## Task List

### PR 1: Infrastructure
- [x] `[quick]` Setup project structure
- [x] `[coding]` Add configuration module
- [ ] `[coding]` Implement database layer

### PR 2: Core Features
- [ ] `[coding]` Add user authentication
- [ ] `[coding]` Implement API endpoints
- [ ] `[general]` Add input validation

### PR 3: Testing & Documentation
- [ ] `[general]` Write unit tests
- [ ] `[general]` Write integration tests
- [ ] `[quick]` Update documentation

## Success Criteria

1. All PRs merged to main
2. All tests pass with >90% coverage
3. API documentation complete
"""

# Complex plan with nested tasks and notes
COMPLEX_PLAN = """## Task List

### Phase 1: Foundation

**Backend Infrastructure**
- [x] `[quick]` Initialize project with proper tooling
- [x] `[coding]` Set up database schema
- [ ] `[coding]` Implement base models

**API Layer**
- [ ] `[coding]` Create REST endpoints
- [ ] `[coding]` Add GraphQL support (optional)

### Phase 2: Features

**User Management**
- [ ] `[coding]` User registration
- [ ] `[coding]` User authentication (OAuth2)
- [ ] `[coding]` User profile management

**Core Business Logic**
- [ ] `[coding]` Implement main workflow
- [ ] `[coding]` Add notification system
- [ ] `[general]` Error handling and logging

### Phase 3: Polish

- [ ] `[general]` Comprehensive testing
- [ ] `[quick]` Performance optimization
- [ ] `[quick]` Documentation update

## Success Criteria

1. All phases completed
2. Test coverage > 85%
3. Load testing passes (1000 concurrent users)
4. Security audit completed
5. Documentation approved by tech lead

## Notes

- Use TypeScript for frontend
- PostgreSQL for database
- Redis for caching
"""

# Plan with all tasks completed
COMPLETED_PLAN = """## Task List

- [x] Set up project structure
- [x] Implement core feature
- [x] Add unit tests
- [x] Write documentation
- [x] Deploy to production

## Success Criteria

1. All tests pass with >80% coverage ✓
2. Documentation is complete ✓
3. Production deployment successful ✓

## Completion Notes

All tasks completed successfully on 2025-01-15.
"""

# Empty plan (no tasks)
EMPTY_PLAN = """## Task List

No tasks defined yet.

## Success Criteria

1. Define requirements first
"""

# Plan with code examples
PLAN_WITH_CODE = """## Task List

- [ ] Implement the following API endpoint:
  ```python
  @app.route("/api/users")
  def get_users():
      return jsonify(users)
  ```
- [ ] Add authentication middleware
- [ ] Write tests

## Success Criteria

1. API returns 200 OK
2. Tests pass
"""

# Plan for update testing - before update
PLAN_BEFORE_UPDATE = """## Task List

### PR 1: Core
- [x] Setup
- [ ] Feature A
- [ ] Feature B

## Success Criteria

1. All done
"""

# Plan for update testing - after update (new tasks added)
PLAN_AFTER_UPDATE = """## Task List

### PR 1: Core
- [x] Setup
- [ ] Feature A
- [ ] Feature B
- [ ] Feature C (NEW from change request)

### PR 2: Enhancement (NEW)
- [ ] Add logging
- [ ] Add monitoring

## Success Criteria

1. All done
2. Logging enabled (NEW)
"""


def get_sample_plans():
    """Get a dictionary of sample plans by type."""
    return {
        "simple": SIMPLE_PLAN,
        "partial": PARTIALLY_COMPLETE_PLAN,
        "pr_grouped": PR_GROUPED_PLAN,
        "complex": COMPLEX_PLAN,
        "completed": COMPLETED_PLAN,
        "empty": EMPTY_PLAN,
        "with_code": PLAN_WITH_CODE,
        "before_update": PLAN_BEFORE_UPDATE,
        "after_update": PLAN_AFTER_UPDATE,
    }


def get_plan_for_type(plan_type: str) -> str:
    """Get a specific plan by type."""
    plans = get_sample_plans()
    result = plans.get(plan_type, SIMPLE_PLAN)
    return str(result)


def get_plan_with_n_tasks(n: int, completed: int = 0) -> str:
    """Generate a plan with n tasks, with specified number completed."""
    tasks = []
    for i in range(n):
        checkbox = "[x]" if i < completed else "[ ]"
        tasks.append(f"- {checkbox} Task {i + 1}")

    return f"""## Task List

{chr(10).join(tasks)}

## Success Criteria

1. All {n} tasks completed
"""


def get_plan_with_pr_groups(group_count: int, tasks_per_group: int = 3) -> str:
    """Generate a plan with PR groups."""
    groups = []
    for g in range(group_count):
        tasks = [f"- [ ] Task {g + 1}.{t + 1}" for t in range(tasks_per_group)]
        groups.append(f"""### PR {g + 1}: Group {g + 1}
{chr(10).join(tasks)}""")

    return f"""## Task List

{chr(10).join(groups)}

## Success Criteria

1. All PRs merged
"""
