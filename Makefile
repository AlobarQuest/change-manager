# code-standards Makefile (vendored). Edit upstream and `code-standards sync`.
# check: full-repo lint/type/test pass for humans and CI.
#        diff-scoping is the hook's job — this runs everything.
# fix:   run all autofixers (ruff, prettier).
#
# Each tool is guarded with `command -v` so absent tools degrade gracefully.
# A present tool that exits non-zero propagates its failure (real lint errors
# are NOT swallowed — the old &&/|| pattern was replaced with if/then/else/fi).

.PHONY: check fix

check:
	@if command -v ruff >/dev/null 2>&1; then ruff check .; else echo "ruff not installed — skipping ruff check"; fi
	@if command -v ruff >/dev/null 2>&1; then ruff format --check .; else echo "ruff not installed — skipping ruff format check"; fi
	@if command -v pyright >/dev/null 2>&1; then pyright; else echo "pyright not installed — skipping pyright"; fi
	@if command -v eslint >/dev/null 2>&1; then eslint .; else echo "eslint not installed — skipping eslint"; fi
	@if command -v prettier >/dev/null 2>&1; then prettier --check .; else echo "prettier not installed — skipping prettier check"; fi
	@if command -v shellcheck >/dev/null 2>&1; then find . -name '*.sh' -not -path './.git/*' -exec shellcheck {} +; else echo "shellcheck not installed — skipping shellcheck"; fi
	@if command -v pytest >/dev/null 2>&1; then pytest; else echo "pytest not installed — skipping tests"; fi

fix:
	@if command -v ruff >/dev/null 2>&1; then ruff check --fix .; else echo "ruff not installed — skipping ruff fix"; fi
	@if command -v ruff >/dev/null 2>&1; then ruff format .; else echo "ruff not installed — skipping ruff format"; fi
	@if command -v prettier >/dev/null 2>&1; then prettier --write .; else echo "prettier not installed — skipping prettier fix"; fi
