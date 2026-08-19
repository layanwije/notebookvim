# Contributing to NotebookVim

Thank you for considering a contribution. Bug reports, documentation
improvements, feature proposals, and code changes are welcome.

## Before you begin

- Search existing issues and pull requests to avoid duplicates.
- For a substantial feature or behavioral change, open an issue first so the
  approach can be discussed before implementation.
- Never include credentials, tokens, private data, or generated system files
  such as `.DS_Store` in a contribution.
- Report security vulnerabilities privately as described in
  [SECURITY.md](SECURITY.md).

## Development setup

NotebookVim requires Python. Follow the installation requirements in the
[README](README.md), then create an isolated environment and install the local
project:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Install any development or test dependencies declared in `pyproject.toml`
before running the project's checks.

## Making a change

1. Fork the repository and create a short-lived branch from `main`.
2. Keep the change focused and avoid unrelated formatting or refactoring.
3. Add or update tests when behavior changes.
4. Update documentation when user-facing behavior changes.
5. Run the relevant tests and checks locally.
6. Commit the change and open a pull request against `main`.

Useful branch names include:

- `feature/short-description`
- `fix/short-description`
- `docs/short-description`

## Testing

Run the test suite from the repository root:

```bash
python -m pytest
```

Also run any formatting, linting, or type-checking commands configured in
`pyproject.toml`. Pull requests should leave the repository's automated checks
passing.

## Pull requests

A good pull request:

- Explains what changed and why.
- Links any related issue.
- Describes how the change was tested.
- Includes screenshots or terminal output when they clarify a user-facing
  change.
- Contains no secrets, personal data, build artifacts, or editor metadata.

Maintainers may request changes before merging. Review conversations should be
resolved once the concern has been addressed. Pull requests are squash-merged,
so use a clear title that can serve as the final commit message.

By contributing, you agree that your contribution will be licensed under the
repository's existing license.
