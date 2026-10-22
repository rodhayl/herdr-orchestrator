#!/usr/bin/env python3
"""Install/check exact-version frontend assets for Herdr Orchestrator UI.

No Node/npm runtime is required. Packages are resolved from the npm registry at
an exact version, their registry-provided SRI is verified, and only locked files/prefixes from ui/vendor.lock.json are extracted into .tools/ui/vendor.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import pathlib
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.error
import urllib.request
import re
from typing import Any, List

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_LOCK = ROOT / "ui" / "vendor.lock.json"
DEFAULT_DEST = ROOT / ".tools" / "ui" / "vendor"
STATE_FILE = "vendor-state.json"
MAX_PACKAGE_BYTES = 25 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
EXACT_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


class VendorError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_lock(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VendorError(f"Unable to read vendor lock: {path}: {exc}") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("packages"), list):
        raise VendorError("Unsupported or malformed vendor lock")

    mappings: list[tuple[str, bool, str]] = []
    for package in data["packages"]:
        if not isinstance(package, dict) or not package.get("name") or not package.get("version"):
            raise VendorError("Each package requires name and exact version")
        if not EXACT_VERSION_RE.fullmatch(str(package["version"])):
            raise VendorError(f"Package {package.get('name')} must use an exact semantic version")
        files = package.get("files", [])
        prefixes = package.get("prefixes", [])
        if not isinstance(files, list) or not isinstance(prefixes, list) or (not files and not prefixes):
            raise VendorError(f"Package {package.get('name')} requires files or prefixes")

        for is_prefix, items in ((False, files), (True, prefixes)):
            for item in items:
                if not isinstance(item, dict):
                    raise VendorError(f"Invalid vendor mapping in {package.get('name')}")
                source = str(item.get("source") or "")
                target = str(item.get("target") or "")
                if not source or not target or source.startswith("/") or target.startswith("/"):
                    raise VendorError(f"Unsafe vendor mapping in {package.get('name')}")
                if ".." in pathlib.PurePosixPath(source).parts or ".." in pathlib.PurePosixPath(target).parts:
                    raise VendorError(f"Unsafe vendor mapping in {package.get('name')}")
                normalized = target.rstrip("/")
                if not normalized or normalized in {".", STATE_FILE}:
                    raise VendorError(f"Reserved or empty vendor target in {package.get('name')}")
                mappings.append((normalized, is_prefix, str(package.get("name"))))

    for index, (target, is_prefix, package_name) in enumerate(mappings):
        for other, other_prefix, other_package in mappings[index + 1:]:
            overlaps = (
                target == other
                or (is_prefix and other.startswith(target + "/"))
                or (other_prefix and target.startswith(other + "/"))
            )
            if overlaps:
                raise VendorError(f"Overlapping vendor targets: {package_name}:{target} and {other_package}:{other}")
    return data


def _npm_metadata_url(name: str, version: str) -> str:
    encoded = urllib.parse.quote(name, safe="")
    return f"https://registry.npmjs.org/{encoded}/{urllib.parse.quote(version, safe='')}"


def _fetch_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "agy-herdr-factory-ui-vendor/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise VendorError(f"HTTP {response.status} fetching package metadata")
            raw = response.read(2 * 1024 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VendorError(f"Unable to fetch npm package metadata: {type(exc).__name__}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VendorError(f"Invalid npm metadata for {url}") from exc
    if not isinstance(value, dict):
        raise VendorError(f"Unexpected npm metadata for {url}")
    return value


def _download(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "agy-herdr-factory-ui-vendor/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise VendorError(f"HTTP {response.status} fetching package")
            chunks = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PACKAGE_BYTES:
                    raise VendorError("Package exceeds size limit")
                chunks.append(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VendorError(f"Unable to download npm package: {type(exc).__name__}") from exc
    return b"".join(chunks)


def verify_sri(data: bytes, integrity: str) -> None:
    candidates = str(integrity or "").split()
    supported = [item for item in candidates if item.startswith("sha512-") or item.startswith("sha256-")]
    if not supported:
        raise VendorError("npm package metadata does not provide a supported integrity hash")
    for item in supported:
        algorithm, encoded = item.split("-", 1)
        try:
            expected = base64.b64decode(encoded, validate=True)
        except Exception:
            continue
        digest = hashlib.new(algorithm, data).digest()
        if digest == expected:
            return
    raise VendorError("npm package integrity verification failed")


def _safe_extract_member(archive: tarfile.TarFile, source: str) -> bytes:
    member_name = "package/" + source.lstrip("/")
    try:
        member = archive.getmember(member_name)
    except KeyError as exc:
        raise VendorError(f"Package file missing: {source}") from exc
    if not member.isfile() or member.size < 0 or member.size > MAX_MEMBER_BYTES:
        raise VendorError(f"Unsafe or oversized package member: {source}")
    handle = archive.extractfile(member)
    if handle is None:
        raise VendorError(f"Unable to extract package member: {source}")
    data = handle.read(MAX_MEMBER_BYTES + 1)
    if len(data) > MAX_MEMBER_BYTES:
        raise VendorError(f"Package member exceeds size limit: {source}")
    return data


def _iter_prefix_members(archive: tarfile.TarFile, source_prefix: str):
    prefix = "package/" + source_prefix.lstrip("/")
    if not prefix.endswith("/"):
        prefix += "/"
    found = False
    for member in archive.getmembers():
        if not member.name.startswith(prefix):
            continue
        if member.isdir():
            continue
        if not member.isfile() or member.size < 0 or member.size > MAX_MEMBER_BYTES:
            raise VendorError(f"Unsafe or oversized package member: {member.name}")
        relative = member.name[len(prefix):]
        if not relative or ".." in pathlib.PurePosixPath(relative).parts:
            raise VendorError(f"Unsafe package path under prefix: {member.name}")
        handle = archive.extractfile(member)
        if handle is None:
            raise VendorError(f"Unable to extract package member: {member.name}")
        data = handle.read(MAX_MEMBER_BYTES + 1)
        if len(data) > MAX_MEMBER_BYTES:
            raise VendorError(f"Package member exceeds size limit: {member.name}")
        found = True
        yield relative, data
    if not found:
        raise VendorError(f"Package prefix missing: {source_prefix}")


def _write_atomic(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def sync(lock_path: pathlib.Path = DEFAULT_LOCK, destination: pathlib.Path = DEFAULT_DEST) -> dict:
    lock = load_lock(lock_path)
    destination = pathlib.Path(destination)
    staging = destination.parent / f".{destination.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    state = {
        "schema_version": 1,
        "lock_sha256": sha256_bytes(canonical_bytes(lock)),
        "packages": [],
        "files": {},
    }

    try:
        for package in lock["packages"]:
            name = str(package["name"])
            version = str(package["version"])
            metadata = _fetch_json(_npm_metadata_url(name, version))
            if str(metadata.get("version")) != version:
                raise VendorError(f"Registry version mismatch for {name}: expected {version}")
            dist = metadata.get("dist") if isinstance(metadata.get("dist"), dict) else {}
            tarball = str(dist.get("tarball") or "")
            integrity = str(dist.get("integrity") or "")
            parsed_tarball = urllib.parse.urlsplit(tarball)
            if (
                parsed_tarball.scheme != "https"
                or parsed_tarball.hostname != "registry.npmjs.org"
                or parsed_tarball.username is not None
                or parsed_tarball.password is not None
                or parsed_tarball.query
                or parsed_tarball.fragment
            ):
                raise VendorError(f"Untrusted npm tarball URL for {name}")
            package_bytes = _download(tarball)
            verify_sri(package_bytes, integrity)

            package_state = {
                "name": name,
                "version": version,
                "integrity": integrity,
                "tarball_sha256": sha256_bytes(package_bytes),
            }
            state["packages"].append(package_state)

            try:
                archive = tarfile.open(fileobj=io.BytesIO(package_bytes), mode="r:gz")
            except tarfile.TarError as exc:
                raise VendorError(f"Invalid npm tarball for {name}") from exc
            with archive:
                for item in package.get("files", []):
                    source = str(item["source"])
                    target = pathlib.PurePosixPath(str(item["target"]))
                    data = _safe_extract_member(archive, source)
                    target_path = staging.joinpath(*target.parts)
                    _write_atomic(target_path, data)
                    state["files"][str(target)] = {
                        "package": name,
                        "version": version,
                        "source": source,
                        "sha256": sha256_bytes(data),
                        "bytes": len(data),
                    }
                for item in package.get("prefixes", []):
                    source_prefix = str(item["source"])
                    target_prefix = pathlib.PurePosixPath(str(item["target"]))
                    for relative, data in _iter_prefix_members(archive, source_prefix):
                        target = target_prefix / pathlib.PurePosixPath(relative)
                        target_path = staging.joinpath(*target.parts)
                        _write_atomic(target_path, data)
                        state["files"][str(target)] = {
                            "package": name,
                            "version": version,
                            "source": source_prefix + relative,
                            "sha256": sha256_bytes(data),
                            "bytes": len(data),
                        }

        _write_atomic(staging / STATE_FILE, json.dumps(state, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        if destination.exists():
            backup = destination.parent / f".{destination.name}.previous"
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(destination, backup)
            try:
                os.replace(staging, destination)
            except Exception:
                os.replace(backup, destination)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            os.replace(staging, destination)
        return state
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def check(lock_path: pathlib.Path = DEFAULT_LOCK, destination: pathlib.Path = DEFAULT_DEST) -> List[str]:
    lock = load_lock(lock_path)
    state = _read_state(destination / STATE_FILE)
    errors: List[str] = []
    expected_lock_hash = sha256_bytes(canonical_bytes(lock))
    if not state:
        return [f"missing {destination / STATE_FILE}"]
    if state.get("lock_sha256") != expected_lock_hash:
        errors.append("vendor lock changed since last sync")

    expected_packages = [(str(item["name"]), str(item["version"])) for item in lock["packages"]]
    state_packages = [
        (str(item.get("name")), str(item.get("version")))
        for item in state.get("packages", []) if isinstance(item, dict)
    ]
    if state_packages != expected_packages:
        errors.append("vendor state package set/version mismatch")

    file_state = state.get("files") if isinstance(state.get("files"), dict) else {}
    expected_explicit = {str(item["target"]) for package in lock["packages"] for item in package.get("files", [])}
    recorded_targets = set(file_state)
    for target in sorted(expected_explicit):
        if target not in recorded_targets:
            errors.append(f"vendor state missing locked asset: {target}")
    for package in lock["packages"]:
        for item in package.get("prefixes", []):
            prefix = str(item["target"]).rstrip("/") + "/"
            if not any(target.startswith(prefix) for target in recorded_targets):
                errors.append(f"vendor state missing locked prefix: {prefix}")

    actual_targets: set[str] = set()
    if destination.is_dir():
        try:
            for path in destination.rglob("*"):
                if path.is_symlink():
                    errors.append(f"unexpected vendor symlink: {path.relative_to(destination)}")
                    continue
                if path.is_file() and path.name != STATE_FILE:
                    actual_targets.add(path.relative_to(destination).as_posix())
        except OSError as exc:
            errors.append(f"unable to enumerate vendor assets: {exc}")
    for target in sorted(actual_targets - recorded_targets):
        errors.append(f"unrecorded vendor asset: {target}")
    for target in sorted(recorded_targets - actual_targets):
        errors.append(f"missing vendor asset: {target}")

    for target, recorded in sorted(file_state.items()):
        if not isinstance(recorded, dict):
            errors.append(f"invalid vendor state entry: {target}")
            continue
        path = destination.joinpath(*pathlib.PurePosixPath(target).parts)
        if not path.is_file() or path.is_symlink():
            continue
        try:
            digest = sha256_bytes(path.read_bytes())
        except OSError as exc:
            errors.append(f"unable to read vendor asset {target}: {exc}")
            continue
        if not recorded.get("sha256") or digest != recorded.get("sha256"):
            errors.append(f"vendor asset hash mismatch: {target}")
    return errors


def _read_state(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage self-hosted Herdr Orchestrator UI frontend assets")
    parser.add_argument("action", choices=("check", "sync", "ensure"), nargs="?", default="check")
    parser.add_argument("--lock", default=str(DEFAULT_LOCK))
    parser.add_argument("--destination", default=str(DEFAULT_DEST))
    args = parser.parse_args(argv)

    lock = pathlib.Path(args.lock).resolve()
    destination = pathlib.Path(args.destination).resolve()
    errors = check(lock, destination)
    if args.action == "check":
        if errors:
            for error in errors:
                print(f"[UI VENDOR] {error}", file=os.sys.stderr)
            return 1
        print("[UI VENDOR] OK")
        return 0
    if args.action == "ensure" and not errors:
        print("[UI VENDOR] OK")
        return 0

    if args.action in {"sync", "ensure"}:
        if errors:
            print("[UI VENDOR] syncing exact-version frontend assets...")
        try:
            state = sync(lock, destination)
        except VendorError as exc:
            print(f"[UI VENDOR] {exc}", file=os.sys.stderr)
            return 1
        print(f"[UI VENDOR] synced {len(state.get('files', {}))} files to {destination}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
