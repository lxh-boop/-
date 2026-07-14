# Git 操作手册

本文以 `D:\stock_daily_app` 为例，说明项目上传、日常开发、分支协作、冲突处理和安全回滚。

## 1. Git 的四个位置

| 位置 | 说明 | 常用命令 |
| --- | --- | --- |
| 工作区 | 本机正在编辑的文件 | `git status`、`git diff` |
| 暂存区 | 准备放入下一次提交的文件 | `git add`、`git diff --cached` |
| 本地仓库 | 已经提交的历史版本 | `git commit`、`git log` |
| 远程仓库 | GitHub 上的共享版本 | `git fetch`、`git pull`、`git push` |

`git add` 不等于上传。只有执行 `git push` 后，提交才会发送到 GitHub。

## 2. 首次配置

```powershell
git config --global user.name "你的 GitHub 用户名"
git config --global user.email "你的邮箱"
git config --global core.autocrlf true
```

检查配置：

```powershell
git config --global --list
```

检查 GitHub SSH 连接：

```powershell
ssh -T git@github.com
```

GitHub CLI 登录主要用于创建 PR、查看 Issue 等操作：

```powershell
gh auth login
gh auth status
```

只通过已经配置好的 SSH 远程执行 `git push` 时，不一定需要登录 GitHub CLI。

## 3. 克隆项目

```powershell
cd D:\
git clone git@github.com:lxh-boop/-.git stock_daily_app
cd D:\stock_daily_app
```

检查当前远程地址：

```powershell
git remote -v
```

修改远程地址：

```powershell
git remote set-url origin git@github.com:你的用户名/你的仓库名.git
```

## 4. 日常开发流程

推荐每次提交都按以下顺序执行：

```powershell
cd D:\stock_daily_app
git status -sb
git diff
git add agent app tests docs
git diff --cached
git commit -m "完善 Agent 运行链路"
git push
```

只提交一个文件：

```powershell
git add agent\executor.py
git commit -m "修复 Agent 完成状态"
git push
```

提交当前项目内的全部新增、修改和删除文件：

```powershell
git add -A
git diff --cached --stat
git commit -m "同步当前项目版本"
git push origin main
```

执行 `git add -A` 前必须先确认 `.gitignore` 正确，并检查 `git status` 中没有数据库、Token、模型或运行日志。

## 5. 拉取远程更新

查看远程变化但不修改工作区：

```powershell
git fetch origin
git log --oneline --graph --decorate --all -20
```

在工作区干净时拉取主分支：

```powershell
git switch main
git pull --ff-only origin main
```

`--ff-only` 可以避免 Git 在不知情时自动创建合并提交。

## 6. 使用功能分支

创建并切换分支：

```powershell
git switch main
git pull --ff-only origin main
git switch -c codex/rag-evaluation
```

提交并首次推送：

```powershell
git add evaluation rag tests
git commit -m "完善 RAG 评测"
git push -u origin codex/rag-evaluation
```

后续在同一分支只需：

```powershell
git push
```

创建草稿 PR：

```powershell
gh pr create --draft --base main --head codex/rag-evaluation --fill
```

查看 PR：

```powershell
gh pr view --web
```

## 7. 查看历史和差异

```powershell
git log --oneline -20
git show HEAD
git diff HEAD~1 HEAD
git diff main...codex/rag-evaluation
git blame agent\executor.py
```

查看某个文件的历史：

```powershell
git log --follow -- app.py
```

## 8. 撤销操作

撤销尚未暂存的单个文件修改：

```powershell
git restore app.py
```

取消暂存，但保留工作区修改：

```powershell
git restore --staged app.py
```

修改最近一次提交说明：

```powershell
git commit --amend -m "新的提交说明"
```

已经推送到共享仓库的错误提交，使用可追溯的反向提交：

```powershell
git revert <commit-id>
git push
```

不要在不理解影响时使用：

```powershell
git reset --hard
git push --force
```

这两个命令可能丢失本地修改或覆盖其他人的远程提交。

## 9. 处理冲突

拉取或合并时发生冲突：

```powershell
git status
```

打开冲突文件，处理 Git 插入的三类标记：七个小于号加 `HEAD`、七个等号、七个大于号加另一分支名。保留正确内容后删除这些标记。

处理完成后：

```powershell
git add 冲突文件
git commit
git push
```

如果希望取消尚未完成的合并：

```powershell
git merge --abort
```

## 10. 标签和版本

创建版本标签：

```powershell
git tag -a v1.0.0 -m "Windows 桌面发布版 v1.0.0"
git push origin v1.0.0
```

查看标签：

```powershell
git tag --list
git show v1.0.0
```

## 11. 本项目禁止上传的内容

本项目的 `.gitignore` 已排除以下本机内容：

```text
local_app_config.json
local_config.json
.env*
data/*
models/*
outputs/*
logs/*
runtime/
build/
dist/
installer_output/
_backup_*/
.streamlit/
```

提交前进行快速检查：

```powershell
git status --short
git diff --cached --stat
git diff --cached --name-only
```

确认暂存区不存在以下内容：

- Tushare Token、LLM API Key、密码和私钥；
- `agent_quant.db` 等真实数据库；
- 本地模型权重和大体积索引；
- 用户持仓、对话记录、运行 Artifact 和日志；
- 安装包、构建目录和临时备份。

如果密钥曾经提交到 Git 历史，单纯删除文件并不能使密钥恢复安全。应立即在服务商后台吊销旧密钥并生成新密钥，再根据需要清理 Git 历史。

## 12. 当前项目完整上传示例

```powershell
cd D:\stock_daily_app
git status -sb
git diff
git add -A
git diff --cached --stat
git commit -m "同步金融 Agent 完整项目"
git push origin main
```

上传后核对：

```powershell
git status -sb
git log --oneline -3
git ls-remote --heads origin main
```

当本地 `main` 与 `origin/main` 指向同一个提交，并且 `git status` 显示工作区干净时，本次上传完成。
