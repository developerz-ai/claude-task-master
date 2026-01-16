# Release Guide

This document describes the process for releasing new versions of Claude Task Master to PyPI.

## Prerequisites

1. **Maintainer access** to the PyPI project
2. **Write access** to the GitHub repository
3. **Up-to-date main branch** with all changes committed

## Release Process

### 1. Prepare the Release

Update the version and changelog:

```bash
# Bump version (choose one):
python scripts/bump_version.py patch   # 0.1.0 -> 0.1.1 (bug fixes)
python scripts/bump_version.py minor   # 0.1.0 -> 0.2.0 (new features)
python scripts/bump_version.py major   # 0.1.0 -> 1.0.0 (breaking changes)

# Or set a specific version:
python scripts/bump_version.py --set 1.2.3
```

This will automatically update:
- `pyproject.toml`
- `src/claude_task_master/__init__.py`
- `CHANGELOG.md` (adds new version section)

### 2. Review Changes

```bash
# Check what changed
git diff

# Verify version consistency
grep -r "0.1.0" pyproject.toml src/claude_task_master/__init__.py
```

### 3. Update CHANGELOG

Edit `CHANGELOG.md` to add release notes under the new version section:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New features

### Changed
- Changes to existing functionality

### Fixed
- Bug fixes

### Security
- Security improvements
```

### 4. Commit and Tag

```bash
# Commit the version bump
git add pyproject.toml src/claude_task_master/__init__.py CHANGELOG.md
git commit -m "chore: bump version to X.Y.Z"

# Create and push tag
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z
```

**Important**: Push the tag AFTER the commit is merged to main.

### 5. Automated Release

When you push a tag matching `v*.*.*`, GitHub Actions will automatically:

1. ✅ **Verify version consistency** - Checks that versions match in:
   - Git tag
   - `pyproject.toml`
   - `src/claude_task_master/__init__.py`

2. ✅ **Run tests** - Full test suite with coverage

3. ✅ **Build package** - Creates sdist and wheel distributions

4. ✅ **Create GitHub Release** - With changelog and artifacts

5. ✅ **Publish to PyPI** - Using trusted publishing (no API token needed)

### 6. Monitor the Release

Check the GitHub Actions workflow:

```bash
# View workflow status
gh run watch

# Or visit: https://github.com/sebyx07/claude-task-master-py/actions
```

The workflow must complete successfully for the package to be published.

### 7. Verify Publication

After the workflow completes:

```bash
# Check PyPI (may take a few minutes to appear)
# Visit: https://pypi.org/project/claude-task-master/

# Test installation
pip install --upgrade claude-task-master
claudetm --version  # Should show new version
```

## Troubleshooting

### Version Mismatch Error

If the release workflow fails with version mismatch:

```bash
# Check all version locations
grep -r "version" pyproject.toml
grep -r "__version__" src/claude_task_master/__init__.py

# Fix manually or re-run bump_version.py
```

### Failed Tests

If tests fail during release:

```bash
# Run tests locally first
pytest --cov=claude_task_master --cov-report=term-missing

# Fix issues and create a new patch version
```

### PyPI Publishing Fails

If PyPI publishing fails:

1. Check that the package name is available (first release only)
2. Verify trusted publishing is configured in PyPI project settings
3. Check the workflow logs for specific errors

### Rollback a Release

If you need to rollback:

```bash
# Delete the tag locally
git tag -d vX.Y.Z

# Delete the tag remotely
git push origin :refs/tags/vX.Y.Z

# Note: You cannot delete a PyPI release, but you can "yank" it
# Visit: https://pypi.org/manage/project/claude-task-master/releases/
```

## Pre-release Testing

### Test on TestPyPI (Optional)

For major releases, you can test on TestPyPI first:

```bash
# Build the package
python -m build

# Install twine
pip install twine

# Upload to TestPyPI (requires TestPyPI account)
twine upload --repository testpypi dist/*

# Test installation from TestPyPI
pip install --index-url https://test.pypi.org/simple/ claude-task-master
```

### Local Testing

```bash
# Build and install locally
python -m build
pip install dist/claude_task_master-X.Y.Z-py3-none-any.whl

# Test the CLI
claudetm --help
claudetm doctor
```

## Release Checklist

Before releasing, ensure:

- [ ] All tests pass locally (`pytest`)
- [ ] Linting passes (`ruff check . && ruff format --check .`)
- [ ] Type checking passes (`mypy .`)
- [ ] Version bumped in all locations
- [ ] CHANGELOG.md updated with release notes
- [ ] Changes committed to main branch
- [ ] Git tag created and pushed
- [ ] GitHub Actions workflow completes successfully
- [ ] Package appears on PyPI
- [ ] Installation works: `pip install claude-task-master`
- [ ] GitHub release created with notes

## Trusted Publishing Setup

This project uses PyPI's trusted publishing (no manual tokens needed).

### First-time Setup on PyPI

1. Create the project on PyPI (maintainer only):
   - Visit https://pypi.org/manage/account/
   - Create new project: `claude-task-master`

2. Configure trusted publishing:
   - Go to project settings
   - Add trusted publisher:
     - Owner: `sebyx07`
     - Repository: `claude-task-master-py`
     - Workflow: `release.yml`
     - Environment: `release`

3. The `release.yml` workflow is already configured with:
   ```yaml
   permissions:
     id-token: write  # Required for trusted publishing
   environment: release  # Required for security
   ```

## Post-Release

After a successful release:

1. Announce the release (if applicable):
   - GitHub Discussions
   - Social media
   - User mailing list

2. Monitor for issues:
   - Check GitHub Issues
   - Monitor PyPI download stats

3. Update documentation if needed

## Version Numbering

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (X.0.0): Breaking changes
- **MINOR** (0.X.0): New features, backward compatible
- **PATCH** (0.0.X): Bug fixes, backward compatible

Pre-release versions:
- **Alpha**: `X.Y.Z-alpha.N`
- **Beta**: `X.Y.Z-beta.N`
- **RC**: `X.Y.Z-rc.N`
