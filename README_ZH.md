# Kars EV Ultimate V1.0 (Beta)
### Powered by HentaiP feat. ClawMoew

[English](README.md) | [繁體中文](README_ZH.md)

EV 服務部署工具。跨平台啟動、Compose 設定、每次安裝專用憑證。服務資產需自備。

## 🚀 核心特性
- **跨平台支援**：支援 Linux, macOS 與 Windows。
- **自動路徑校正**：結構化 YAML 解析、重複鍵檢查與指定路徑重新映射。
- **物理護盾**：指定掛載來源，拒絕不合規路徑並避免 Docker 自動建立錯誤目錄。
- **自癒維運**：檢查既有 Docker 與 Compose 環境；不自動安裝或啟動 Docker。
- **熱注入補丁**：為指定 gateway 產生唯讀掛載的 SSO 禁用補丁。
- **資安旋轉螺旋**：新安裝產生隨機 JWT、資料庫/API 憑證及 RSA 金鑰；重跑沿用既有憑證，不自動輪換。
- **ARM64 環境檢查**：提供 ARM 設備的環境檢查。

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
- 先安裝 Python 3.10+、Docker Desktop（含 Compose v2），並啟動 Docker。
- PowerShell：`py -3 -m venv .venv`，再執行 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`。
- 執行 `.\.venv\Scripts\python.exe kars.py check` 檢查輸入，再以 `deploy` 部署；也可將 `KARS_PYTHON` 指向該 Python 後使用啟動器。

### macOS / Linux
- **注意**：請確保專案目錄路徑為 **全英文**，以避免掛載失敗。
- 需要 Python 3.10+、Docker 與 Compose v2。先建立虛擬環境：
```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```
- macOS 終端機：`chmod +x run_mac.sh && ./run_mac.sh`
- Linux 終端機：`chmod +x run_linux.sh && ./run_linux.sh`

### 🚩 安全提醒
- 成功登入 WebUI 後，請務必 **立即修改預設的管理員密碼**，以確保系統安全性。

### Arm64 Linux (Canary)
- 終端機：`./extra/setup_box64_arm64.sh`
- 後續依照標準 Linux 流程執行。

## 使用範圍與驗證

- 請自行提供合法取得、符合程式預期的 Compose 範本與映像；空白 checkout 不能直接部署。
- `python kars.py check` 只檢查輸入語法；`prepare` 寫入設定但不啟動容器；`deploy` 執行 Compose。
- 預設資料與憑證存於 `~/.kars`，請私下備份，不要提交至 Git。
- Compose 啟動成功不代表登入、服務就緒或硬體行為已驗收。ARM64 檢查不提供模擬器，也不保證 x86 映像相容。
- `cleanup --yes` 只停止記錄中的 Compose 專案，保留資料、憑證與映像；不是全機清除工具。
- 授權見 [GPLv3](LICENSE)。第三方資產依其原始授權另行取得。

---
**Powered by HentaiP feat. ClawMoew**
