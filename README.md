# Kars EV Ultimate V1.0 (Beta)
### Powered by HentaiP feat. ClawMoew

[English](README.md) | [繁體中文](README_ZH.md)

EV-service deployment tooling. Cross-platform launchers, Compose preparation, per-install credentials. Bring your own service assets.

## 🚀 Key Features
- **Cross-Platform**: Support for Linux, macOS, and Windows.
- **Infrastructure Auto-Correction**: Structured YAML parsing, duplicate-key checks, and targeted path re-mapping.
- **Physical Shield**: Explicit bind sources and checks that prevent accidental directory creation for file mounts.
- **Self-Healing**: Checks an existing Docker/Compose environment; does not install or start Docker.
- **Hot-Injection**: Generates a read-only SSO-disable patch mount for the designated gateway.
- **Security Hardening**: Random JWT, database/API credentials and RSA keys for new installs; reruns reuse credentials rather than rotating them.
- **ARM64 Environment Check**: ARM64 environment check for ARM devices.

## 📂 Structure
```text
Kars_EV_Ultimate/
├── run_linux.sh          # Linux script
├── run_mac.sh            # macOS script
├── run_windows.bat       # Windows loader
├── run_windows.ps1       # Windows core logic
├── kars.py               # Deployment core (Python)
├── requirements.txt      # Python dependencies
├── docker_compose_files/ # Sanitized YAMLs - [Excluded from Git/GitHub]
├── docker_img_files/     # Portable Docker images (tar) - [Excluded from Git/GitHub]
├── patch_core/           # Hot-patches - [Excluded from Git/GitHub]
└── extra/                # Utilities
    ├── cleanup_all.sh      # Environment purge
    ├── legacy_backup.sh    # Data extractor
    ├── migrate_restore.sh  # Data restorer
    └── setup_box64_arm64.sh # Box64 environment check
```

## 🛠️ Quick Start

### Windows
- Install Python 3.10+ and Docker Desktop with Compose v2; start Docker first.
- In PowerShell: `py -3 -m venv .venv`, then `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
- Run `.\.venv\Scripts\python.exe kars.py check`, then use `deploy`; alternatively set `KARS_PYTHON` to that interpreter before using the launcher.

### macOS / Linux
- **Notice**: Ensure the project directory path contains **ONLY English characters** to prevent mount failures.
- Requires Python 3.10+, Docker and Compose v2. Create a virtual environment first:
```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```
- macOS Terminal: `chmod +x run_mac.sh && ./run_mac.sh`
- Linux Terminal: `chmod +x run_linux.sh && ./run_linux.sh`

### 🚩 Security Reminder
- Upon successful login, **immediately change the default administrator password** to secure your instance.

### Arm64 Linux (Canary)
- Terminal: `./extra/setup_box64_arm64.sh`
- Follow standard Linux procedure.

## Scope and validation

- Supply legally obtained Compose templates and images matching the expected layout; an empty checkout cannot deploy a service.
- `python kars.py check` checks input syntax only; `prepare` writes configuration without starting containers; `deploy` runs Compose.
- Data and credentials default to `~/.kars`. Back them up privately; never commit them.
- Successful Compose startup does not establish application login, readiness, or hardware compatibility. The ARM64 check does not install emulation or guarantee x86 image compatibility.
- `cleanup --yes` stops only recorded Compose projects and retains data, credentials and images; it is not a system-wide purge.
- See [GPLv3](LICENSE) for the automation license. Obtain third-party assets separately under their own terms.

---
**Powered by HentaiP feat. ClawMoew**
