"""Sample CI failure logs for testing.

This module provides test data for CI failure handling tests.
"""

# Sample CI failure logs from different CI providers
GITHUB_ACTIONS_FAILURE = """Run npm test
npm ERR! code ELIFECYCLE
npm ERR! errno 1
npm ERR! test@1.0.0 test: `jest --coverage`
npm ERR! Exit status 1
npm ERR!
npm ERR! Failed at the test@1.0.0 test script.

 FAIL  src/__tests__/auth.test.js
  ● Test suite failed to run

    SyntaxError: Unexpected token

      at Runtime.createScriptFromCode (node_modules/jest-runtime/build/index.js:1728:14)

Test Suites: 1 failed, 5 passed, 6 total
Tests:       2 failed, 23 passed, 25 total
Snapshots:   0 total
Time:        5.123 s
"""

ESLINT_FAILURE = """> eslint . --ext .js,.jsx,.ts,.tsx

/home/runner/work/repo/src/api/auth.js
   5:10  error  'response' is defined but never used  no-unused-vars
  12:23  error  Missing semicolon                     semi
  28:5   error  Unexpected console statement          no-console

/home/runner/work/repo/src/utils/helpers.js
   3:1   error  'lodash' is already declared in the upper scope  no-shadow
  15:40  error  Expected '===' and instead saw '=='              eqeqeq

✖ 5 problems (5 errors, 0 warnings)
  2 errors and 0 warnings potentially fixable with the `--fix` option.

error Command failed with exit code 1.
"""

TYPESCRIPT_FAILURE = """src/components/UserProfile.tsx:23:15 - error TS2322: Type 'string' is not assignable to type 'number'.

23     const age: number = user.age;
                 ~~~

src/components/UserProfile.tsx:45:7 - error TS2339: Property 'fullName' does not exist on type 'User'.

45       user.fullName
         ~~~~~~~~

src/api/client.ts:67:3 - error TS2345: Argument of type 'string' is not assignable to parameter of type 'RequestConfig'.

67   fetchData("invalid");
     ~~~~~~~~~~~~~~~~~~~~~


Found 3 errors in 2 files.

Errors  Files
     2  src/components/UserProfile.tsx:23
     1  src/api/client.ts:67
"""

PYTHON_TEST_FAILURE = """============================= test session starts ==============================
platform linux -- Python 3.11.0, pytest-7.4.0, pluggy-1.2.0
rootdir: /home/runner/work/repo
collected 45 items

tests/test_auth.py .....F...
tests/test_api.py ....F....
tests/test_utils.py ..........

================================= FAILURES =================================
________________________________ test_login ________________________________

    def test_login():
        response = client.post("/login", json={"username": "test", "password": "wrong"})
>       assert response.status_code == 401
E       AssertionError: assert 500 == 401
E        +  where 500 = <Response [500]>.status_code

tests/test_auth.py:25: AssertionError
________________________________ test_get_user ________________________________

    def test_get_user():
        response = client.get("/users/1")
>       assert response.json()["name"] == "John"
E       KeyError: 'name'

tests/test_api.py:42: KeyError
=========================== short test summary info ============================
FAILED tests/test_auth.py::test_login - AssertionError: assert 500 == 401
FAILED tests/test_api.py::test_get_user - KeyError: 'name'
========================= 2 failed, 43 passed in 3.21s =========================
"""

RUFF_FAILURE = """ruff check .
src/main.py:1:1: F401 [*] `os` imported but unused
src/main.py:15:5: E501 Line too long (120 > 88)
src/utils.py:23:1: E302 Expected 2 blank lines, found 1
src/api/handler.py:67:9: B006 Do not use mutable data structures for argument defaults
Found 4 errors.
[*] 1 fixable with the `--fix` option.
"""

BUILD_FAILURE = """> next build

Creating an optimized production build...

Error: Build failed because of webpack errors
./src/pages/index.js
Module not found: Can't resolve 'missing-package'

./src/components/Header.js
Module not found: Can't resolve '@/styles/header.css'

info  - Creating an optimized production build .
Error: Cannot find module 'react'
    at Function.Module._resolveFilename (node:internal/modules/cjs/loader:933:15)
    at Function.Module._load (node:internal/modules/cjs/loader:778:27)

error Command failed with exit code 1.
"""

# Combined CI failure scenario
COMBINED_CI_FAILURES = f"""=== CI Run Summary ===

Job: test (1/3) - FAILED
Job: lint (2/3) - FAILED
Job: build (3/3) - PASSED

=== Test Failures ===
{PYTHON_TEST_FAILURE}

=== Lint Failures ===
{ESLINT_FAILURE}

=== Build Status ===
Build completed successfully.
"""


def get_sample_ci_failures():
    """Get a dictionary of sample CI failures by type."""
    return {
        "github-actions": GITHUB_ACTIONS_FAILURE,
        "eslint": ESLINT_FAILURE,
        "typescript": TYPESCRIPT_FAILURE,
        "pytest": PYTHON_TEST_FAILURE,
        "ruff": RUFF_FAILURE,
        "build": BUILD_FAILURE,
        "combined": COMBINED_CI_FAILURES,
    }


def get_ci_failure_for_type(failure_type: str) -> str:
    """Get a specific CI failure log by type."""
    failures = get_sample_ci_failures()
    result = failures.get(failure_type, GITHUB_ACTIONS_FAILURE)
    return str(result)
