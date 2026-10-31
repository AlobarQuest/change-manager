"""The inert-repository release generator, run only against a COPY of this repository.

`scripts/release_inert_repository.py` edits the policy modules in place, so every test here runs
it inside a temporary copy of the tree and asserts the real tree's bytes are untouched. The
property that matters is the self-check: a generation that alters anything but the one repository
is refused and every file put back, which the fault tests show for each of its five conditions.

Copies are kept small: the policy modules, the contract, the scripts and the ruff configuration.
Only the release that is then held to its own gates also copies what `tests/test_deploy_policy.py`
needs, and the refusals that never write share one copy.
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
COPIED = ("app", "contracts", "scripts")
COPIED_FOR_THE_SUITE = ("tests", ".github")
IGNORED = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache")


def _digests(root: Path) -> dict[Path, str]:
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in TOUCHED}


@pytest.fixture(scope="module")
def real_tree_before() -> dict[Path, str]:
    return _digests(REPO)


def _make_copy(root: Path, *extra: str) -> Path:
    root.mkdir()
    for name in (*COPIED, *extra):
        shutil.copytree(REPO / name, root / name, ignore=IGNORED)
    shutil.copy2(REPO / "pyproject.toml", root / "pyproject.toml")
    return root


@pytest.fixture()
def copy(tmp_path: Path, real_tree_before: dict[Path, str]):
    yield _make_copy(tmp_path / "repo")
    assert _digests(REPO) == real_tree_before, "a test modified the real tree"


@pytest.fixture(scope="module")
def shared_copy(tmp_path_factory: pytest.TempPathFactory, real_tree_before: dict[Path, str]):
    """One copy for the refusals that must never write. Each test asserts its own bytes; this
    asserts nothing was left changed for the next one either."""
    root = _make_copy(tmp_path_factory.mktemp("shared") / "repo")
    start = _bytes(root)
    yield root
    assert _bytes(root) == start
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


def _reported(done: subprocess.CompletedProcess[str]) -> dict:
    """The one JSON line on stdout, and nothing else there."""
    lines = done.stdout.splitlines()
    assert len(lines) == 1, done.stdout
    return json.loads(lines[0])


def test_a_release_adds_one_repository_and_the_released_tree_passes_its_gates(tmp_path: Path):
    copy = _make_copy(tmp_path / "repo", *COPIED_FOR_THE_SUITE)
    n, _ = _in_force(copy)
    done = release(
        copy,
        repository=PROBE.upper(),  # lower-cased by the script
        reason="The operator's fork of `upstream/probe`, a tool for the operator's machine",
    )
    assert done.returncode == 0, done.stderr
    assert _reported(done) == {"status": "released", "version": n + 1, "repository": PROBE}

    contract = json.loads((copy / TOUCHED[2]).read_text(encoding="utf-8"))
    assert contract["policy_version"] == n + 1
    policy = (copy / TOUCHED[0]).read_text(encoding="utf-8")
    assert f"CURRENT_VERSION: Final = {n + 1}\n" in policy
    assert f'            "{PROBE}",\n' in policy
    history = (copy / TOUCHED[1]).read_text(encoding="utf-8")
    assert f"_V{n}_INERT: Final = InertLanding(" in history
    assert f"        V{n},\n        V{n + 1},\n    )\n}}" in history
    assert re.match(_same_object(n), _landing_comment(policy, n + 1))

    # The released tree's own gates: lint, format, and the policy suite, whose generic per-release
    # test covers version N+1. The rest of the suite does not read the policy modules.
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
            "tests/test_deploy_policy.py",
        ],
        cwd=copy,
        # The interpreter's own bytecode cache: the copy is fresh, so it holds no stale `.pyc`,
        # and a private cache prefix would recompile every dependency.
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
    assert _reported(done) == {"status": "released", "version": n + 2, "repository": f"{PROBE}-2"}


def _same_object(n: int) -> str:
    """The generated comment's subject: version N's deploying-lane term, which versions before it
    may have declared too (`versions 9 to 13`) or which N introduced (`version 14`)."""
    return rf"The SAME OBJECT (?:versions \d+ to {n}|version {n}) declared"


def _landing_comment(source: str, version: int) -> str:
    """The comment on version `version`'s deploying-lane term, as one line of prose."""
    block = source[source.index(f"V{version}: Final = DeployPolicy(") :]
    found = re.search(r"((?:    # .*\n)+)    landing=_V\d+_LANDING,\n", block)
    assert found is not None
    return " ".join(line.strip()[2:] for line in found[1].splitlines())


def test_the_deploying_lane_comment_is_written_from_the_facts_when_absent(copy: Path):
    """The comment on the deploying-lane term is generated, so a source that lacks it, or words it
    differently, still gets the true statement rather than a silent no-op."""
    n, _ = _in_force(copy)
    module = copy / TOUCHED[0]
    source = module.read_text(encoding="utf-8")
    stripped = re.sub(r"(?:    #.*\n)+(    landing=_V\d+_LANDING,\n)", r"\1", source)
    assert stripped != source
    module.write_text(stripped, encoding="utf-8")

    done = release(copy)
    assert done.returncode == 0, done.stderr
    assert re.fullmatch(
        _same_object(n) + r": this version makes no statement about the deploying lane\.",
        _landing_comment(module.read_text(encoding="utf-8"), n + 1),
    )


def test_a_deploying_lane_term_in_another_shape_is_refused(copy: Path):
    module = copy / TOUCHED[0]
    source = module.read_text(encoding="utf-8")
    n, _ = _in_force(copy)
    current_block = source[source.index(f"V{n}: Final = DeployPolicy(") :]
    old = re.search(r"    landing=(_V\d+_LANDING),\n", current_block)
    assert old is not None
    header = source.index(f"# Version {n} -- the version in force.")
    header = source.rindex("\n# ---", 0, header) + 1
    source = source[:header] + f"DEPLOYING_LANE = {old[1]}\n\n\n" + source[header:]
    source = source.replace(old[0], "    landing=DEPLOYING_LANE,\n", 1)
    module.write_text(source, encoding="utf-8")
    before = _bytes(copy)

    done = release(copy)
    assert done.returncode == 1
    assert done.stdout == ""
    assert "deploying-lane landing term" in done.stderr
    assert _bytes(copy) == before


def test_a_failing_probe_reports_its_cause_first_and_briefly(copy: Path):
    module = copy / TOUCHED[0]
    module.write_text(module.read_text(encoding="utf-8") + "\nraise RuntimeError('boom')\n")
    before = _bytes(copy)
    done = release(copy)
    assert done.returncode == 1
    assert done.stderr.startswith("release refused: RuntimeError: boom"), done.stderr
    assert "[policy probe exited 1]" in done.stderr
    assert "import app.deploy_policy" not in done.stderr  # never the probe's source
    assert len(done.stderr) < 300
    assert _bytes(copy) == before


def test_a_repository_already_present_is_done_and_changes_nothing(shared_copy: Path):
    n, inert = _in_force(shared_copy)
    before = _bytes(shared_copy)
    done = release(shared_copy, repository=inert[0].upper())
    assert done.returncode == 0, done.stderr
    assert _reported(done) == {"status": "already_present", "version": n, "repository": inert[0]}
    assert _bytes(shared_copy) == before


@pytest.mark.parametrize(
    "repository",
    ["no-slash", "alobarquest/", "/name", "a/b/c", "alobar quest/x", "alobarquest/x!", "ö/x"],
)
def test_an_invalid_name_returns_one_and_changes_nothing(shared_copy: Path, repository: str):
    before = _bytes(shared_copy)
    done = release(shared_copy, repository=repository)
    assert done.returncode == 1, done.stderr
    assert done.stdout == ""
    assert _bytes(shared_copy) == before


@pytest.mark.parametrize("reason", ["", "   ", 'a "quoted" reason', "back\\slash"])
def test_an_unusable_reason_returns_one_and_changes_nothing(shared_copy: Path, reason: str):
    before = _bytes(shared_copy)
    assert release(shared_copy, reason=reason).returncode == 1
    assert _bytes(shared_copy) == before


def test_a_repository_in_the_deploying_population_is_refused(shared_copy: Path):
    before = _bytes(shared_copy)
    assert release(shared_copy, repository="alobarquest/brain").returncode == 1
    assert _bytes(shared_copy) == before


@pytest.mark.parametrize("args", [["--repository", PROBE], ["--help"]])
def test_a_usage_error_or_help_is_one_not_a_success_code(shared_copy: Path, args: list[str]):
    before = _bytes(shared_copy)
    done = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=shared_copy,
        env=_env(shared_copy.parent),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 1
    assert done.stdout == ""  # help goes to stderr: stdout is only ever the one JSON line
    assert _bytes(shared_copy) == before


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
        ("reformat_contract", "(c) the contract is not what current() renders"),
        ("stale_current_version", "(d) CURRENT_VERSION is {old} and current() is version {new}"),
        ("rebind_criteria", "(b) version {new} changes more than the inert population"),
        ("rebind_class_remedy", "(b) version {new} changes more than the inert population"),
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
