# FINANO 产品仓库工作区

## 和 `finano-pitch-deck` 的分工

| 文件夹 | 用途 | push 后 CI |
|--------|------|------------|
| **本仓库** `finano-repo` | 产品：frontend、backend、Docker | 改了代码 → **deploy-app**（慢，含 pip/Docker） |
| 上级 **`finano-pitch-deck`** | 路演 HTML | 用 `push-pitch.ps1` → 只 **deploy-pitch-deck**（快） |

## 在本仓库提交（产品）

```powershell
cd "d:\HKUST学习资料\Meeeee\商业书\finano-repo"
git add .
git commit -m "Fix MAFB pipeline"
git push origin main
```

- 只改 `pitch-deck/**` → 自动走快速部署（约 1–2 分钟）
- 改了 `frontend/`、`backend/` 等 → 全量 Docker 部署（慢，日志里的 pip 安装属于这类）

## 路演 PPT 请去另一个文件夹

不要在本仓库根目录改 `index.html`。请到：

`d:\HKUST学习资料\Meeeee\商业书\finano-pitch-deck`

改完后运行 `.\push-pitch.ps1`。

## VPS 重启后自动恢复（8081 产品 + 8082 路演）

在服务器**执行一次**：

```bash
cd /opt/finano && git pull origin main && bash scripts/install-vps-boot-all.sh
```

诊断：`bash scripts/diagnose-vps.sh`
