---
description: Checking markdown links and anchors after a docs edit. Use for docs, markdown link, anchor, broken link, cross-reference.
applies: [python]
---

> House skill — established by dz-runner setup mode from this repo's own evidence, then owned by its maintainers. Correct it in place; setup never overwrites a skill that exists.

1. Run `python verify_docs_links.py` -> "All N links verified successfully!" -> done.
2. A red run prints each broken link with its file and line number -> fix the target path or the anchor in the file it names, then re-run.
3. The script resolves relative markdown links, relative file paths and `#anchor` references inside the same file -> an anchor rename breaks the link that names it.
4. It scans every `*.md` in the repo (README, `docs/`, `examples/`, `CHANGELOG.md`) and skips `.venv` and `.claude-task-master` -> a new doc directory needs no extra configuration.
5. The gate does not check links -> run this after any edit under `docs/`, `examples/` or a README, before the gate.
