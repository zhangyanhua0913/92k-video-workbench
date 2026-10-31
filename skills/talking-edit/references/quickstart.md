# 首次使用与依赖准备

供Agent帮助新用户准备环境。命令中的SKILL_DIR、PROJECT_DIR和可执行路径均为占位符，换成本机绝对路径；不要照抄其他用户盘符。命令返回JSON，review启动页面，无前端开发服务器。

1. 安装整个skills/talking-edit目录，读取SKILL.md。在Windows检查Python 3.11+，运行 `python SKILL_DIR/scripts/cli.py doctor`。建议Python 3.12为转写创建隔离环境，不在全局Python装模型依赖。
2. 检查FFmpeg/ffprobe，动画另查Node.js/npm。缺少时由Agent在包外目录准备，先说明下载用途，不替换其他软件环境。运行 `python SKILL_DIR/scripts/cli.py configure-runtime --ffmpeg ABS_FFMPEG --ffprobe ABS_FFPROBE [--node ABS_NODE]` 保存位置；doctor读回真实状态。
3. 本地剪切导出依赖固定FredTalk执行层，即使无动态包装也需准备：`python SKILL_DIR/scripts/cli.py prepare-deps fredtalk`。默认在用户目录 `.talking-edit/deps/FredTalk`；网络失败先核查归档和完整性，不把部分下载标为安装完成。
4. 没有字幕才准备本地转写：`python SKILL_DIR/scripts/cli.py prepare-deps whisper --download-model --python ABS_PYTHON_3_12`。首次下载模型需网络和磁盘；失败不自动改云端。已有SRT可跳过此步。
5. 选包外项目目录，例如用户目录TalkingEditProjects/我的视频。执行 `python SKILL_DIR/scripts/cli.py --project PROJECT_DIR create --title 我的口播`，然后 `--project PROJECT_DIR review --stage project` 自动打开系统浏览器。Agent可用浏览器面板时加 `--no-browser` 并打开返回地址。临时会话链接不放GitHub或普通笔记。
6. 页面导入素材，进入流程配置选语速和包装。内置暗金/资料讲解不要求额外插件；自由创意选项需Remotion插件。动画工程放包外，用npm ci安装锁定依赖；首次渲染可能下载浏览器。缺Node/npm、模型、组件或Key时显示原因，准备后重读状态。
7. 手动流程按SKILL.md完成粗剪、方向、关键帧和成片审看。分段 `wait --request ID --seconds 40` 保活同一请求；页面关闭或超时不授权继续。自动模式必须由用户在批量页显式勾选，范围见batch.md。
8. 交付视频、字幕和项目位置，stop-server。下次说“继续这个项目”时recover原目录，不重建避开未知任务。升级只更新Skill，保留包外项目/依赖/凭据。

最短试用建议：短H.264/AAC MP4＋SRT → 无动态包装 → 手动确认导出；通过后再试暗金、资料讲解或多视频。缺SRT时选择本地Whisper。自动模式不清理语义口误，复杂风格需Agent按本期内容制作。

云转写新提交当前关闭，设置Key不会开启提交，不要在聊天、命令参数或GitHub Issue填Key。付费和会员素材不在首次试用自动执行范围内。
