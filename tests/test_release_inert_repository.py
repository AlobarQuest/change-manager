"""The inert-repository release generator, run only against a COPY of this repository.

`scripts/release_inert_repository.py` edits the policy modules in place, so every test here runs
it inside a temporary copy of the tree and asserts the real tree's bytes are untouched. The
property that matters is the self-check: a generation that alters anything but the one repository
is refused and every file put back, which the fault tests show for each of its four conditions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = Path("scripts") / "release_inert_repository.py"
TOUCHED = (
    Path("app") / "deploy_policy.py",
    Path("app") / "deploy_policy_history.py",
    Path("contracts") / "ratified_rollout_policy.json",
)
# Never a real fork: the tests assume no version admits it. The worktree probe uses another name.
PROBE = "alobarquest/release-generator-test-fork"
COPIED = ("app", "contracts", "scripts", "tests", "alembic", ".github")
COPIED_FILES = ("pyproject.toml", "alembic.ini", "Dockerfile", "entrypoint.sh", ".python-version")


def _digests(root: Path) -> dict[Path, str]:
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in TOUCHED}


@pytest.fixture(scope="module")
def real_tree_before() -> dict[Path, str]:
    return _digests(REPO)


@pytest.fixture()
def copy(tmp_path: Path, real_tree_before: dict[Path, str]):
    root = tmp_path / "repo"
    root.mkdir()
    ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache")
    for name in COPIED:
        shutil.copytree(REPO / name, root / name, ignore=ignore)
    for name in COPIED_FILES:
        if (REPO / name).exists():
            shutil.copy2(REPO / name, root / name)
    yield root
    assert _digests(REPO) == real_tree_before, "a test modified the real tree"


def _env(tmp: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("RELEASE_INERT_FAULT", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(tmp / "pycache")
    env.update(extra)
    return env


def release(root: Path, repository: str = PROBE, reason: str = "probe", **env: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repository", repository, "--reason", reason],
        cwd=root,
        env=_env(root.parent, **env),
        capture_output=True,
        text=True,
    )


def _in_force(root: Path) -> tuple[int, list[str]]:
    """The copy's current version and inert population, read the way the script reads them: in a
    subprocess rooted at the copy, so the editable install cannot answer for the real tree."""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from app.deploy_policy import CURRENT_VERSION, current; "
            "print(json.dumps([CURRENT_VERSION, sorted(current().inert_landing.repositories)]))",
        ],
        cwd=root,
        env=_env(root.parent),
        capture_output=True,
        text=True,
        check=True,
    )
    version, inert = json.loads(done.stdout)
    assert PROBE not in inert, f"{PROBE} has been admitted; choose another name for these tests"
    return version, inert


def _bytes(root: Path) -> dict[Path, bytes]:
    return {path: (root / path).read_bytes() for path in TOUCHED}


def test_a_release_adds_one_repository_and_the_released_tree_passes_its_gates(copy: Path):
    n, _ = _in_force(copy)
    done = release(
        copy,
        repository=PROBE.upper(),  # lower-cased by the script
        reason="The operator's fork of `upstream/probe`, a tool for the operator's machine",
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == f"{n + 1} {PROBE}\n"

    contract = json.loads((copy / TOUCHED[2]).read_text(encoding="utf-8"))
    assert contract["policy_version"] == n + 1
    policy = (copy / TOUCHED[0]).read_text(encoding="utf-8")
    assert f"CURRENT_VERSION: Final = {n + 1}\n" in policy
    assert f'            "{PROBE}",\n' in policy
    history = (copy / TOUCHED[1]).read_text(encoding="utf-8")
    assert f"_V{n}_INERT: Final = InertLanding(" in history
    assert f"        V{n},\n        V{n + 1},\n    )\n}}" in history

    # The released tree's own gates: lint, format, and the whole suite but this module (which
    # would recurse). The generic per-release tests in test_deploy_policy cover version N+1.
    ruff = Path(sys.executable).parent / "ruff"
    for args in (["check", "."], ["format", "--check", "."]):
        lint = subprocess.run([str(ruff), *args], cwd=copy, capture_output=True, text=True)
        assert lint.returncode == 0, lint.stdout + lint.stderr
    suite = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-rA",
            "-p",
            "no:cacheprovider",
            "--ignore=tests/test_release_inert_repository.py",
        ],
        cwd=copy,
        # The interpreter's own bytecode cache: the copy is fresh, so it holds no stale `.pyc`,
        # and a private cache prefix would recompile every dependency (about 20 seconds).
        env={k: v for k, v in os.environ.items() if k != "RELEASE_INERT_FAULT"},
        capture_output=True,
        text=True,
    )
    assert suite.returncode == 0, suite.stdout[-4000:] + suite.stderr[-2000:]
    assert re.search(r"\b\d+ passed\b", suite.stdout), suite.stdout[-2000:]
    # The generic per-release test actually ran over the generated version.
    assert f"test_every_inert_only_release_adds_repositories_and_moves_nothing_else[{n + 1}]" in (
        suite.stdout
    )


def test_a_second_release_builds_on_the_first(copy: Path):
    n, _ = _in_force(copy)
    assert release(copy).returncode == 0
    done = release(copy, repository=PROBE + "-2")
    assert done.returncode == 0, done.stderr
    assert done.stdout == f"{n + 2} {PROBE}-2\n"


def test_a_repository_already_present_returns_two_and_changes_nothing(copy: Path):
    _, inert = _in_force(copy)
    before = _bytes(copy)
    done = release(copy, repository=inert[0].upper())
    assert done.returncode == 2, done.stderr
    assert done.stdout == ""
    assert _bytes(copy) == before


@pytest.mark.parametrize(
    "repository",
    ["no-slash", "alobarquest/", "/name", "a/b/c", "alobar quest/x", "alobarquest/x!", "ö/x"],
)
def test_an_invalid_name_returns_one_and_changes_nothing(copy: Path, repository: str):
    before = _bytes(copy)
    done = release(copy, repository=repository)
    assert done.returncode == 1, done.stderr
    assert done.stdout == ""
    assert _bytes(copy) == before


@pytest.mark.parametrize("reason", ["", "   ", 'a "quoted" reason', "back\\slash"])
def test_an_unusable_reason_returns_one_and_changes_nothing(copy: Path, reason: str):
    before = _bytes(copy)
    assert release(copy, reason=reason).returncode == 1
    assert _bytes(copy) == before


def test_a_repository_in_the_deploying_population_is_refused(copy: Path):
    before = _bytes(copy)
    assert release(copy, repository="alobarquest/brain").returncode == 1
    assert _bytes(copy) == before


@pytest.mark.parametrize("args", [["--repository", PROBE], ["--help"]])
def test_a_usage_error_or_help_is_one_not_a_success_code(copy: Path, args: list[str]):
    before = _bytes(copy)
    done = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=copy,
        env=_env(copy.parent),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 1
    assert _bytes(copy) == before


@pytest.mark.parametrize(
    ("fault", "condition"),
    [
        ("alter_older_version", "(a) version 1 no longer projects what it did"),
        ("widen_new_version", "(b) version {new} changes more than the inert population"),
        ("add_second_repository", "(b) version {new}'s inert population is not version {old}'s"),
        ("wrong_decided", "(b) version {new} is not decided"),
        ("unregistered_version", "(d) the registry is"),
        ("unregistered_version", "(b) version {new} is not registered"),
        ("corrupt_contract", "(c) contracts/ratified_rollout_policy.json does not parse"),
        ("stale_contract", "(c) the contract names version {old}, not {new}"),
        ("stale_current_version", "(d) CURRENT_VERSION is {old} and current() is version {new}"),
        ("rebind_criteria", "(b) version {new} changes more than the inert population"),
        ("overlong_line", "(e) ruff check"),
        ("stale_current_function", "(d) CURRENT_VERSION is {new} and current() is version {old}"),
    ],
)
def test_a_corrupted_generation_is_refused_and_every_file_restored(
    copy: Path, fault: str, condition: str
):
    n, _ = _in_force(copy)
    before = _bytes(copy)
    done = release(copy, RELEASE_INERT_FAULT=fault)
    assert done.returncode == 1
    assert done.stdout == ""
    assert condition.format(old=n, new=n + 1) in done.stderr, done.stderr
    assert _bytes(copy) == before
