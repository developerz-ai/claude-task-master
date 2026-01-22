"""Sample PR comments for testing.

This module provides test data for PR review comment handling tests.
"""

# Sample CodeRabbit review comments
CODERABBIT_COMMENT = """## CodeRabbit AI Review

**File:** `src/api/auth.js`
**Line:** 23-45

### Issue: Missing Error Handling

The authentication function doesn't properly handle network failures. Consider wrapping the API call in a try-catch block and implementing proper error recovery.

**Suggestion:**
```javascript
try {
  const response = await fetch('/api/auth', options);
  if (!response.ok) {
    throw new Error(`Auth failed: ${response.status}`);
  }
  return response.json();
} catch (error) {
  console.error('Authentication error:', error);
  throw error;
}
```

---

**File:** `src/utils/helpers.js`
**Line:** 67

### Issue: Potential Memory Leak

The event listener is never removed. This could cause memory leaks in long-running applications.

**Suggestion:** Store the listener reference and remove it in a cleanup function.
"""

# Sample human reviewer comment
HUMAN_REVIEWER_COMMENT = """## Review by @senior-dev

### General Comments

Good progress on the feature implementation! A few things to address:

1. **Code Style**: Please follow the project's naming conventions for variables
2. **Documentation**: Add JSDoc comments to the public API functions
3. **Tests**: The test coverage for edge cases is insufficient

### Specific Issues

**src/components/UserForm.jsx:34**
> The form validation logic should be extracted to a custom hook for reusability.

**src/api/client.ts:89**
> Consider using axios interceptors instead of manual error handling in each request.

### Approved with Comments

Once the above items are addressed, this PR is good to merge.
"""

# Sample automated review comment (e.g., from linters)
AUTOMATED_REVIEW_COMMENT = """## Automated Code Review

### SonarCloud Analysis

**Quality Gate Status:** ⚠️ Warning

| Metric | Value | Status |
|--------|-------|--------|
| Bugs | 0 | ✅ |
| Vulnerabilities | 1 | ⚠️ |
| Code Smells | 5 | ⚠️ |
| Coverage | 72.3% | ✅ |
| Duplications | 3.2% | ✅ |

### Security Vulnerability Found

**File:** `src/config/database.js:15`
**Type:** SQL Injection Risk
**Severity:** High

The database query uses string concatenation which could allow SQL injection attacks.

**Current code:**
```javascript
const query = `SELECT * FROM users WHERE id = ${userId}`;
```

**Recommended fix:**
```javascript
const query = `SELECT * FROM users WHERE id = $1`;
const result = await client.query(query, [userId]);
```
"""

# Sample inline code comment
INLINE_CODE_COMMENT = """**File:** `src/api/handler.py`
**Line:** 42

@developer-2 commented:
> This function is getting too complex. Consider breaking it into smaller functions:
> - `validate_input()`
> - `process_data()`
> - `format_response()`
"""

# Combined comments scenario
COMBINED_COMMENTS = f"""# PR #123 Review Comments

{CODERABBIT_COMMENT}

---

{HUMAN_REVIEWER_COMMENT}

---

{AUTOMATED_REVIEW_COMMENT}

---

{INLINE_CODE_COMMENT}
"""

# Edge case comments
EDGE_CASE_COMMENTS = {
    "empty": "",
    "whitespace_only": "   \n\t\n   ",
    "unicode": "Review: 日本語コメント with emoji 👍",
    "special_chars": 'Comment with "quotes" and <html> & symbols',
    "very_long": "Detailed comment. " * 500,
    "code_block": """
```python
def example():
    # This is sample code
    return {"status": "ok"}
```

Please update to match this pattern.
""",
}


def get_sample_pr_comments():
    """Get a dictionary of sample PR comments by type."""
    return {
        "coderabbit": CODERABBIT_COMMENT,
        "human": HUMAN_REVIEWER_COMMENT,
        "automated": AUTOMATED_REVIEW_COMMENT,
        "inline": INLINE_CODE_COMMENT,
        "combined": COMBINED_COMMENTS,
    }


def get_pr_comment_for_type(comment_type: str) -> str:
    """Get a specific PR comment by type."""
    comments = get_sample_pr_comments()
    result = comments.get(comment_type, HUMAN_REVIEWER_COMMENT)
    return str(result)


def get_edge_case_comment(case_type: str) -> str:
    """Get an edge case comment for testing."""
    return EDGE_CASE_COMMENTS.get(case_type, "")
