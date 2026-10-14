"""Synthetic deployment regressions. No vendor assets, network, or live containers."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import kars


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.data = Path(self.tmp.name) / "data"
        gateway = self.repo / "docker_compose_files/kars-gateway"
        core = self.repo / "docker_compose_files/kars-core"
        write(gateway / "docker-compose.yml", """
            services:
              kars-gateway:
                image: example.invalid/kars-gateway:test
                environment:
                  AUTH_RSA_PRIVATE: -REPLACE_ME
                  AUTH_RSA_PUBLIC: -REPLACE_ME
                  API_PASSWORD: DEFAULT_SECURE_PASS_B
                volumes:
                  - ~/.kars/kars/data/nginx/conf.d:/etc/nginx/conf.d:ro
                  - ./local.txt:/opt/local.txt:ro
            networks:
              kars-network:
                external: true
                name: kars-network
            """)
        write(gateway / "local.txt", "ordinary local file\n")
        write(core / "docker-compose.yml", """
            services:
              kars-core:
                image: example.invalid/kars-core:test
                environment:
                  DB_PASSWORD: DEFAULT_SECURE_PASS_A
                volumes:
                  - ~/.kars/kars-core/appsettings.json:/app/appsettings.json:ro
                  - ./data:/var/lib/app
            """)
        write(core / "appsettings.json", '{"Jwt":{"Key":"BOOTSTRAP_KEY_PLACEHOLDER","expiration":1440}}\n')

    def prepare(self):
        documents = kars.inputs(self.repo)
        with kars.deployment_lock(self.data):
            creds = kars.credentials(self.data)
            manifest = kars.prepare(self.repo, self.data, documents, creds)
            kars.private_write(self.data / "prepared.json", json.dumps(manifest, indent=2) + "\n")
        return creds, manifest

    def rendered(self, manifest, bundle):
        project = next(item for item in manifest["projects"] if item["bundle"] == bundle)
        path = self.data / project["file"]
        return path, kars.yaml.safe_load(path.read_text())

    def test_prepare_is_stable_private_and_scoped(self):
        first, manifest = self.prepare()
        gateway_path, gateway = self.rendered(manifest, "kars-gateway")
        _, core = self.rendered(manifest, "kars-core")
        cred_path = self.data / "credentials.json"
        self.assertEqual(stat.S_IMODE(cred_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)
        core_path = self.data / next(item["file"] for item in manifest["projects"] if item["bundle"] == "kars-core")
        rendered = gateway_path.read_text() + core_path.read_text()
        self.assertNotIn("PRIVATE KEY", rendered)
        self.assertNotIn("-REPLACE_ME", rendered)
        self.assertNotIn("DEFAULT_SECURE_PASS_", rendered)
        self.assertNotIn("BOOTSTRAP_KEY_PLACEHOLDER", rendered)
        environment = gateway["services"]["kars-gateway"]["environment"]
        self.assertEqual(environment["API_PASSWORD"], first["api"])
        self.assertNotIn("-REPLACE_ME", environment["AUTH_RSA_PRIVATE"])
        mounts = {item["target"]: item for item in gateway["services"]["kars-gateway"]["volumes"]}
        self.assertTrue(mounts["/internal/api/routes/auth.js"]["read_only"])
        self.assertTrue(Path(mounts["/internal/api/routes/auth.js"]["source"]).is_file())
        self.assertEqual(Path(mounts["/etc/nginx/conf.d"]["source"]), next(self.data.glob("config-*/nginx")))
        self.assertIn("ordinary local file", Path(mounts["/opt/local.txt"]["source"]).read_text())
        core_mounts = {item["target"]: item for item in core["services"]["kars-core"]["volumes"]}
        settings = json.loads(Path(core_mounts["/app/appsettings.json"]["source"]).read_text())
        self.assertEqual(settings["Jwt"]["Key"], first["jwt"])
        self.assertEqual(settings["Jwt"]["expiration"], 60)
        self.assertEqual(core["services"]["kars-core"]["environment"]["DB_PASSWORD"], first["db"])
        self.assertTrue((self.data / "kars-core/data").is_dir())
        self.assertEqual(manifest["networks"], ["kars-network"])
        subprocess.run(["node", "--check", mounts["/internal/api/routes/auth.js"]["source"]], check=True)

        second, again = self.prepare()
        self.assertEqual(second, first)
        self.assertEqual(again["instance"], manifest["instance"])
        self.assertEqual(len(list(self.data.glob("config-*"))), 2)
        config = subprocess.run(
            ["docker", "compose", "--file", str(gateway_path), "config", "--quiet"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(config.returncode, 0, "docker compose config rejected the rendered file")

    def test_parent_mount_rejected(self):
        path = self.repo / "docker_compose_files/kars-gateway/docker-compose.yml"
        path.write_text(path.read_text().replace(
            "./local.txt:/opt/local.txt:ro", "../outside:/outside:ro"))
        documents = kars.inputs(self.repo)
        with self.assertRaisesRegex(kars.KarsError, "parent-relative"):
            with kars.deployment_lock(self.data):
                kars.prepare(self.repo, self.data, documents, kars.credentials(self.data))

    def test_rejects_incomplete_duplicate_symlink_and_existing_data(self):
        with self.assertRaisesRegex(kars.KarsError, "No Compose inputs"):
            kars.inputs(Path(self.tmp.name) / "empty")
        write(self.repo / "docker_compose_files/kars/docker-compose.yml", """
            services:
              a:
                image: example.invalid/a:test
              a:
                image: example.invalid/b:test
            """)
        with self.assertRaisesRegex(kars.KarsError, "Duplicate YAML"):
            kars.inputs(self.repo)
        (self.repo / "docker_compose_files/kars/docker-compose.yml").unlink()
        link = self.repo / "docker_compose_files/kars-gateway/linked.yml"
        link.symlink_to(self.repo / "docker_compose_files/kars-gateway/local.txt")
        with self.assertRaisesRegex(kars.KarsError, "symlinks"):
            kars.inputs(self.repo)
        link.unlink()
        self.data.mkdir()
        (self.data / "existing-database").mkdir()
        with self.assertRaisesRegex(kars.KarsError, "no credential record"):
            with kars.deployment_lock(self.data):
                kars.credentials(self.data)

    def test_cleanup_cannot_escape_recorded_projects(self):
        _, manifest = self.prepare()
        kars.private_write(self.data / "deployment.json", (self.data / "prepared.json").read_text())
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        log = bin_dir / "calls"
        write(bin_dir / "docker", """
            #!/bin/sh
            printf '%s\\n' "$*" >> "$KARS_DOCKER_LOG"
            exit 0
            """)
        (bin_dir / "docker").chmod(0o755)
        env = dict(os.environ, PATH=str(bin_dir), KARS_DOCKER_LOG=str(log))
        with mock.patch.dict(os.environ, {"SUDO_USER": "root"}):
            self.assertEqual(kars.main(["cleanup", "--yes", "--data-root", str(self.data)]), 1)
        self.assertEqual(kars.main(["cleanup", "--data-root", str(self.data)]), 1)
        with mock.patch.dict(os.environ, env):
            self.assertEqual(kars.main(["cleanup", "--yes", "--data-root", str(self.data)]), 0)
        calls = log.read_text()
        self.assertIn(" compose ", f" {calls} ")
        self.assertIn(" down", calls)
        for forbidden in ("rmi", "prune", "network rm", "volume"):
            self.assertNotIn(forbidden, calls)
        self.assertTrue((self.data / "credentials.json").is_file())
        project = manifest["projects"][0]
        config = self.data / project["file"]
        config.write_bytes(config.read_bytes() + b"\n")
        with mock.patch.dict(os.environ, env):
            self.assertEqual(kars.main(["cleanup", "--yes", "--data-root", str(self.data)]), 1)

    def test_deploy_commands_do_not_pull_build_or_open_the_socket(self):
        _, manifest = self.prepare()
        calls = []

        def record(command, **kwargs):
            calls.append(list(map(str, command)))
            class Result:
                returncode = 1 if list(map(str, command))[1:3] == ["network", "inspect"] else 0
                stdout = b""
                stderr = b""
            return Result()

        with mock.patch.object(kars, "checked_run", side_effect=record), \
             mock.patch.object(kars.subprocess, "run", side_effect=record):
            kars.deploy("docker", self.repo, self.data, manifest)
        flat = [" ".join(map(str, command)) for command in calls]
        self.assertTrue(any("compose version" in item or item.endswith(" info") or " info" in item for item in flat))
        ups = [item for item in flat if " up " in item]
        self.assertEqual(len(ups), len(manifest["projects"]))
        self.assertTrue(all("--pull never" in item and "--no-build" in item for item in ups))
        self.assertFalse(any("chmod" in item or "666" in item or "rmi" in item or "prune" in item for item in flat))
        self.assertTrue(any(item.endswith("network create kars-network") or "network create kars-network" in item for item in flat))


class ShellBoundaryTests(unittest.TestCase):
    def test_backup_never_puts_password_on_command_line_and_restore_defaults_to_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            record = root / "record"
            record.mkdir()
            write(bin_dir / "mysqldump", """
                #!/bin/sh
                printf '%s\\n' "$@" > "$RECORD/argv"
                config=""
                for arg in "$@"; do
                    case "$arg" in
                        --defaults-extra-file=*) config="${arg#*=}" ;;
                    esac
                done
                grep -q 'password="SUPERSECRET"' "$config" && echo config_ok > "$RECORD/config_status"
                echo '-- dump'
                """)
            write(bin_dir / "docker", "#!/bin/sh\necho called > \"$RECORD/docker\"\nexit 99\n")
            for program in bin_dir.iterdir():
                program.chmod(0o755)
            legacy = root / "legacy/kars-core"
            write(legacy / "appsettings.json", "{}\n")
            backup_path = str(bin_dir.parent / "mysqldump-only")
            backup_env = dict(os.environ, PATH=backup_path + ":/bin", RECORD=str(record), LEGACY_ROOT=str(root / "legacy"))
            (bin_dir.parent / "mysqldump-only").mkdir()
            os.symlink(bin_dir / "mysqldump", bin_dir.parent / "mysqldump-only/mysqldump")
            completed = subprocess.run(["/usr/bin/bash", str(ROOT / "extra/legacy_backup.sh"), str(root / "backup-template")],
                                       input="SUPERSECRET\n", text=True, env=backup_env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual((record / "config_status").read_text().strip(), "config_ok")
            self.assertNotIn("SUPERSECRET", (record / "argv").read_text())
            self.assertFalse((record / "docker").exists())
            backup = next(root.glob("backup-template.*"))
            self.assertTrue((backup / "backup.complete").is_file())
            self.assertTrue((backup / "v0_appsettings.json").is_file())
            self.assertEqual(stat.S_IMODE((backup / "v0_mysql_dump.sql").stat().st_mode) & 0o077, 0)
            plan_env = dict(backup_env, PATH=str(bin_dir) + ":/bin")
            plan = subprocess.run(["/usr/bin/bash", str(ROOT / "extra/migrate_restore.sh"), str(backup)],
                                  env=plan_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(plan.returncode, 0, plan.stderr)
            self.assertIn("Plan only", plan.stdout)
            self.assertFalse((record / "docker").exists())

    def test_public_entrypoints_and_arm_helper_make_no_changes(self):
        for relative in ("run_linux.sh", "run_mac.sh", "extra/cleanup_all.sh",
                         "extra/legacy_backup.sh", "extra/migrate_restore.sh", "extra/setup_box64_arm64.sh"):
            subprocess.run(["bash", "-n", str(ROOT / relative)], check=True)
        completed = subprocess.run([str(ROOT / "extra/setup_box64_arm64.sh")],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("ARM64", completed.stderr)
        tracked = subprocess.run(["git", "check-ignore", "docker_compose_files/kars/docker-compose.yml"],
                                 cwd=ROOT, stdout=subprocess.PIPE, text=True)
        self.assertEqual(tracked.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
