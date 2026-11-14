# 第一次给 Goggles Bridge 提交 PR：本次改动的完整演练

本文为提交前演练。**本轮只准备代码、对比和正文文件，没有向上游创建 issue、PR、评论或 review，也没有请求作者审核。** Draft PR 仍是公开提交，不等于本地草稿。

阅读顺序：先看[改动明细](../CHANGES-0.3.1.zh-CN.md)，再按本文选择范围；决定真正提交时，使用文末准备好的英文正文。这里的 Git 命令按 PowerShell 编写，不需要一次全部执行。

## 1. 先认识这几个名字

| 名称 | 本项目中的含义 |
| --- | --- |
| 上游 / upstream | 作者仓库 `Ammaar-Alam/goggles-bridge`；原来的 `g2-bridge` 地址会重定向 |
| fork / origin | 你的仓库 `zjmdong/g2-bridge-desktop` |
| `main` | 稳定基线。你的 fork 主分支用于跟随上游，不用它堆放开发中的改动 |
| 功能分支 | 保存一个可审查的改动，例如 `codex/pr-windows-gpu-policy` |
| commit | 一次本地记录。`git commit` 本身不把代码发到 GitHub |
| push | 把提交上传到指定远程分支。推到你的 fork 不等于合入作者仓库 |
| issue | 讨论问题、复现条件或方案；不包含一次待合并的 Git 分支 |
| PR / pull request | 请求把 head 分支的改动合入 base 分支，供维护者逐行审查 |
| Draft PR | 已在 GitHub 创建、尚未标记为可正式审查的 PR；不是私有草稿 |

本项目最终要选的是：**base repository = `Ammaar-Alam/goggles-bridge`，base = `main`；head fork = `zjmdong/g2-bridge-desktop`，compare = 准备好的专题分支**。不要把方向选反，也不要误把 PR 发到自己 fork 的 `main`。GitHub 的 fork PR 页面允许分别选择这些字段。[GitHub：从 fork 创建 PR](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-a-pull-request-from-a-fork)

当前交付分支是 `codex/polish-upstream-options-v0.3.1`；之前的集成分支 `codex/upstream-app-performance-v0.3.0` 仍保留。后文 `codex/pr-windows-capture` 是为未来专题 PR 举的例子，不要误以为它已经完成提取或上传。

## 2. 本项目实际要求什么

本次只读核对的上游基线为 `e88bb484f6643e98ed2785698b272a3f8399f0db`。正式提交当天仍应重新读取最新文件，下面不是替维护者制定新规则。

- 每个 PR 保持聚焦，说明问题、改动、验证方法。
- bug 修复应有回归测试；硬件测试单独记录型号、固件和参数。
- commit 与 PR 标题使用 `type(scope): description`。类型和 scope 小写，描述从小写动作动词开始，不加句号。支持 `feat`、`fix`、`perf`、`refactor`、`test`、`chore`；纯文档用 `chore(docs)`。
- 项目约定使用 squash merge，并以 PR 标题作为最终提交标题。
- 日志去掉设备序列号和个人信息；不要把 DJI 私有安装包、反编译厂商代码、个人录像塞进 PR。
- 当前 PR 模板只有 `Changes` 与 `Validation` 两节，应沿用模板，而非贴一长串开发聊天记录。

这些来自上游 [CONTRIBUTING.md](https://github.com/Ammaar-Alam/goggles-bridge/blob/main/CONTRIBUTING.md) 和 [PR 模板](https://github.com/Ammaar-Alam/goggles-bridge/blob/main/.github/pull_request_template.md)。检查时 `.github` 下没有仓库级 `ISSUE_TEMPLATE` 目录；实际创建页面若出现后来新增的模板，应使用当时模板。

合适的标题例子：

```text
fix(app): preserve desktop encoder preferences across source changes
feat(app): manage an owned virtual display during windows streams
perf(capture): add bounded desktop duplication capture on windows
chore(docs): document windows capture validation
```

不建议用 `Update`、`fixed bugs`、`优化了一下` 或把版本号当作性能 PR 的主题。

## 3. 这次先发 issue，还是直接发 PR

**GitHub 没有要求每个 PR 必须先有 issue，上游当前贡献规范也没有这条前置要求。** 小而明确的修复，可以直接提交聚焦的 PR。对本次涉及第三方驱动、定制 FFmpeg 和发行包的较大改动，建议先用一个简短 issue 确认维护者愿意接受的边界。

提交前先看已有讨论，避免两个贡献者同时改同一段代码。本次核查时发现：

- [Draft PR #14](https://github.com/Ammaar-Alam/goggles-bridge/pull/14) 已讨论可选的参考帧、SEI、VBV 和关键帧实验。
- [PR #26](https://github.com/Ammaar-Alam/goggles-bridge/pull/26) 涉及 Windows AMD 编码支持。

这不代表它们已合并，也不意味着本项目应直接采用它们。它们提醒我们：编码选项、默认值、Windows 捕获与测试可能发生交叉。可以在方案说明中提及相关讨论，避免将别人正在验证的猜测写成我们已解决的问题。

本次建议的 issue 内容是：需要独立虚拟屏、不占用主屏；已有 Windows fork 验证；希望保留原 UI 和原有高级选项；询问作者是否接受分阶段贡献。不要把“延迟必须低于 12 ms”或“USB 应当绝对无抖动”写成已经证明的结论。准备好的正文：[issue-proposal.md](drafts/issue-proposal.md)。GitHub issue 可以用于缺陷和功能方案讨论，创建时应先查看潜在重复项。[GitHub：创建 issue](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-an-issue)

## 4. 为什么不直接提交整个 0.3.1 发行分支

当前发行分支同时承载用户可用的程序、驱动打包、原生捕获构建与 fork 发行安排。它适合交付，不等于最小上游 PR。即使标题只写“增加虚拟屏”，GitHub 也会显示该分支相对 base 的**全部差异**。

建议与作者商定后按下面边界准备专题分支：

| 建议顺序 | 主题 | 应当包含 | 不宜顺带包含 |
| --- | --- | --- | --- |
| A | 独立的小修复或可选接口 | 清晰触发条件、最小实现、专属回归测试 | 定制 FFmpeg、驱动、品牌和版本变化 |
| B | 可选的 Windows 捕获性能后端 | 明确 opt-in/默认行为、完整源代码与构建方式、队列/色彩/捕获测试 | 无关安装器重构、未证明的延迟承诺 |
| C | 虚拟屏生命周期 | 驱动所有权、模式、失败回滚、退出清理、尽量少的 UI 控件 | 强制接管其他软件的 VDD、改主屏、自动改系统信任 |
| D | 可选的打包便利功能 | 作者同意后的驱动获取或原生制品流程 | fork 专有更新源和私人发行配置 |

这些不是已经创建的 PR，也不是承诺必须拆成四个。B/C 的依赖应在代码里明确：若 C 必须依赖 B，可等 B 合并后再从最新 `upstream/main` 准备 C；也可先发布 Draft C 说明依赖，但这会增加第一次提交的维护成本。

尤其需要从上游提交范围中单独审视：fork 的 `0.3.x` 版本号、`zjmdong/g2-bridge-desktop` 更新通道、定制 release workflow、个人中文入门说明、旧客户端专有设置迁移。它们对当前安装包有用，未必适合直接进入作者的项目。普通桌面的高级选项恢复主要修复我们 0.3.0 的集成回归；上游本来就有这些选项，不能把它宣传成修复了上游不存在的 bug。

原来三个 0.3.0 提交分别为 `496c164`、`8c5d619`、`2c47182`，已经按性能、功能和发布分层，但前两个仍较大。**不要不看依赖就整体 cherry-pick 到一个“小 PR”里。** 例如视频后端的测试可能依赖新 worker；只复制生产文件而漏掉依赖，并不能形成可运行的贡献。

## 5. 只读预演：先看将要提交什么

以下命令不发帖、不推送代码。其中 `fetch` 只从远程下载内容并更新本地远程跟踪引用；它不会更新作者仓库。

```powershell
Set-Location 'C:\Users\zjmdong\Documents\g2-bridge\work\upstream-app-v030'
git status --short
git branch --show-current
git worktree list
git remote -v
git fetch origin
git fetch upstream
git log --oneline upstream/main..HEAD
git diff --stat upstream/main...HEAD
git diff --name-status upstream/main...HEAD
git diff --check upstream/main...HEAD
git diff upstream/main...HEAD -- goggles_bridge/engine.py
```

怎么读结果：

- `status` 有输出时，先确认是不是本次工作；不要为得到“干净”结果直接丢弃它们。
- `worktree list` 会显示目录与分支。本机同时保留旧客户端和新集成工作树；不要假定可以在任意目录切到 `main`。如果分支已经被另一 worktree 检出，应去那个目录操作。
- `origin` 应指向你的 fork，`upstream` fetch 指向作者仓库。当前 `upstream` push URL 为 `DISABLED`，保留它即可；创建 fork PR 不需要直接推送上游。
- `upstream/main...HEAD` 是从共同基线查看本分支引入的内容，适合预审。实际 GitHub PR 页面仍是提交前最后的差异依据。
- `diff --check` 检查空白问题，不是功能测试，也不能证明没有 bug。

不要用 `gh pr create --dry-run` 冒充“绝对无副作用预演”：GitHub CLI 文档说明这个选项仍可能推送 Git 改动。本轮预演只读取差异和正文，不调用 `create`。[GitHub CLI：gh pr create](https://cli.github.com/manual/gh_pr_create)

## 6. 为一个确定的 PR 创建干净专题工作树

这一节会创建本地分支/目录，但不发帖、不推送。下面名字是**演练用示例**，不是已准备好全部补丁的分支。应先在第 4 节确定本次 PR 的准确范围。

```powershell
# 在现有项目的任意工作树中执行；目录名和分支名必须尚不存在
git fetch upstream
git worktree add -b codex/pr-windows-capture 'C:\Users\zjmdong\Documents\goggles-bridge-pr-capture' upstream/main
Set-Location 'C:\Users\zjmdong\Documents\goggles-bridge-pr-capture'
git status --short
```

新目录从最新作者 `main` 开始，不会把正在用的 0.3.1 安装包回退，也不改变旧客户端工作树。接下来仅移入经审查的代码段和必要测试，逐文件检查依赖；这一步需要按最终范围制作补丁，不能靠上述命令自动完成。不要把 `dist/`、`vendor/`、`work/`、设备录像和用户设置复制进 Git。

同步 fork 主分支可在 GitHub fork 页面使用 **Sync fork → Update branch**；若出现冲突，先检查分叉原因，不要选择强制覆盖来“修好”。同步 fork 与专题分支更新是两件事。[GitHub：同步 fork](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/syncing-a-fork)

## 7. 测试、审查，再形成提交

在专题工作树的最终补丁上重新验证，不把完整发行分支的测试成绩直接算到裁剪后的 PR 上。

```powershell
# 本地安装开发依赖和执行测试，不向 GitHub发帖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
git diff --stat
git diff
```

若该 PR 包含桌面界面，再安装 `requirements-app.txt`，执行它实际包含的界面回归；若包含 Windows 原生后端，还需验证固定输入、捕获/编码预检与有界队列测试。不要为了“测试全绿”关闭原有检查。

验证结果分三类写：

| 类别 | 应写什么 | 不应推导什么 |
| --- | --- | --- |
| 离线单测/界面测试 | 命令、通过/跳过数量、覆盖的失败路径 | 所有显卡/固件一定正常 |
| 本机硬件测试 | GPU、驱动、眼镜型号/固件、来源、分辨率/fps/码率、持续时间 | 静态桌面成绩等于 FPV 游戏成绩 |
| 尚未测量 | macOS 真机回归、光学延迟、眼镜显示时钟等实际缺口 | 用 USB send p95 代替输入到显示的总延迟 |

提交前逐文件暂存，检查后再提交。下面路径只是示例，必须换成这次实际审核过的文件：

```powershell
git add -- goggles_bridge/app/windows/video.py tests/windows/test_video.py
git diff --cached --stat
git diff --cached --check
git diff --cached
git commit -m 'perf(capture): add bounded desktop duplication capture on windows'
```

第一次提交不需要自己重写所有旧历史来凑成一个 commit；上游最终可以 squash。review 期间新增规范的小提交通常更方便维护者查看本轮反馈改了什么。

## 8. 上传到自己的 fork

这是第一个会修改 GitHub 远程仓库的步骤；它仅上传你的专题分支，仍不会创建 PR。

```powershell
# 只有专题分支内容和测试已经完成时执行
git push -u origin codex/pr-windows-capture
```

上传后，在你的 fork 切换到这个分支，核对最新 commit、文件内容和名称。不要 `git push upstream main`，不要为了 PR 把整个发行分支强推到 fork 的 `main`。

## 9. 真正提交 issue：可选，点击后会公开发帖

1. 打开作者仓库的 **Issues**，搜索相似问题及关键词 `virtual display`、`capture`、`NVENC`。
2. 若没有合适的现有讨论，点击 **New issue**。
3. 使用 [issue-proposal.md](drafts/issue-proposal.md) 的题目和正文，结合准备提交的实际范围删改。
4. 在 Preview 中检查格式、链接和证据。不要附未经脱敏的日志；不要写不存在的测试结果。
5. **Submit new issue 会向上游发布内容。** 本轮尚未执行这一步。

英文题目可用：`feat(windows): discuss native capture and virtual display contributions`。issue 的编号发布后才存在；现在不要编一个 `Fixes #123`。PR 如果只涉及部分问题，使用 `Related to #实际编号`，不要提前承诺关闭整个议题。

## 10. 真正创建 Draft PR：字段逐项核对

1. 打开作者仓库 **Pull requests → New pull request → compare across forks**。
2. base repository 选 `Ammaar-Alam/goggles-bridge`，base 选 `main`。
3. head repository 选 `zjmdong/g2-bridge-desktop`，compare 选**已整理的专题分支**。
4. 先看提交数量与 Files changed。若出现旧 Qt UI、大量与主题无关的发行设置或用户文件，返回整理分支；不要寄希望于标题把这些差异隐藏。
5. 填规范标题，正文沿用 `Changes` / `Validation`。可从 [performance-pr.md](drafts/performance-pr.md) 或 [virtual-display-pr.md](drafts/virtual-display-pr.md) 开始；带“待补”的部分必须改成真实结果。
6. 在 Create pull request 按钮右侧选择 **Create draft pull request**。准备好以后再确认发布。

Draft 可以帮助作者先看边界；它不能合并，标记 Ready for review 后才进入正式审核阶段。本轮的 Markdown 草稿没有创建 GitHub Draft。[GitHub：Draft PR](https://docs.github.com/en/pull-requests/reference/pull-requests)

如果页面提供 **Allow edits from maintainers**，它允许上游有权限的人协助改你的 PR 分支。这是你的协作选择，不是提交前置条件；涉及 fork workflows/secrets 时应阅读页面对权限的说明。[GitHub：允许维护者编辑 fork 分支](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/allowing-changes-to-a-pull-request-branch-created-from-a-fork)

想改用 GitHub CLI 时，下面命令**会真实创建上游 Draft PR**，不是演练命令，且要求该专题分支已经 push：

```powershell
# 真实发布操作，本文未执行
gh pr create --repo Ammaar-Alam/goggles-bridge --base main --head zjmdong:codex/pr-windows-capture --draft --title 'perf(capture): add bounded desktop duplication capture on windows' --body-file 'C:\Users\zjmdong\Documents\g2-bridge\work\upstream-app-v030\docs\contributing\drafts\performance-pr.md'
```

`--body-file` 读取文件的实际换行，避免将 `\n` 字符或 PowerShell 转义写进正文。不要用 `--fill` 把几个完整发行提交的日志直接当成精简 PR 描述。

## 11. PR 创建后的正常过程

| GitHub 状态 | 含义与下一步 |
| --- | --- |
| Draft | 仍在准备或等待范围讨论；完成后由你标记 Ready for review |
| Checks queued/running | CI 正在排队/执行；查看具体 job，不要重复推空提交 |
| Awaiting approval | 首次或外部 fork 的 workflow 可能等待维护者批准运行；不等于代码错误 |
| Checks failed | 打开失败步骤，区分功能回归、构建输入缺失和运行环境问题，修复后重新验证 |
| Changes requested | 维护者给了具体修改意见；这是正常协作，不代表贡献被否定 |
| Approved | 审阅认可，但仍可能等待 CI、冲突解决或维护者安排合并 |
| Merged / Closed | Merged 表示已合入；Closed 但未合入表示这次提案已结束，应阅读原因 |

来自 fork 的 workflow 是否需要批准由仓库/组织设置决定；贡献者不能把等待批准写成本地测试失败。[GitHub：批准来自 fork 的 workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks)

收到 review 时，在**同一个专题分支**修改、测试、commit、push，原 PR 会更新，不必为每次修复新开 PR。回复说明改动位置和验证结果；若不同意建议，用代码和数据解释，不要只回复“我这里正常”。超出这次范围的建议可单开后续讨论。[GitHub：处理 PR 反馈](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/incorporating-feedback-in-your-pull-request)

```powershell
# 在专题工作树中，本地修改和验证之后
git add -- '实际修改的文件'
git commit -m 'fix(capture): address reviewed shutdown behavior'
git push origin codex/pr-windows-capture
```

如作者期间更新了 `main`，先 `git fetch upstream`，再按项目习惯将上游变化合入专题分支。第一次贡献可以用普通 merge 避免重写已经 review 的提交：

```powershell
git fetch upstream
git merge upstream/main
# 如果有冲突，逐文件理解后解决、暂存，再完成 merge；重新测试
git push origin codex/pr-windows-capture
```

不要默认使用 `git push --force`。如果作者明确要求 rebase，先保存工作，理解要重写哪些提交；必要的远程更新使用有租约的方式，并与协作者沟通，避免覆盖别人已经推送的反馈修复。

## 12. 合并以后怎么办

上游要求 squash merge，通常由维护者处理。它会把这个 PR 的多个提交整理成上游的一次提交，所以合并后的 SHA 可能不等于你分支上任何一个 SHA；这不表示代码丢了。[GitHub：squash merge](https://docs.github.com/en/pull-requests/reference/pull-request-merges)

确认 GitHub 显示 **Merged** 后，同步 fork `main`，再为下一个专题从新的 `upstream/main` 建分支。不要继续沿用已 squash 的旧专题分支开发新 PR，否则可能再次带入之前的提交历史。

删除分支属于可选整理动作。第一次提交可以先保留本地分支与工作树，确认所有内容都在上游、没有未提交文件、没有依赖它的后续 PR 后，再删除 GitHub 的专题分支和不再需要的 worktree。不要为清理执行 `reset --hard`、`clean -fd` 或递归删除开发目录。[GitHub：合并与删除 head 分支](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-a-pull-request)

## 13. 提交属于我，为什么 Profile 没有贡献记录

**提交作者归属和个人贡献图是两回事。** 本轮核对 0.3.0 提交 `2c47182` 时，GitHub 返回的 `author.login` 和 `committer.login` 都是 `zjmdong`；已有提交已归属于你的账号，不能因为没有绿格就认定邮箱或身份配置错误。

GitHub 的 commit 贡献统计要求提交在非 fork 仓库的默认分支或适用的 `gh-pages` 分支，作者邮箱也必须关联账号。当前代码位于 fork 的开发分支，仅 push 到这里不会增加对应的 commit 贡献；通过 PR 合入上游的默认分支并满足归属条件后，才符合统计要求。创建 fork 本身、向上游提出 PR 又是另外的活动类型，不等于 fork 内每次 commit 都计数。[GitHub：个人贡献统计规则](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference)

后续新提交使用你的 Git 身份及已关联邮箱或 GitHub 提供的 `noreply` 地址。检查身份可用下面的只读命令；命令可能显示个人邮箱，粘贴到公开 issue 前应删去该信息。

```powershell
git config --show-origin --get user.name
git config --show-origin --get user.email
git log -3 --format='%h author=%an <%ae> committer=%cn <%ce>'
```

`git config` 影响未来提交，不会自动改写历史；也不应把同步来的上游作者提交改成自己的。当前身份归属已正确，无须重写历史或为绿格改默认分支。满足规则的记录可能需要最多 24 小时才显示。[GitHub：排查缺失贡献](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/troubleshooting-missing-contributions)

## 14. 本轮演练到哪一步

已完成的是：读取上游贡献规范和模板、检查相关开放 PR、准备本地改动说明与英文提案正文，并说明分支选择、测试、发布及 review 流程。没有伪造 issue 编号或 PR 链接，没有自动点击提交，没有向作者发消息。

下次真正提交前，应确定**第一条 PR 的具体范围**，从上游基线整理成独立可运行的专题分支，在那个准确 diff 上重跑测试，再由你决定发布 Draft。当前用户安装包和完整发行分支会继续保留。
