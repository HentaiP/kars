# Kars EV Ultimate V1.0 (Beta)
### Powered by HentaiP feat. ClawMoew

## 🚀 核心特性
- **跨平台支援**：支援 Linux, macOS 與 Windows。
- **自動路徑校正**：YAML 淨化與零信任路徑重新映射。
- **物理護盾**：自動解決目錄/檔案掛載衝突。
- **自癒維運**：基礎設施偵測與 Docker 自動啟動。
- **熱注入補丁**：執行層注入資安補丁（SSO 禁用）。
- **資安旋轉螺旋**：自動化的 JWT 密鑰旋轉與 RSA 身份密鑰生成。
- **ARM64 支援**：提供 ARM 設備的環境檢查。

## 📂 專案結構
```text
Kars_EV_Ultimate/
├── run_linux.sh          # Linux 啟動腳本
├── run_mac.sh            # macOS 啟動腳本
├── run_windows.bat       # Windows 載入器
├── run_windows.ps1       # Windows 核心邏輯
├── kars.py               # 部署核心（Python）
├── requirements.txt      # Python 依賴
├── docker_compose_files/ # 淨化後的 YAML 定義 - [Excluded from Git/GitHub]
├── docker_img_files/     # Docker 映像檔資產 (tar) - [Excluded from Git/GitHub]
├── patch_core/           # 全域熱補丁 - [Excluded from Git/GitHub]
└── extra/                # 維運工具箱
    ├── cleanup_all.sh      # 環境清理
    ├── legacy_backup.sh    # 資料提取
    ├── migrate_restore.sh  # 資料還原
    └── setup_box64_arm64.sh # Box64 環境檢查
```

## 🛠️ 快速開始

### Windows
- 直接 **雙擊** 執行 `run_windows.bat`。

### macOS / Linux
- **注意**：請確保專案目錄路徑為 **全英文**，以避免掛載失敗。
- 需要 Python 3.10+ 與 Docker Compose v2：`python3 -m pip install -r requirements.txt`
- macOS 終端機：`chmod +x run_mac.sh && ./run_mac.sh`
- Linux 終端機：`chmod +x run_linux.sh && ./run_linux.sh`

### 🚩 安全提醒
- 成功登入 WebUI 後，請務必 **立即修改預設的管理員密碼**，以確保系統安全性。

### Arm64 Linux (Canary)
- 終端機：`./extra/setup_box64_arm64.sh`
- 後續依照標準 Linux 流程執行。

---
**Powered by HentaiP feat. ClawMoew**
