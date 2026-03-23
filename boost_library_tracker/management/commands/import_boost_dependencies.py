"""
Management command: import_boost_dependencies

Imports Boost dependency data by running boostdep in the boost clone (no file).
Ensures the boost superproject is in the raw dir (clones if needed), builds
boostdep, runs the tag loop, parses boostdep stdout in memory, and updates DB.

Populates BoostDependency only (changelog to be implemented later).
"""

import logging
import re
import subprocess
import sys
from pathlib import Path

from django.core.management.base import BaseCommand

from boost_library_tracker.models import BoostLibrary, BoostVersion
from boost_library_tracker.services import add_boost_dependency
from boost_library_tracker.workspace import get_boost_clone_dir

logger = logging.getLogger(__name__)

BOOST_REPO_URL = "https://github.com/boostorg/boost"
BOOST_TAG_RE = re.compile(r"^boost-([0-9]+)\.([0-9]+)\.0$")
MIN_BOOST_MINOR_VERSION = 15  # Ignore tags with minor version <= 15 (e.g. boost-1.15.0)
DEPS_LINE_RE = re.compile(r"^([^\s]+)\s+->\s+(.*)$")


def _parse_deps_stdout(stdout: str) -> list[tuple[str, list[str]]]:
    """
    Parse boostdep stdout: only "library -> dep1 dep2 ..." lines (no version header).
    Returns [(client_lib, [dep1, dep2, ...]), ...].
    """
    deps_list: list[tuple[str, list[str]]] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = DEPS_LINE_RE.match(line)
        if m:
            client = m.group(1).strip()
            dep_str = m.group(2).strip()
            deps = [d.strip() for d in dep_str.split()] if dep_str else []
            deps_list.append((client, deps))
    return deps_list


def _ensure_clone(clone_dir: Path) -> bool:
    """Clone boostorg/boost into clone_dir if not present. Return True if repo is ready."""
    if clone_dir.exists() and (clone_dir / ".git").exists():
        return True
    clone_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "clone", BOOST_REPO_URL, str(clone_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.exception("Clone failed: %s", e)
        return False


def _fetch_tags(clone_dir: Path) -> bool:
    """Fetch all tags so we can resolve boost-x.x.0. Return True on success."""
    try:
        subprocess.run(
            ["git", "fetch", "--tags"],
            cwd=clone_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.exception("Fetch tags failed: %s", e)
        return False


def _enable_git_long_paths(clone_dir: Path) -> None:
    """Enable long path support in the clone and all submodules (avoids 'Filename too long' on Windows)."""
    try:
        subprocess.run(
            ["git", "config", "core.longpaths", "true"],
            cwd=clone_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "submodule",
                "foreach",
                "--recursive",
                "git",
                "config",
                "core.longpaths",
                "true",
            ],
            cwd=clone_dir,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # Non-fatal; some tags may still fail with long path errors


def _remove_macos_appledouble_files(clone_dir: Path) -> int:
    """
    Delete AppleDouble ``._*`` files anywhere under the clone, including ``.git``.

    macOS / external volumes create ``._filename`` beside real files. That breaks
    Boost.Jam (e.g. ``._detail``) and Git: pack indexes are named ``pack-*.idx``,
    so ``._pack-*.idx`` under ``.git/modules/.../objects/pack/`` is mistaken for an
    index and triggers ``non-monotonic index`` / failed ``git clean``.
    """
    if sys.platform != "darwin":
        return 0
    removed = 0
    for path in clone_dir.rglob("*"):
        try:
            if path.is_file() and path.name.startswith("._"):
                path.unlink()
                removed += 1
        except OSError:
            pass
    if removed:
        logger.info(
            "Removed %s macOS AppleDouble (._*) file(s) under boost clone "
            "(work tree and .git; avoids Jam and git errors on external volumes).",
            removed,
        )
    return removed


def _init_submodules(clone_dir: Path) -> tuple[bool, str]:
    """Run recursive ``git submodule update --init`` so ``tools/build`` (and nested) exist for bootstrap/b2."""
    try:
        proc = subprocess.run(
            ["git", "submodule", "update", "--init", "--recursive"],
            cwd=clone_dir,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err = (
                proc.stderr or proc.stdout or ""
            ).strip() or f"Exit code {proc.returncode}"
            logger.error(
                "Submodule init failed. stdout: %s stderr: %s",
                proc.stdout,
                proc.stderr,
            )
            return False, err
        return True, ""
    except FileNotFoundError as e:
        logger.exception("Submodule init failed: %s", e)
        return False, str(e)


def _get_git_boost_tags(clone_dir: Path) -> list[str]:
    """Return list of git tags matching boost-x.x.0."""
    try:
        result = subprocess.run(
            ["git", "tag"],
            cwd=clone_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [
        t.strip() for t in result.stdout.splitlines() if BOOST_TAG_RE.match(t.strip())
    ]


def _boost_tag_minor_version(tag: str) -> int | None:
    """Return the minor version from a tag like boost-1.84.0, or None if not matched."""
    m = BOOST_TAG_RE.match(tag.strip())
    if not m:
        return None
    return int(m.group(2))


def _get_tags_to_process(clone_dir: Path, version_arg: str | None) -> list[str]:
    """
    Return list of tags to run boostdep for.
    - version_arg empty/None: only tags that exist in git but NOT in BoostVersion (new tags).
    - version_arg "all": all versions in BoostVersion table.
    - version_arg specific (e.g. boost-1.84.0): that tag only.
    """
    if version_arg is not None and version_arg.strip() != "":
        v = version_arg.strip()
        if v.lower() == "all":
            return list(
                BoostVersion.objects.order_by("version")
                .filter(version__regex=r"^boost-\d+\.\d+\.0$")
                .values_list("version", flat=True)
            )
        return [v]

    all_git_tags = _get_git_boost_tags(clone_dir)
    git_tags = set(
        t
        for t in all_git_tags
        if (minor := _boost_tag_minor_version(t)) is not None
        and minor >= MIN_BOOST_MINOR_VERSION
    )
    db_versions = set(BoostVersion.objects.values_list("version", flat=True))
    new_tags = sorted(git_tags - db_versions)
    return new_tags


def _build_boostdep(clone_dir: Path) -> bool:
    """Run bootstrap and b2 tools/boostdep/build in clone_dir. Skip if dist/bin/boostdep exists. Return True on success."""
    boostdep_exe = clone_dir / "dist" / "bin" / "boostdep.exe"
    boostdep_unix = clone_dir / "dist" / "bin" / "boostdep"
    if boostdep_exe.exists() or boostdep_unix.exists():
        return True
    is_win = sys.platform == "win32"
    try:
        if is_win:
            # Run .bat via cmd; cwd ensures bootstrap.bat is run in clone_dir (no path interpolation)
            proc = subprocess.run(
                ["cmd", "/c", "bootstrap.bat"],
                cwd=clone_dir,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                logger.error(
                    "Bootstrap failed (exit %s). stdout: %s stderr: %s",
                    proc.returncode,
                    proc.stdout or "",
                    proc.stderr or "",
                )
                return False
        else:
            boot = subprocess.run(
                ["bash", "bootstrap.sh"],
                cwd=clone_dir,
                capture_output=True,
                text=True,
            )
            if boot.returncode != 0:
                logger.error(
                    "bootstrap.sh failed (exit %s). stdout: %s stderr: %s",
                    boot.returncode,
                    boot.stdout or "",
                    boot.stderr or "",
                )
                return False
        b2_exe = clone_dir / "b2.exe" if is_win else clone_dir / "b2"
        if not b2_exe.exists():
            logger.error(
                "b2 not found at %s (bootstrap may have failed to build it)",
                b2_exe,
            )
            return False
        b2_base = [str(b2_exe), "tools/boostdep/build"]
        proc = subprocess.run(
            b2_base,
            cwd=clone_dir,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 and sys.platform == "darwin":
            proc = subprocess.run(
                b2_base + ["toolset=clang"],
                cwd=clone_dir,
                capture_output=True,
                text=True,
            )
        if proc.returncode != 0:
            logger.error(
                "b2 tools/boostdep/build failed (exit %s). stdout: %s stderr: %s",
                proc.returncode,
                proc.stdout or "",
                proc.stderr or "",
            )
            return False
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.exception("Build boostdep failed: %s", e)
        return False


def _prepare_boost_clone_for_import(clone_dir: Path) -> bool:
    """
    Clone boost if needed, fetch tags, init submodules, build boostdep.
    On Windows, enable long paths in the clone. Returns False on failure (errors logged).
    """
    if not _ensure_clone(clone_dir):
        logger.error("Clone failed.")
        return False
    if sys.platform == "win32":
        _enable_git_long_paths(clone_dir)

    if not _fetch_tags(clone_dir):
        logger.error("Fetch tags failed.")
        return False

    ok, err = _init_submodules(clone_dir)
    if not ok:
        logger.error("Submodule init failed.")
        if err:
            logger.error("%s", err)
        return False
    _remove_macos_appledouble_files(clone_dir)
    if not _build_boostdep(clone_dir):
        logger.error("Build boostdep failed.")
        return False
    return True


def _generate_deps_output(
    clone_dir: Path,
    tags: list[str],
):
    """
    In clone_dir: for each tag in tags, checkout, submodule update, git clean,
    run boostdep and parse stdout in memory. Yields (tag, deps_list).
    """
    if not tags:
        logger.warning("No tags to process")
        return

    boostdep_exe = clone_dir / "dist" / "bin" / "boostdep"
    if sys.platform == "win32":
        boostdep_exe = clone_dir / "dist" / "bin" / "boostdep.exe"

    _remove_macos_appledouble_files(clone_dir)

    for tag in tags:
        try:
            subprocess.run(
                ["git", "checkout", tag, "--force"],
                cwd=clone_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            proc = subprocess.run(
                ["git", "submodule", "update", "--init", "--force"],
                cwd=clone_dir,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0 and sys.platform == "win32":
                # Retry once after enabling long paths in submodules (fixes "Filename too long")
                _enable_git_long_paths(clone_dir)
                proc = subprocess.run(
                    ["git", "submodule", "update", "--init", "--force"],
                    cwd=clone_dir,
                    capture_output=True,
                    text=True,
                )
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(
                    proc.returncode, proc.args, proc.stdout, proc.stderr
                )
            subprocess.run(
                ["git", "clean", "-dff", "-e", "dist"],
                cwd=clone_dir,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            out = (getattr(e, "stdout", None) or "").strip()
            err = (getattr(e, "stderr", None) or "").strip()
            logger.warning(
                "git checkout/update/clean failed for %s: %s%s%s",
                tag,
                e,
                f" stdout={out!r}" if out else "",
                f" stderr={err!r}" if err else "",
            )
            continue

        try:
            proc = subprocess.run(
                [str(boostdep_exe), "--list-dependencies", "--track-sources"],
                cwd=clone_dir,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                logger.warning("boostdep failed for %s (continue)", tag)
                continue
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning("boostdep failed for %s: %s", tag, e)
            continue

        # boostdep stdout has only "library -> dep1 dep2 ..." lines; no version header
        deps_list = _parse_deps_stdout(proc.stdout or "")
        yield tag, deps_list


# boostdep identifier -> DB library name when generic normalization does not match
BOOSTDEP_NAME_TO_DB_NAME: dict[str, str] = {
    "logic": "Tribool",
    "numeric~ublas": "uBLAS",
    "numeric~interval": "Interval",
    "numeric~odeint": "Odeint",
}


def _normalize_boostdep_name_to_db_candidates(name: str) -> list[str]:
    """
    Return candidate DB names for a boostdep identifier (e.g. 'numeric~conversion' -> 'Numeric Conversion').
    Tries exact, override map, then ~ to space+title, then _ to space+title, then _ to -.
    """
    candidates = [name]
    if name in BOOSTDEP_NAME_TO_DB_NAME:
        candidates.append(BOOSTDEP_NAME_TO_DB_NAME[name])
    if "~" in name:
        candidates.append(name.replace("~", " ").title())
    if "_" in name:
        candidates.append(name.replace("_", " ").title())
        candidates.append(name.replace("_", "-"))
    return candidates


def _build_library_cache() -> dict[str, BoostLibrary]:
    """Pre-load all BoostLibrary rows keyed by name for fast lookups in hot loops."""
    return {lib.name: lib for lib in BoostLibrary.objects.all()}


def _library_by_name(
    name: str, cache: dict[str, BoostLibrary] | None = None
) -> BoostLibrary | None:
    """
    Return first BoostLibrary matching boostdep identifier (any repo).
    Tries exact name, override map, then normalizations so boostdep 'numeric~conversion'
    matches DB 'Numeric Conversion', 'min_max' can match 'Min-Max', etc.
    If cache is provided, use it to avoid repeated DB queries; otherwise query the DB.
    """
    seen: set[str] = set()
    for candidate in _normalize_boostdep_name_to_db_candidates(name):
        if candidate in seen:
            continue
        seen.add(candidate)
        if cache is not None:
            if candidate in cache:
                return cache[candidate]
        else:
            lib = BoostLibrary.objects.filter(name=candidate).first()
            if lib is not None:
                return lib
    return None


class Command(BaseCommand):
    """Import Boost dependency data by running boostdep in the boost clone; populates BoostDependency."""

    help = (
        "Import dependency data by running boostdep in the boost clone (no output file). "
        "Clones boost into raw dir if not present, then populates BoostDependency."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--boost-version",
            type=str,
            default=None,
            dest="boost_version",
            help="Empty: process only new tags (in git but not in BoostVersion). "
            "'all': process all versions in BoostVersion. Or a single tag (e.g. boost-1.84.0).",
        )
        parser.add_argument(
            "--clone-dir",
            type=Path,
            default=None,
            help="Directory to clone boost into (default: workspace/raw/boost_library_tracker/boost)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report only; do not write to DB",
        )

    def handle(self, *args, **options):
        version_override = options.get("boost_version")
        dry_run = options.get("dry_run", False)
        clone_dir = options.get("clone_dir") or get_boost_clone_dir()

        if not _prepare_boost_clone_for_import(clone_dir):
            return

        tags_to_process = _get_tags_to_process(clone_dir, version_override)
        if dry_run:
            logger.info("Tags to process: %s", len(tags_to_process))
            return

        if not tags_to_process:
            logger.error("No tags to process. Nothing to import.")
            return

        stats = {
            "dependencies_added": 0,
            "skipped_no_library": 0,
        }

        lib_cache = _build_library_cache()

        for version_tag, deps_list in _generate_deps_output(clone_dir, tags_to_process):
            version_obj, _ = BoostVersion.objects.get_or_create(
                version=version_tag,
                defaults={"version_created_at": None},
            )

            for client_name, dep_names in deps_list:
                client_lib = _library_by_name(client_name, cache=lib_cache)
                if not client_lib:
                    stats["skipped_no_library"] += 1
                    continue
                for dep_name in dep_names:
                    dep_lib = _library_by_name(dep_name, cache=lib_cache)
                    if not dep_lib:
                        stats["skipped_no_library"] += 1
                        continue
                    _, created = add_boost_dependency(client_lib, version_obj, dep_lib)
                    if created:
                        stats["dependencies_added"] += 1

        logger.info(
            "Dependencies added: %s, skipped (no library): %s",
            stats["dependencies_added"],
            stats["skipped_no_library"],
        )
        logger.info("Done.")
