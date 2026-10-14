#!/usr/bin/env python3
"""Kars deployment preparation; user-supplied assets, no privileged installation.

Powered by HentaiP feat. ClawMoew.
SPDX-License-Identifier: GPL-3.0-only
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid

try:
    import yaml
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    raise SystemExit("Install the requirements in a virtual environment: python -m pip install -r requirements.txt")

BUNDLES = ("kars", "kars-gateway", "kars-core", "kars-connector")
SSO_TARGET = "/internal/api/routes/auth.js"
SSO_PATCH = """'use strict';
const express = require('express');
const router = express.Router();
router.all('/sso', (req, res) => res.status(403).json({
  success: false, message: 'Kars Security: SSO disabled'
}));
module.exports = router;
"""
NGINX = """server {
 listen 80 default_server;
 listen [::]:80 default_server;
 server_name _;
 location / {
  proxy_pass http://kars_frontend_ui:4200/;
  proxy_http_version 1.1;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_set_header Host $host;
 }
 location ~* ^/kars/api/(.*) {
  proxy_pass http://kars-gateway:8580/$1$is_args$args;
  proxy_http_version 1.1;
  proxy_set_header Host $host;
 }
}
"""


class KarsError(Exception):
    pass


class UniqueLoader(yaml.SafeLoader):
    """Compose keys must not silently replace one another (notably volumes)."""


def unique_mapping(loader, node, deep=False):
    # Reject duplicate explicit keys, but permit YAML merge keys/anchors.
    keys = [key.value for key, _ in node.value if key.tag != 'tag:yaml.org,2002:merge']
    if len(keys) != len(set(keys)):
        raise KarsError("Duplicate YAML mapping key")
    loader.flatten_mapping(node)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def checked_run(command, *, env=None, **kwargs):
    result = subprocess.run(command, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        # Native diagnostics may echo rendered secrets. Do not include them.
        raise KarsError(f"{Path(str(command[0])).name} failed (exit {result.returncode}); no success reported")
    return result


def secure_directory(path: Path):
    if path.is_symlink():
        raise KarsError("Managed directory must not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        if path.stat().st_uid != os.geteuid():
            raise KarsError("Data directory is owned by another user; refusing recursive chown")
        path.chmod(0o700)
    elif os.name == "nt":
        # Set a private inheritable ACL. No admin requirement or shell quoting
        # of user paths: the static PowerShell program reads an environment value.
        script = """
$ErrorActionPreference = 'Stop'
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetOwner($sid)
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $env:KARS_ACL_PATH -AclObject $acl
"""
        env = dict(os.environ, KARS_ACL_PATH=str(path))
        checked_run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                     base64.b64encode(script.encode("utf-16le")).decode()], env=env)


def private_write(path: Path, text: str):
    if path.is_symlink():
        raise KarsError("Managed file must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".kars-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def deployment_lock(root: Path):
    secure_directory(root)
    lock = root / ".deployment.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise KarsError("Another deployment holds the lock. If it crashed, verify no run is active before removing .deployment.lock")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def inputs(repo: Path):
    result = {}
    for bundle in BUNDLES:
        folder = repo / "docker_compose_files" / bundle
        path = folder / "docker-compose.yml"
        if not path.exists():
            continue
        if folder.is_symlink() or any(p.is_symlink() for p in folder.rglob("*")):
            raise KarsError("Input directories must contain ordinary files, not symlinks")
        try:
            document = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=UniqueLoader)
        except yaml.YAMLError:
            raise KarsError(f"Invalid YAML in {bundle}/docker-compose.yml (contents withheld)")
        if not isinstance(document, dict) or not isinstance(document.get("services"), dict) or not document["services"]:
            raise KarsError(f"{bundle}: a nonempty services mapping is required")
        if not all(isinstance(name, str) and isinstance(service, dict) for name, service in document["services"].items()):
            raise KarsError(f"{bundle}: invalid service definitions")
        if bundle == "kars-gateway" and "kars-gateway" not in document["services"]:
            raise KarsError("The gateway template must define the kars-gateway service")
        if bundle == "kars-core":
            settings = folder / "appsettings.json"
            if not settings.is_file():
                raise KarsError("kars-core requires appsettings.json")
            try:
                parsed = json.loads(settings.read_text(encoding="utf-8-sig"))
            except ValueError:
                raise KarsError("Invalid appsettings.json (contents withheld)")
            if "BOOTSTRAP_KEY_PLACEHOLDER" not in json.dumps(parsed):
                raise KarsError("appsettings.json must identify its JWT secret with BOOTSTRAP_KEY_PLACEHOLDER")
        result[bundle] = document
    if not result:
        raise KarsError("No Compose inputs. Supply legally obtained templates under docker_compose_files/<bundle>/docker-compose.yml first")
    return result


def credentials(root: Path):
    path = root / "credentials.json"
    if path.is_symlink():
        raise KarsError("credentials.json must not be a symlink")
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, length in (("jwt", 64), ("db", 48), ("api", 48), ("instance", 12)):
                if not re.fullmatch("[a-f0-9]{" + str(length) + "}", data[key]):
                    raise ValueError()
            private = serialization.load_pem_private_key(data["private_pem"].encode(), password=None)
            public = serialization.load_pem_public_key(data["public_pem"].encode())
            if not isinstance(private, rsa.RSAPrivateKey) or private.key_size < 2048 or private.public_key().public_numbers() != public.public_numbers():
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError, UnsupportedAlgorithm):
            raise KarsError("Existing credentials are invalid; restore their backup instead of rotating live database passwords")
        if os.name == "posix":
            path.chmod(0o600)
        return data
    if any(p.name != ".deployment.lock" for p in root.iterdir()):
        raise KarsError("Existing deployment data has no credential record. Migrate existing credentials/data explicitly; refusing to generate incompatible database passwords")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    data = {"jwt": secrets.token_hex(32), "db": secrets.token_hex(24),
            "api": secrets.token_hex(24), "instance": secrets.token_hex(6),
            "private_pem": private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()).decode(),
            "public_pem": private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()}
    private_write(path, json.dumps(data, indent=2) + "\n")
    return data


def replace_values(value, replacements, *, settings=False):
    if isinstance(value, str):
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [replace_values(v, replacements, settings=settings) for v in value]
    if isinstance(value, dict):
        return {k: (60 if settings and str(k).lower() == "expiration" and v == 1440
                    else replace_values(v, replacements, settings=settings)) for k, v in value.items()}
    return value


def compose_path(path: Path) -> str:
    """Absolute Compose bind path; Docker Desktop needs /c/... on Windows."""
    raw = path.absolute()
    if os.name == "nt":
        drive, rest = os.path.splitdrive(str(raw))
        text = "/" + drive[0].lower() + rest.replace("\\", "/") if drive else raw.as_posix()
    else:
        text = raw.as_posix()
    return text.replace("$", "$$")


def private_dir(path: Path):
    if path.is_symlink():
        raise KarsError("Refusing to create a directory through a symlink")
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        path.chmod(0o700)


def volume_parts(volume):
    if isinstance(volume, dict):
        return dict(volume)
    if not isinstance(volume, str):
        raise KarsError("Volume definitions must be strings or mappings")
    match = re.fullmatch(r"(.*):(/[^:]*)(?::([^:]*))?", volume)
    if not match:
        return volume  # anonymous volume: /container/path
    source, target, mode = match.groups()
    if not (source.startswith((".", "/", "~")) or re.match(r"^[A-Za-z]:[/\\]", source)):
        return volume  # named Docker volume
    if mode and mode not in ("ro", "rw"):
        raise KarsError("Use long-form bind mounts for options other than ro/rw")
    return {"type": "bind", "source": source, "target": target, "read_only": mode == "ro"}


def prepare(repo: Path, root: Path, documents: dict, creds: dict):
    """Create a new immutable configuration generation, not a live installation.

    Caller holds deployment_lock. Existing data and earlier configurations stay.
    """
    generation = root / ("config-" + uuid.uuid4().hex)
    private_dir(generation)
    patch = generation / "patch_core/routes/auth_v5.js"
    private_write(patch, SSO_PATCH)
    nginx = generation / "nginx/default.conf"
    private_write(nginx, NGINX)
    user = re.sub(r"[^A-Za-z0-9_]", "", getpass.getuser()) or "kars_user"
    # Escape literal dollars inserted into Compose strings, not user-authored
    # ${VARIABLE} expressions; Compose will restore a literal dollar at runtime.
    replacements = {"DEFAULT_SECURE_PASS_A": creds["db"], "DEFAULT_SECURE_PASS_B": creds["api"],
                    "BOOTSTRAP_KEY_PLACEHOLDER": creds["jwt"], "universal-user": user,
                    "$HOME/.kars": compose_path(root), "${HOME}/.kars": compose_path(root),
                    "~/.kars": compose_path(root), "./patch_core": compose_path(generation / "patch_core")}
    keys = {"AUTH_RSA_PRIVATE": base64.b64encode(creds["private_pem"].encode()).decode(),
            "AUTH_RSA_PUBLIC": base64.b64encode(creds["public_pem"].encode()).decode()}
    manifests, networks = [], set()
    try:
        for bundle, template in documents.items():
            source = repo / "docker_compose_files" / bundle
            destination = generation / bundle
            private_dir(destination)
            for item in source.rglob("*"):
                if item.is_file() and item.name != "docker-compose.yml":
                    target = destination / item.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    shutil.copyfile(item, target)
                    if os.name == "posix":
                        target.chmod(0o600)
            settings = destination / "appsettings.json"
            if bundle == "kars-core":
                data = replace_values(json.loads(settings.read_text(encoding="utf-8-sig")),
                                      {"BOOTSTRAP_KEY_PLACEHOLDER": creds["jwt"]}, settings=True)
                private_write(settings, json.dumps(data, indent=2) + "\n")
            document = replace_values(template, replacements)
            for name, service in document["services"].items():
                environment = service.get("environment", {})
                if isinstance(environment, list):
                    environment = [entry.split("=", 1)[0] + "=" + keys[entry.split("=", 1)[0]]
                                   if isinstance(entry, str) and entry.split("=", 1)[0] in keys else entry
                                   for entry in environment]
                elif isinstance(environment, dict):
                    environment = {k: keys.get(k, v) for k, v in environment.items()}
                else:
                    raise KarsError("Environment must be a mapping or list")
                if "environment" in service:
                    service["environment"] = environment
                volumes = []
                for value in service.get("volumes", []):
                    volume = volume_parts(value)
                    if isinstance(volume, dict) and volume.get("type") == "bind":
                        mount_source = volume.get("source", "")
                        if not isinstance(mount_source, str) or not mount_source:
                            raise KarsError("Bind mounts require an explicit source")
                        if os.name == "nt" and re.match(r"^[A-Za-z]:[/\\]", mount_source):
                            volume["source"] = compose_path(Path(mount_source))
                            mount_source = volume["source"]
                        if mount_source.startswith("./"):
                            relative = Path(mount_source[2:])
                            if ".." in relative.parts:
                                raise KarsError("Relative bind mounts must stay within their bundle")
                            if (source / relative).is_file():
                                resolved = destination / relative
                            else:
                                resolved = root / bundle / relative
                                if resolved.is_symlink() or (resolved.exists() and not resolved.is_dir()):
                                    raise KarsError("Relative directory mount is not an ordinary directory")
                                private_dir(resolved)
                            volume["source"] = compose_path(resolved)
                        elif mount_source.startswith("../"):
                            raise KarsError("Use explicit absolute paths instead of parent-relative bind mounts")
                        redirects = {
                            compose_path(root / "kars-core/appsettings.json"): generation / "kars-core/appsettings.json",
                            compose_path(root / "kars/data/nginx/conf.d"): nginx.parent,
                            compose_path(root / "kars/data/nginx/conf.d/default.conf"): nginx,
                        }
                        if volume["source"] in redirects:
                            volume["source"] = compose_path(redirects[volume["source"]])
                        volume.setdefault("bind", {})["create_host_path"] = False
                    if name == "kars-gateway" and isinstance(volume, dict) and volume.get("target") == SSO_TARGET:
                        continue
                    volumes.append(volume)
                if name == "kars-gateway":
                    volumes.append({"type": "bind", "source": compose_path(patch), "target": SSO_TARGET,
                                    "read_only": True, "bind": {"create_host_path": False}})
                if volumes or "volumes" in service:
                    service["volumes"] = volumes
            rendered = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
            if any(token in rendered for token in ("-REPLACE_ME", "DEFAULT_SECURE_PASS_", "BOOTSTRAP_KEY_PLACEHOLDER")):
                raise KarsError(f"{bundle}: unresolved credential placeholders")
            compose = destination / "docker-compose.yml"
            private_write(compose, rendered)
            for key, network in (document.get("networks") or {}).items():
                if isinstance(network, dict) and network.get("external") is True:
                    netname = network.get("name", key)
                    if not isinstance(netname, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", netname):
                        raise KarsError("External networks need a concrete name, not an interpolated expression")
                    networks.add(netname)
            manifests.append({"bundle": bundle, "project": f"kars-{creds['instance']}-{bundle}",
                              "file": compose.relative_to(root).as_posix(),
                              "sha256": hashlib.sha256(compose.read_bytes()).hexdigest()})
        return {"schema": 1, "instance": creds["instance"], "projects": manifests, "networks": sorted(networks)}
    except Exception:
        shutil.rmtree(generation)
        raise


def docker_command():
    docker = shutil.which("docker")
    if not docker:
        raise KarsError("Install Docker with Compose v2+ yourself before deploying")
    checked_run([docker, "compose", "version"])
    return docker


def compose_command(docker, root, project):
    path = root / project["file"]
    return [docker, "compose", "--project-name", project["project"],
            "--project-directory", str(path.parent), "--file", str(path)]


def validate_configs(docker, root, manifest):
    for project in manifest["projects"]:
        checked_run(compose_command(docker, root, project) + ["config", "--quiet"])


def deploy(docker, repo, root, manifest):
    checked_run([docker, "info"])
    validate_configs(docker, root, manifest)
    # Known persistent directories only; never invent directories for missing
    # file mounts. Docker's create_host_path=false provides the final guard.
    for path in ("kars/data/mysql", "kars/data/mongodb", "kars/data/logs",
                 "kars-core/logs", "kars-gateway/logs", "kars-connector/logs"):
        directory = root / path
        if directory.is_symlink():
            raise KarsError("Persistent data path is a symlink")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for image in sorted((repo / "docker_img_files").glob("*.tar")):
        if image.is_symlink():
            raise KarsError("Image archives must not be symlinks")
        checked_run([docker, "load", "--input", str(image)])
    for network in manifest["networks"]:
        found = subprocess.run([docker, "network", "inspect", network], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if found.returncode:
            checked_run([docker, "network", "create", network])
    # Keep the manifest if a later up fails: cleanup can stop partial deployments.
    private_write(root / "deployment.json", json.dumps(manifest, indent=2) + "\n")
    for project in manifest["projects"]:
        checked_run(compose_command(docker, root, project) + ["up", "-d", "--pull", "never", "--no-build"])


def load_manifest(root):
    path = root / "deployment.json"
    if path.is_symlink() or not path.is_file():
        raise KarsError("No managed deployment manifest")
    try:
        data = json.loads(path.read_text())
        if data["schema"] != 1 or not re.fullmatch(r"[a-f0-9]{12}", data["instance"]):
            raise ValueError()
        for project in data["projects"]:
            relative = Path(project["file"])
            if project["bundle"] not in BUNDLES or project["project"] != f"kars-{data['instance']}-{project['bundle']}":
                raise ValueError()
            if relative.is_absolute() or ".." in relative.parts or not relative.parts[0].startswith("config-"):
                raise ValueError()
            config = root / relative
            if not config.resolve().is_relative_to(root.resolve()) or config.is_symlink():
                raise ValueError()
            if hashlib.sha256(config.read_bytes()).hexdigest() != project["sha256"]:
                raise ValueError()
        return data
    except (ValueError, KeyError, TypeError, IndexError, OSError):
        raise KarsError("Deployment manifest/config was changed or damaged; refusing unscoped cleanup")


def cleanup(docker, root, manifest):
    for project in manifest["projects"]:
        checked_run(compose_command(docker, root, project) + ["down"])
    # No global prune, force removal, image deletion, external-network removal,
    # volume deletion or credential/data deletion.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("check", "prepare", "deploy", "cleanup"), default="deploy")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--data-root", type=Path, default=Path.home() / ".kars")
    parser.add_argument("--yes", action="store_true", help="Confirm stopping this managed deployment only")
    args = parser.parse_args(argv)
    root = args.data_root.expanduser().absolute()
    repo = args.repo.expanduser().resolve()
    try:
        if os.environ.get("SUDO_USER"):
            raise KarsError("Run as the deployment user, not through sudo; Docker access must already be configured")
        if args.action == "cleanup":
            manifest = load_manifest(root)
            if not args.yes:
                raise KarsError("Cleanup stops only the recorded Compose projects. Re-run cleanup --yes to confirm; data/images/shared networks remain")
            with deployment_lock(root):
                cleanup(docker_command(), root, manifest)
            print("Managed Compose projects stopped; data, credentials and images preserved.")
            return 0
        documents = inputs(repo)
        if args.action == "check":
            print(f"Input syntax accepted for {len(documents)} bundle(s); no files or containers changed.")
            return 0
        docker = docker_command() if args.action == "deploy" else None
        if docker:
            checked_run([docker, "info"])
        with deployment_lock(root):
            creds = credentials(root)
            manifest = prepare(repo, root, documents, creds)
            if docker:
                deploy(docker, repo, root, manifest)
            else:
                private_write(root / "prepared.json", json.dumps(manifest, indent=2) + "\n")
        if docker:
            print("Compose up completed for every bundle. Application login, readiness and hardware behavior remain to be verified.")
        else:
            print("Configuration prepared; Docker validation/deployment not performed. Credentials are private and reused on rerun.")
        return 0
    except (KarsError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
