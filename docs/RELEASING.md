# Releasing Forge

Forge is published to PyPI as **`forge-local-memory`**. Its installed commands remain `forge`, `forge-mcp`, and `forge-antigravity-stop-hook`.

## One-time PyPI setup

1. Create a PyPI account and enable two-factor authentication.
2. In PyPI, add a pending Trusted Publisher with these exact values:
   - Project name: `forge-local-memory`
   - Owner: `jeel1566`
   - Repository: `Forge`
   - Workflow filename: `release.yml`
   - Environment: `pypi`
3. In GitHub repository settings, create an environment named `pypi` and require a maintainer approval.

Forge uses PyPI Trusted Publishing. No PyPI token is stored in the repository, GitHub secrets, Forge database, or local configuration.

## Release checklist

1. Update `pyproject.toml` and `CHANGELOG.md` with the intended version.
2. Run the local checks:

   ```powershell
   python -m unittest discover -s backend/tests -v
   pnpm install --frozen-lockfile
   pnpm --dir frontend run build
   python -m pip install --upgrade build twine pipx
   pyproject-build
   python -m twine check dist/*
   ```

3. Test the built wheel in an isolated `pipx` environment:

   ```powershell
   pipx install --force .\dist\forge_local_memory-<version>-py3-none-any.whl
   forge --help
   forge doctor --path .
   pipx uninstall forge-local-memory
   ```

4. Commit the version and changelog, then create and push an annotated matching tag:

   ```powershell
   git tag -a v<version> -m "Forge <version>"
   git push origin v<version>
   ```

5. GitHub Actions runs the checks, builds both distributions, and waits for the protected `pypi` environment approval. After approval, it publishes the tagged version through Trusted Publishing.
6. Confirm the release with a clean install:

   ```powershell
   pipx install forge-local-memory
   forge --help
   pipx uninstall forge-local-memory
   ```

Never upload a package manually from a developer workstation. `pyproject-build` is used instead of `python -m build` because this repository has a top-level `build` directory. If the workflow fails, fix the source, increment the version, and create a new tag; PyPI release files cannot be replaced.
