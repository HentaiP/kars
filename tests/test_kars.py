"""Synthetic deployment regressions. No vendor assets, network, or live containers."""
import contextlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
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


BASH = shutil.which("bash")
POSIX = unittest.skipUnless(os.name == "posix", "POSIX permissions, symlinks and shell scripts")

FAKE_DOCKER = """
    #!/bin/sh
    # Stands in for the docker CLI: records every call, starts nothing.
    printf '%s\\n' "$*" >> "$KARS_FAKE/calls"
    case "$*" in
        "load --input "*) echo "Loaded image: demo/app:1" ;;
        "image inspect "*) [ -f "$KARS_FAKE/image-gone" ] && exit 1; echo "sha256:feed" ;;
        "network inspect "*) exit 1 ;;
        *" config --services") printf 'kars-gateway\\nkars-core\\n' ;;
        "ps --all --quiet --no-trunc") [ -f "$KARS_FAKE/mounts" ] && echo c0ffee ;;
        "inspect --format "*) /bin/cat "$KARS_FAKE/mounts" ;;
        *" ps --all --format json") echo '{"Service":"app","State":"running","Status":"Up 1 second"}' ;;
        *" up -d "*) [ -f "$KARS_FAKE/up-fails" ] && { echo "TOP-SECRET-OUTPUT" >&2; exit 7; } ;;
    esac
    exit 0
    """


class Fixture(unittest.TestCase):
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

    def run_main(self, *arguments):
        """main() against this fixture; returns (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = kars.main([*arguments, "--repo", str(self.repo), "--data-root", str(self.data)])
        return code, out.getvalue(), err.getvalue()

    def generations(self):
        return sorted(path.name for path in self.data.glob("config-*"))


@POSIX
class DeploymentTests(Fixture):
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
        if shutil.which("node"):
            subprocess.run(["node", "--check", mounts["/internal/api/routes/auth.js"]["source"]], check=True)

        second, again = self.prepare()
        self.assertEqual(second, first)
        self.assertEqual(again["instance"], manifest["instance"])
        self.assertEqual(len(list(self.data.glob("config-*"))), 2)
        if shutil.which("docker"):
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


class PortableTests(Fixture):
    """No Docker and nothing POSIX-only: these run on every platform."""

    def test_check_names_what_it_found(self):
        (self.repo / "docker_compose_files/kars_core").mkdir()
        before = sorted(self.repo.rglob("*"))
        code, out, _ = self.run_main("check")
        self.assertEqual(code, 0)
        self.assertIn("2 bundle(s): kars-gateway, kars-core", out)
        self.assertIn("Not supplied: kars, kars-connector", out)
        self.assertIn("Ignored, not a Kars bundle name: kars_core", out)
        self.assertEqual(sorted(self.repo.rglob("*")), before)
        self.assertFalse(self.data.exists())

    def test_prepare_reuses_credentials_and_keeps_one_generation(self):
        self.assertEqual(self.run_main("prepare")[0], 0)
        first = (self.data / "credentials.json").read_text(encoding="utf-8")
        kept = self.generations()
        self.assertEqual(len(kept), 1)
        self.assertEqual(self.run_main("prepare")[0], 0)
        self.assertEqual((self.data / "credentials.json").read_text(encoding="utf-8"), first)
        again = self.generations()
        self.assertEqual(len(again), 1)
        self.assertNotEqual(again, kept)
        prepared = json.loads((self.data / "prepared.json").read_text(encoding="utf-8"))
        for project in prepared["projects"]:
            rendered = (self.data / project["file"]).read_text(encoding="utf-8")
            self.assertNotIn("~/.kars", rendered)
            self.assertNotIn("DEFAULT_SECURE_PASS_", rendered)
            document = kars.yaml.safe_load(rendered)
            for service in document["services"].values():
                for volume in service["volumes"]:
                    self.assertFalse(volume["bind"]["create_host_path"])
                    self.assertTrue(kars.host_path(volume["source"], self.data).exists(), volume["source"])

    def test_pruning_spares_referenced_and_foreign_directories(self):
        self.run_main("prepare")
        deployed = self.generations()[0]
        prepared = (self.data / "prepared.json").read_text(encoding="utf-8")
        kars.private_write(self.data / "deployment.json", prepared)
        (self.data / "config-notes").mkdir()
        self.run_main("prepare")
        self.run_main("prepare")
        kept = self.generations()
        self.assertEqual(len(kept), 3)
        self.assertIn(deployed, kept)
        self.assertIn("config-notes", kept)
        # A record that cannot be read protects everything.
        (self.data / "deployment.json").write_text("{", encoding="utf-8")
        self.run_main("prepare")
        self.assertEqual(len(self.generations()), 4)

    def test_lock_excludes_a_second_run_but_not_a_leftover_file(self):
        self.data.mkdir()
        (self.data / ".deployment.lock").write_text("4242", encoding="utf-8")  # left by a killed run
        with kars.deployment_lock(self.data):
            with self.assertRaisesRegex(kars.KarsError, "Another Kars run"):
                with kars.deployment_lock(self.data):
                    pass
        with kars.deployment_lock(self.data):
            pass

    def test_legacy_external_network_is_recognised_and_rewritten(self):
        path = self.repo / "docker_compose_files/kars-core/docker-compose.yml"
        path.write_text(path.read_text(encoding="utf-8") + textwrap.dedent("""
            networks:
              default:
                external:
                  name: mgmt-network
            """), encoding="utf-8")
        self.assertEqual(self.run_main("prepare")[0], 0)
        prepared = json.loads((self.data / "prepared.json").read_text(encoding="utf-8"))
        self.assertEqual(prepared["networks"], ["kars-network", "mgmt-network"])
        core = next(item for item in prepared["projects"] if item["bundle"] == "kars-core")
        document = kars.yaml.safe_load((self.data / core["file"]).read_text(encoding="utf-8"))
        self.assertEqual(document["networks"]["default"], {"external": True, "name": "mgmt-network"})

    def test_compose_ps_output_of_either_shape(self):
        row = {"Service": "app", "State": "running"}
        self.assertEqual(kars.compose_rows(json.dumps([row, row])), [row, row])
        self.assertEqual(kars.compose_rows(json.dumps(row) + "\n" + json.dumps(row) + "\n"), [row, row])
        self.assertEqual(kars.compose_rows(""), [])


@POSIX
class FakeDockerTests(Fixture):
    """main() end to end against a docker stand-in that records its calls."""

    def setUp(self):
        super().setUp()
        self.fake = Path(self.tmp.name) / "fake"
        write(self.fake / "bin/docker", FAKE_DOCKER)
        (self.fake / "bin/docker").chmod(0o755)
        patcher = mock.patch.dict(os.environ, {"PATH": str(self.fake / "bin"), "KARS_FAKE": str(self.fake)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("SUDO_USER", None)

    def calls(self, containing=""):
        log = self.fake / "calls"
        return [line for line in log.read_text().splitlines() if containing in line] if log.exists() else []

    def test_deploy_status_cleanup(self):
        code, out, err = self.run_main("deploy")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls("network create"), ["network create kars-network"])
        self.assertEqual(len(self.calls(" up -d --pull never --no-build")), 2)
        self.assertEqual(len(self.generations()), 1)
        code, out, _ = self.run_main("status")
        self.assertEqual(code, 0)
        self.assertIn("kars-gateway:\n  app: running (Up 1 second)", out)
        self.assertEqual(self.run_main("cleanup", "--yes")[0], 0)
        self.assertEqual(len(self.calls(" down")), 2)
        self.assertFalse(any(word in call for call in self.calls() for word in ("prune", "rmi", "volume rm")))

    def test_only_a_deployment_removes_generations_it_did_not_supersede(self):
        # What an interrupted deployment leaves: a generation no record names,
        # which containers may still be running from.
        self.assertEqual(self.run_main("prepare")[0], 0)
        unrecorded = self.data / ("config-" + "a" * 32)
        unrecorded.mkdir()
        self.assertEqual(self.run_main("prepare")[0], 0)
        self.assertTrue(unrecorded.is_dir())
        self.assertEqual(self.run_main("deploy")[0], 0)
        self.assertFalse(unrecorded.exists())
        self.assertEqual(len(self.generations()), 2)        # deployed, and the last prepared

    def test_generation_a_container_still_mounts_is_kept(self):
        self.assertEqual(self.run_main("deploy")[0], 0)
        first = self.generations()[0]
        # A service dropped from its template: Compose leaves its container running.
        write(self.fake / "mounts", f"/host_mnt{self.data}/{first}/nginx\n")
        self.assertEqual(self.run_main("deploy")[0], 0)
        self.assertIn(first, self.generations())
        self.assertEqual(len(self.generations()), 2)
        (self.fake / "mounts").unlink()
        self.assertEqual(self.run_main("deploy")[0], 0)
        self.assertNotIn(first, self.generations())
        self.assertEqual(len(self.generations()), 1)
        self.assertEqual(self.run_main("cleanup", "--yes")[0], 0)
        self.assertTrue(all(call.endswith(" down --remove-orphans") for call in self.calls(" down")))

    def test_inactive_profile_service_is_not_preflighted(self):
        path = self.repo / "docker_compose_files/kars-core/docker-compose.yml"
        path.write_text(path.read_text() + (
            "  tools:\n"
            "    image: example.invalid/tools:test\n"
            "    profiles: [tools]\n"
            "    volumes:\n"
            "      - ~/.kars/kars-core/absent.pem:/absent.pem\n"))
        self.assertIn("tools", kars.inputs(self.repo)["kars-core"]["services"])
        code, _, err = self.run_main("deploy")       # the stand-in lists kars-gateway and kars-core as active
        self.assertEqual(code, 0, err)

    def test_failed_step_is_named_and_native_output_withheld(self):
        (self.fake / "up-fails").touch()
        code, out, err = self.run_main("deploy")
        self.assertEqual(code, 1)
        self.assertIn("docker compose up (kars-gateway) failed (exit 7)", err)
        self.assertNotIn("TOP-SECRET-OUTPUT", out + err)
        self.assertEqual(len(self.generations()), 1)        # recorded, so kept
        # The partial deployment stays recorded, so cleanup can still reach it.
        self.assertEqual(self.run_main("cleanup", "--yes")[0], 0)

    def test_unchanged_image_archive_is_loaded_once(self):
        archive = self.repo / "docker_img_files/app.tar"
        write(archive, "not really a tar; the stand-in never opens it\n")
        self.assertEqual(self.run_main("deploy")[0], 0)
        self.assertEqual(self.run_main("deploy")[0], 0)
        self.assertEqual(len(self.calls("load --input")), 1)
        os.utime(archive, ns=(1, 1))                       # replaced archive
        self.assertEqual(self.run_main("deploy")[0], 0)
        self.assertEqual(len(self.calls("load --input")), 2)
        (self.fake / "image-gone").touch()                  # image removed behind our back
        self.assertEqual(self.run_main("deploy")[0], 0)
        self.assertEqual(len(self.calls("load --input")), 3)

    def test_missing_bind_source_is_named_before_anything_starts(self):
        path = self.repo / "docker_compose_files/kars-core/docker-compose.yml"
        path.write_text(path.read_text().replace(
            "- ./data:/var/lib/app", "- ~/.kars/kars-core/cert:/app/cert"))
        code, _, err = self.run_main("deploy")
        self.assertEqual(code, 1)
        self.assertIn(f"kars-core: {self.data / 'kars-core/cert'}", err)
        self.assertEqual(self.calls(" up -d"), [])
        self.assertEqual(self.calls("load --input"), [])
        self.assertFalse((self.data / "kars-core/cert").exists())
        self.assertEqual(self.generations(), [])            # nothing ran from it; no stray credentials

    def test_bundle_without_a_template_stays_within_reach_of_cleanup(self):
        self.assertEqual(self.run_main("deploy")[0], 0)
        shutil.rmtree(self.repo / "docker_compose_files/kars-core")
        code, out, err = self.run_main("deploy")
        self.assertEqual(code, 0, err)
        self.assertIn("not restarted (no template now): kars-core", out)
        self.assertEqual(len(self.calls(" up -d")), 3)     # two, then the gateway alone
        self.assertEqual(len(self.generations()), 2)        # the one kars-core still runs from is kept
        (self.fake / "calls").unlink()
        self.assertEqual(self.run_main("cleanup", "--yes")[0], 0)
        self.assertEqual(len(self.calls(" down")), 2)


@POSIX
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
            backup_env = dict(os.environ, PATH=backup_path + ":/usr/bin:/bin", RECORD=str(record), LEGACY_ROOT=str(root / "legacy"))
            (bin_dir.parent / "mysqldump-only").mkdir()
            os.symlink(bin_dir / "mysqldump", bin_dir.parent / "mysqldump-only/mysqldump")
            completed = subprocess.run([BASH, str(ROOT / "extra/legacy_backup.sh"), str(root / "backup-template")],
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
            plan_env = dict(backup_env, PATH=str(bin_dir) + ":/usr/bin:/bin")
            plan = subprocess.run([BASH, str(ROOT / "extra/migrate_restore.sh"), str(backup)],
                                  env=plan_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(plan.returncode, 0, plan.stderr)
            self.assertIn("Plan only", plan.stdout)
            self.assertFalse((record / "docker").exists())

    def test_public_entrypoints_and_arm_helper_make_no_changes(self):
        for relative in ("run_linux.sh", "run_mac.sh", "extra/cleanup_all.sh",
                         "extra/legacy_backup.sh", "extra/migrate_restore.sh", "extra/setup_box64_arm64.sh"):
            subprocess.run(["bash", "-n", str(ROOT / relative)], check=True)
        if platform.machine().lower() not in ("aarch64", "arm64"):
            completed = subprocess.run([str(ROOT / "extra/setup_box64_arm64.sh")],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(completed.returncode, 1)
            self.assertIn("ARM64", completed.stderr)
        tracked = subprocess.run(["git", "check-ignore", "docker_compose_files/kars/docker-compose.yml"],
                                 cwd=ROOT, stdout=subprocess.PIPE, text=True)
        self.assertEqual(tracked.returncode, 0)

    def test_launchers_prefer_the_local_virtual_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "checkout"
            (checkout / "extra").mkdir(parents=True)
            for relative in ("run_linux.sh", "run_mac.sh", "extra/cleanup_all.sh"):
                shutil.copy(ROOT / relative, checkout / relative)
            write(checkout / ".venv/bin/python", "#!/bin/sh\necho \"venv $*\"\n")
            (checkout / ".venv/bin/python").chmod(0o755)
            write(Path(tmp) / "other", "#!/bin/sh\necho \"chosen $*\"\n")
            (Path(tmp) / "other").chmod(0o755)
            for relative, action in (("run_linux.sh", "check"), ("run_mac.sh", "check"), ("extra/cleanup_all.sh", "cleanup")):
                ran = subprocess.run(["bash", str(checkout / relative), "check"], stdout=subprocess.PIPE, text=True,
                                     env={k: v for k, v in os.environ.items() if k != "KARS_PYTHON"})
                self.assertTrue(ran.stdout.startswith("venv "), ran.stdout)
                self.assertIn(action, ran.stdout)
                ran = subprocess.run(["bash", str(checkout / relative)], stdout=subprocess.PIPE, text=True,
                                     env=dict(os.environ, KARS_PYTHON=str(Path(tmp) / "other")))
                self.assertTrue(ran.stdout.startswith("chosen "), ran.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
