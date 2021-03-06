"""
Nox configuration file for the project.
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import List

import nox

# Nox config
nox.needs_version = ">=2022.1.7"
nox.options.error_on_external_run = True

# GitHub Actions
ON_CI = bool(os.getenv("CI"))

# Global project stuff
PROJECT_ROOT = Path(__file__).parent.resolve()

# Git info
DEFAULT_BRANCH = "main"

# VSCode
VSCODE_DIR = PROJECT_ROOT / ".vscode"
SETTINGS_JSON = VSCODE_DIR / "settings.json"

# Virtual environment stuff
VENV_DIR = PROJECT_ROOT / ".venv"
PYTHON = os.fsdecode(VENV_DIR / "bin" / "python")

# Python to use for non-test sessions
DEFAULT_PYTHON: str = "3.10"

# All supported python versions for copier_pypackage
PYTHON_VERSIONS: List[str] = [
    "3.8",
    "3.9",
    "3.10",
]

# List of seed packages to upgrade to their most
# recent versions in every nox environment
# these aren't strictly required but I've found including them
# solves most installation problems
SEEDS: List[str] = [
    "pip",
    "setuptools",
    "wheel",
]

# "dev" should only be run if no virtual environment found and we're not on CI
# i.e. someone is using nox to set up their local dev environment to
# work on copier_pypackage
if not VENV_DIR.exists() and not ON_CI:
    nox.options.sessions = ["dev"]
else:
    nox.options.sessions = []


@nox.session(python=DEFAULT_PYTHON)
def dev(session: nox.Session) -> None:
    """
    Sets up a python dev environment for the project if one doesn't already exist.

    This session will:
    - Create a python virtualenv for the session
    - Install the `virtualenv` cli tool into this environment
    - Use `virtualenv` to create a global project virtual environment
    - Invoke the python interpreter from the global project environment to install
      the project and all it's development dependencies.
    """
    # Check if dev has been run before
    # this prevents manual running nox -s dev more than once
    # thus potentially corrupting an environment
    if VENV_DIR.exists():
        session.error(
            "There is already a virtual environment deactivate and remove it "
            "before running 'dev' again"
        )

    # Create the project virtual environment using virtualenv
    # installed into this sessions virtual environment
    # confusing but it works!
    session.install("virtualenv")
    session.run("virtualenv", os.fsdecode(VENV_DIR), silent=True)

    # Use the venv's interpreter to install the project along with
    # all it's dev dependencies, this ensure it's installed
    # in the right way
    session.run(
        PYTHON,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
        "setuptools",
        "wheel",
        silent=True,
        external=True,
    )
    session.run(PYTHON, "-m", "pip", "install", "-e", ".[dev]", external=True)

    if bool(shutil.which("code")) or bool(shutil.which("code-insiders")):
        # Only do this is user has VSCode installed
        set_up_vscode(session)


@nox.session(python=False)
def update(session: nox.Session) -> None:
    """
    Updates the dependencies in the virtual environment to their latest versions.

    Note: this is still based on the version specifiers present in setup.cfg.
    """
    session.run(PYTHON, "-m", "pip", "install", "--upgrade", "-e", ".[dev]")


@nox.session(python=DEFAULT_PYTHON)
def release(session: nox.Session) -> None:
    """
    Kicks off the automated release process by creating and pushing a new tag.

    Invokes bump2version with the posarg setting the version.

    Usage:

    $ nox -s release -- [major|minor|patch]
    """
    enforce_branch_no_changes(session)

    parser = argparse.ArgumentParser(description="Release a new semantic version.")
    parser.add_argument(
        "version",
        type=str,
        nargs=1,
        help="The type of semver release to make.",
        choices={"major", "minor", "patch"},
    )
    args: argparse.Namespace = parser.parse_args(args=session.posargs)
    version: str = args.version.pop()

    # If we get here, we should be good to go
    # Let's do a final check for safety
    confirm = input(
        f"You are about to bump the {version!r} version. Are you sure? [y/n]: "
    )

    # Abort on anything other than 'y'
    if confirm.lower().strip() != "y":
        session.error(f"You said no when prompted to bump the {version!r} version.")

    update_seeds(session)

    session.install("bump2version")

    session.log(f"Bumping the {version!r} version")
    session.run("bump2version", version)

    session.log("Pushing the new tag")
    session.run("git", "push", external=True)
    session.run("git", "push", "--tags", external=True)


def set_up_vscode(session: nox.Session) -> None:
    """
    Helper function that will set VSCode's workspace settings
    to use the auto-created virtual environment and enable
    pytest support.

    If called, this function will only do anything if
    there aren't already VSCode workspace settings defined.

    Args:
        session (nox.Session): The enclosing nox session.
    """

    if not VSCODE_DIR.exists():
        session.log("Setting up VSCode Workspace.")
        VSCODE_DIR.mkdir(parents=True)
        SETTINGS_JSON.touch()

        settings = {
            "python.defaultInterpreterPath": PYTHON,
        }

        with open(SETTINGS_JSON, mode="w", encoding="utf-8") as f:
            json.dump(settings, f, sort_keys=True, indent=4)


def update_seeds(session: nox.Session) -> None:
    """
    Helper function to update the core installation seed packages
    to their latest versions in each session.
    Args:
        session (nox.Session): The nox session currently running.
    """

    session.install("--upgrade", *SEEDS)


def has_changes() -> bool:
    """
    Invoke git in a subprocess to check if we have
    any uncommitted changes in the local repo.

    Returns:
        bool: True if uncommitted changes, else False.
    """
    status = (
        subprocess.run(
            "git status --porcelain",
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
        )
        .stdout.decode()
        .strip()
    )
    return len(status) > 0


def get_branch() -> str:
    """
    Invoke git in a subprocess to get the name of
    the current branch.

    Returns:
        str: Name of current branch.
    """
    return (
        subprocess.run(
            "git rev-parse --abbrev-ref HEAD",
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
        )
        .stdout.decode()
        .strip()
    )


def enforce_branch_no_changes(session: nox.Session) -> None:
    """
    Errors out the current session if we're not on
    default branch or if there are uncommitted changes.
    """
    if has_changes():
        session.error("All changes must be committed or removed before release")

    branch = get_branch()

    if branch != DEFAULT_BRANCH:
        session.error(
            f"Must be on {DEFAULT_BRANCH!r} branch. Currently on {branch!r} branch"
        )
