# Contributor setup

## Run Forge from source

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
pnpm install --frozen-lockfile
pnpm --dir frontend run build
forge start --path .
```

Open `http://127.0.0.1:8000`. The selected repository stores data in `.forge/forge.sqlite3`.

## Validate changes

```powershell
python -m unittest discover -s backend/tests -v
pnpm --dir frontend run build
git diff --check
```

Use `forge.validation.json` for trusted local validation runs. Do not commit `.forge/`, build artifacts, tokens, generated vault content, or unrelated user files.

## Package check

Install `build`, `twine`, and `pipx`, then use `pyproject-build` rather than `python -m build` because this repository has a `build/` directory.

```powershell
python -m pip install --upgrade build twine pipx
pyproject-build
python -m twine check dist/*
```

See [Releasing Forge](RELEASING.md) for the isolated `pipx` lifecycle and Trusted Publishing flow.
