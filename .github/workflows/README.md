# GitHub Actions Workflows

## Docker Publishing

The `docker-publish.yml` workflow automatically builds and publishes Docker images to GitHub Container Registry (ghcr.io) when version tags are pushed.

### Trigger

The workflow is triggered by pushing semantic version tags:
```bash
git tag v1.0.0
git push origin v1.0.0
```

### Features

- **Multi-architecture support**: Builds for `linux/amd64` and `linux/arm64`
- **Automatic tagging**: 
  - Version tag (e.g., `1.0.0`)
  - Major.minor tag (e.g., `1.0`)
  - Major tag (e.g., `1`) - only for stable releases
  - `latest` tag - only for stable releases (non-prerelease)
- **Artifact attestation**: Generates build provenance for security
- **Caching**: Uses GitHub Actions cache for faster builds

### Testing

The workflow has been tested and verified to work correctly. A test tag `v0.1.3-test` was created, pushed to trigger the workflow, and then deleted after verification.

### Image Location

Published images are available at:
```text
ghcr.io/developerz-ai/claude-task-master
```

Pull the latest image:
```bash
docker pull ghcr.io/developerz-ai/claude-task-master:latest
```
