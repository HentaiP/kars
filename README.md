# Kars EV Ultimate V1.0 (Beta)
### Powered by HentaiP feat. ClawMoew

## 🚀 Key Features
- **Cross-Platform**: Support for Linux, macOS, and Windows.
- **Infrastructure Auto-Correction**: YAML sanitization and path re-mapping.
- **Physical Shield**: Conflict resolution for directory/file mount errors.
- **Self-Healing**: Automated environment check and Docker auto-start.
- **Hot-Injection**: Secure patches (SSO Disabled) applied during runtime.
- **Security Hardening**: Automated JWT Secret rotation and RSA Identity key Generation.
- **ARM64 Support**: ARM64 environment check for ARM devices.

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
- Simply **double-click** `run_windows.bat`.

### macOS / Linux
- **Notice**: Ensure the project directory path contains **ONLY English characters** to prevent mount failures.
- Requires Python 3.10+ and Docker Compose v2: `python3 -m pip install -r requirements.txt`
- macOS Terminal: `chmod +x run_mac.sh && ./run_mac.sh`
- Linux Terminal: `chmod +x run_linux.sh && ./run_linux.sh`

### 🚩 Security Reminder
- Upon successful login, **immediately change the default administrator password** to secure your instance.

### Arm64 Linux (Canary)
- Terminal: `./extra/setup_box64_arm64.sh`
- Follow standard Linux procedure.

---
**Powered by HentaiP feat. ClawMoew**
