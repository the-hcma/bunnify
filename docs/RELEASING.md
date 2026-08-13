# Releasing bunnify

Releases are automated with
[Release Please](https://github.com/googleapis/release-please) and PyPI trusted
publishing. Do not edit the package version or create release tags manually.

## Release flow

1. Merge changes to `main` using
   [Conventional Commits](https://www.conventionalcommits.org/). `feat:` creates
   a minor release, `fix:` creates a patch release, and a breaking change
   creates a major release.
2. Release Please opens or updates its release PR with the next version,
   `CHANGELOG.md`, `pyproject.toml`, and `uv.lock`.
3. Review and merge the release PR.
4. Release Please creates the version tag and GitHub release.
5. The release workflow builds the wheel and source distribution, publishes
   them to PyPI with OpenID Connect (OIDC), and verifies the installed commands.

Release Please scans every commit since the previous tag. Keep squash commit
subjects conventional, and configure GitHub's
`squash_merge_commit_message` setting as `BLANK` so repeated PR-body commit
lines do not become duplicate changelog entries.

## Trusted publisher setup

An operator must configure both services before the first publish:

1. In GitHub repository settings, create an environment named `pypi`.
   Environment protection rules or required reviewers may be added if desired.
2. On PyPI, configure a trusted publisher for project `bunnify` with:
   - Owner: `the-hcma`
   - Repository: `bunnify`
   - Workflow: `release-please.yml`
   - Environment: `pypi`
3. If the PyPI project does not exist yet, create a pending trusted publisher
   from the PyPI account's publishing settings.

No PyPI API token or repository secret is needed. The workflow's `id-token:
write` permission and the protected `pypi` environment provide the short-lived
publishing credential.

## Install a published release

Use `pipx` for an isolated application install:

```bash
pipx install bunnify
bunnify --version
bunnify-server --help
```

To move to a newer PyPI release, prefer:

```bash
bunnify upgrade
```

That prints the version/commit you are running from and the pipx app you
upgraded to. Bare `pipx upgrade bunnify` also works but does not compare builds.

For runtime configuration and server setup, see
[Configuration](CONFIG.md) and [Local and remote setup](LOCAL.md).
