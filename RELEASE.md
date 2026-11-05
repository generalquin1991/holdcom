# Release checklist — 三通道必须时刻对齐

本工具走三条分发通道，**任何一次发版都必须保证三者指向同一个版本/同一份源码**：

| 通道 | 来源 | 对齐点 |
|---|---|---|
| **pip / PyPI** | `pyproject.toml` `version` + `holdcom.py` `__version__` | 两者必须相等 |
| **bash** | `install.sh` 拉 `main` 分支的 `holdcom.py` | 永远是 `main` 最新；其内置 `--version` 即 `holdcom.py` 的值 |
| **brew** | `Formula/holdcom.rb` 的 `url`(tag) + `sha256` | 必须指向**本次** tag 的 tarball 且哈希正确；公式既在 holdcom 仓库 `Formula/holdcom.rb`，也须同步进公开 tap 仓库 `generalquin1991/homebrew-tap` |

> 铁律：**每次代码改动要发布时，版本号在 `pyproject.toml` 与 `holdcom.py` 同步 +1，打对应 tag，并重算 Formula 的 sha256。** 三者任一落后即视为未对齐。

## 发版步骤（按顺序，一步不能省）

1. **升版本号**（两处必须一致）：
   - `holdcom.py`：`__version__ = "X.Y.Z"`
   - `pyproject.toml`：`version = "X.Y.Z"`
2. **（若改了源码）更新 `Formula/holdcom.rb`**：
   - `url` 的 `vX.Y.Z` → 新 tag
   - `version` → 新版本
   - `sha256` 先复位成 `0000…0000`（占位，步骤 5 回填）
3. **提交版本改动**：`git commit -m "bump vX.Y.Z"` → `git push origin main`
4. **打 tag 并推送**：`git tag vX.Y.Z` → `git push origin vX.Y.Z`
   - tag 必须落在版本号已更新的那个 commit 上
5. **算 tarball 哈希并回填 Formula**：
   ```bash
   HASH=$(curl -fsSL https://github.com/generalquin1991/holdcom/archive/refs/tags/vX.Y.Z.tar.gz | sha256sum | awk '{print $1}')
   # 把 HASH 写进 Formula/holdcom.rb 的 sha256 行
   ```
6. **提交 Formula 哈希**：`git commit -m "dist: fill sha256 for vX.Y.Z"` → `git push origin main`
7. **同步公式到公开 tap 仓库**：把 `Formula/holdcom.rb` 复制到 `generalquin1991/homebrew-tap` 仓库并提交、推送（用户最终走 `brew tap generalquin1991/tap && brew install holdcom`）。
8. **（可选）PyPI**：`python -m build` → `python -m twine upload dist/*`
9. **本机同步裸命令**：`python3 -m pip install --user .`（或 `-e .` 开发模式）
10. **brew 通道校验**：`brew tap generalquin1991/tap` → `brew trust generalquin1991/tap`（brew 4.x 第三方 tap 必须信任，否则 `sandbox_apply` 报错）→ `brew install holdcom` → 确认 `holdcom --version`

## 校验（发版后跑一遍）

```bash
holdcom --version          # 应等于 X.Y.Z
ruby -c Formula/holdcom.rb # 语法 OK
holdcom selftest           # 静态扫描 + pty 回环通过
# bash 通道：装出的 holdcom --version 也应等于 X.Y.Z（因拉 main）
```

## 当前版本

- `0.1.3` — 最新（见 `git tag` 与两处版本号）
