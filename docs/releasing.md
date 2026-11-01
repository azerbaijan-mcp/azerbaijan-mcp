# Releasing

Each package is released on its own, by pushing a tag named `<package>-v<version>`, for example `cbar-v0.1.0`. The tag version must equal `version` in `packages/<package>/pyproject.toml`.

| Tag | What happens |
|---|---|
| `cbar-v0.1.0` | Tests, build, publish to PyPI, then list in the MCP Registry |
| `cbar-v0.1.0rc1` (also `a`, `b` and `.dev` versions) | Tests, build, publish to TestPyPI only |

## One-time setup

1. Make the GitHub repository public. The registry entry links to it.
2. PyPI: for each new package add a pending trusted publisher at <https://pypi.org/manage/account/publishing/>:
   - PyPI project name: `azerbaijan-mcp-cbar`
   - Owner: `azerbaijan-mcp`
   - Repository name: `azerbaijan-mcp`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. TestPyPI: the same at <https://test.pypi.org/manage/account/publishing/> with environment name `testpypi`.
4. GitHub: the `pypi` and `testpypi` environments are created by the first run. To require a manual approval before anything is published, add yourself as a required reviewer on `pypi` (Settings, Environments).
5. MCP Registry: nothing to configure. The workflow logs in with GitHub OIDC, so the names `io.github.azerbaijan-mcp/*` belong to this organization.

## Dry run on TestPyPI

1. On a throwaway branch set the version to a pre-release, for example `0.1.0rc1` in `packages/cbar/pyproject.toml`, then run `uv lock` and `python scripts/release.py stamp cbar`. Without `uv lock`, `uv sync --locked` fails because the lockfile records each package's version.
2. Commit, tag that commit `cbar-v0.1.0rc1` and push only the tag: `git tag cbar-v0.1.0rc1 && git push origin cbar-v0.1.0rc1`.
3. Watch the Release workflow, then install the result (untested until the first dry run; adjust the flags if uv has changed): `uvx --index-strategy unsafe-best-match --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ azerbaijan-mcp-cbar==0.1.0rc1`.
4. Delete the branch and the tag. TestPyPI never accepts a version twice, so the next dry run needs `rc2`.

## Release

1. Bump `version` in `packages/<package>/pyproject.toml`, run `uv lock` and `python scripts/release.py stamp <package>`, and merge that through a PR with green CI.
2. Tag the merge commit on `main` and push the tag: `git tag cbar-v0.1.0 && git push origin cbar-v0.1.0`.
3. The workflow checks the tag against `pyproject.toml`, `server.json` and the README marker, runs the tests, builds, publishes to PyPI, waits until PyPI serves the version with the marker, then publishes `server.json` to the registry.
4. Check the PyPI page, then `curl 'https://registry.modelcontextprotocol.io/v0.1/servers?search=cbar'`, then run `uvx azerbaijan-mcp-cbar` on a clean machine.

## When something fails

- PyPI never accepts the same version twice. Fix the problem and release the next patch version.
- If PyPI succeeded and the registry step failed, re-run only the `publish-registry` job from the Actions page.
- `invalid-publisher` from PyPI or TestPyPI means no trusted publisher entry matches. The failed step prints the claims it presented (owner, repository, workflow, environment). Compare them with the entry. PyPI and TestPyPI are separate sites with separate entries. After fixing it, use "Re-run failed jobs" on the run; no new tag is needed.
- The registry is still in preview. Read its current docs before the first release.

## Pinned tooling

GitHub Actions are pinned by commit SHA and Dependabot opens PRs to bump them. `mcp-publisher` is pinned in `release.yml` by version and SHA-256 (the digest on its GitHub release page). To bump it, change both values together.
