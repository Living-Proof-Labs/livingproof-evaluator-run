# Verification

## Build and inspect

Use Python 3.12.14 and uv 0.13.6 in a prepared environment:

```sh
uv sync --locked
uv run --no-sync python tools/docs.py
uv run --no-sync python -m http.server 8000 --directory site
```

Open `http://localhost:8000/`. The build stages canonical Markdown, fetches the
brand at its locked commit and checks its SHA-256, generates source identity,
builds with Zensical, and checks rendered links, fragments, brand inclusion,
and absence of the stock indigo palette. `site/build.json` records the source
commit and whether the checkout had uncommitted changes.

The workflow uses the same build command. Pull requests build only; their
`evaluator-documentation-review` artifact is retained for 14 days. Main pushes
and manual runs on main can deploy the checked site to GitHub Pages. Other
branches cannot deploy. The live manual is separate from expiring artifacts.

## Publication prerequisites

A maintainer must enable GitHub Pages with GitHub Actions as the source, ensure
Actions and the `github-pages` environment permit the deployment, and review this
PR before merging. This workflow does not change repository settings. Pages
permissions are scoped to the deploy job. No merge or deployment is claimed by
this documentation change.

The configured destination is
`https://docs.livingprooflabs.com/livingproof-evaluator-run/`, subject to the
organization's Pages domain configuration. Use the deployment job's actual
`page_url` as evidence. After publication, check the README journey, source
identity, desktop/mobile/keyboard navigation, a deep link reload, search for
`infrastructure` and opening its result, and organization discovery. Update the
README link to the verified destination only after these checks.

## Scope and adoption exceptions

There is no product code, executable scenario, measured software coverage,
Taskfile, or public command/API/contract to generate reference pages from.
Build checks concern the manual only; they establish no robot capability or
evidence suitability.

For this initial documentation-only scaffold, the local override is a locked
Python environment and one build script instead of Docker, a published tooling
image, and Task. Container/image/Task adoption is deferred to a future tooling
change. This is partial documentation adoption, not full engineering-standards
compliance. The existing Renovate policy remains unchanged.

Current organization/manual/source-directory links are the bounded navigation
exception to release pinning. Executable dependencies and the brand are pinned.
No prior published pages or fragment bookmarks were found to migrate.
External link availability, interactive search, browser navigation and deployed
source identity require separate checks; the static build does not establish them.
