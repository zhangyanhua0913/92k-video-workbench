# 制作与命令

所有命令由 `python <skill>/scripts/director.py` 执行。除doctor/models/account外都需在子命令前传 `--project PROJECT`。stdout固定为JSON的ok/result或ok/code/error。命令返回成功不等于模型效果已验收。

|命令|输入 → 动作 → 输出|
|---|---|
|doctor|无 → 检查Python、DPAPI及FFmpeg → 可用状态和缺失指引|
|create --input FILE|项目JSON → 建立独立项目 → 当前版本与项目编号|
|show / recover|项目目录 → 读取SQLite权威状态并恢复镜像 → 镜头、任务、费用与成片|
|update --input FILE --revision N|完整项目与旧版本 → 版本校验、更新、使旧确认失效 → 新状态|
|import --file FILE [--shot ID]|本地文件 → 复制到项目media，可登记候选 → 项目相对路径|
|probe --file RELATIVE|项目素材 → 本地读取媒体参数 → 时长及音视频轨道|
|review --stage STAGE [--no-browser]|指定阶段 → 复用或启动本机页面并创建审阅 → request_id/url|
|wait --request ID --seconds 40|原请求 → 最多45秒等待 → pending、stale或已完成决定及项目|
|models / account|无 → 免费查询模型或Key状态 → 实际可用模型/参数或余额/到期|
|prepare|镜头/voice/limits → 准备配音和画面操作、引用依赖 → 操作ID和上限|
|plan-operation --shot ID --purpose audio或visual --request FILE --ceiling N|已适配模型请求 → 新操作或复用原操作 → 操作记录|
|quote --operation ID|任务 → 解析依赖、上传必要素材、取真实报价 → quote_id/points/expires|
|submit --operation ID|已确认范围内任务 → 持久化唯一UUID再提交 → 原任务回执|
|poll --operation ID|原操作 → 只查原任务 → 状态、费用与成品就绪|
|download --operation ID|已付成功原任务 → 下载图片/视频/音频 → 本地路径；不重生成|
|step|原项目 → 优先查询未知单，再下载已完成项，再提交下一任务 → 单步结果|
|redo --operation ID --review ID|用户在素材/成片审阅明确要求重做 → 以该审阅编号幂等建立替代操作，仍需新预算确认 → 新操作ID|
|render|用户已采纳素材 → FFmpeg本地合成、解码验证 → MP4/SRT/清单|
|stop-server|本机辅助服务 → 关闭服务 → 项目/原单/Key均保留|

## 依赖与声音

Python标准库即可运行页面和API。剪辑需要带libx264、subtitles/libass、sidechaincompress、loudnorm的FFmpeg与ffprobe；字幕使用系统中文字体。可用DIRECTOR_FFMPEG、DIRECTOR_FFPROBE指定路径。不会自动下载依赖、字体、模型。未通过doctor先不要假称可合成。

`prepare`支持默认模型：图片flux-text、参考图flux-image、文/图生视频dreamvideo、照片口播avatar、视频口型lipsync-2，配音tts-common或tts-clone；模型ID完整前缀为dreamface:。使用手工plan-operation可显式指定其他SUPPORTED中的模型，参数必须按models实际fields，不把不同模型的参数默认值混用。

request固定包含model_id、parameters、assets。assets字段值为数组，每项可为已上传asset_id、`file:media/xxx.wav`或`operation:配音操作ID`。本地文件和依赖成品由适配器上传为当前Key所属素材，不将本机路径作为公网URL。任务语义请求不因上传后的asset_id改变。

逐句配音会按字数计价；参考素材、视频和配音为不同业务单，整轮上限包含全部任务。报价过期可按相同参数刷新，只有不超过批准任务上限且未超整轮上限时继续；重做或换模型需新授权。任务费用未知保留占用，不根据余额差推算退款。

目标时长是脚本要求，不是接口保证。获取音频实际时长后，若过长先暂停画面任务并回到脚本确认；若修改版本，导入已有完成音频到shot.audio复用。人物口播最终视频可能带其自己的声音，必须试听并保留其原声。可在审片前用probe核对实际时长，将差异展示给用户调整。不要为对齐0.1秒差异擅自重买口播。

## 页面与等待

页面仅监听127.0.0.1随机端口；URL里的session只用于短期本机页面，不是用户Key。不可分享到外网。浏览器bootstrap后使用HttpOnly、SameSite Cookie；页面未确认时Agent保持当前任务并分段wait。服务30分钟无API活动自动退出，项目状态仍在；wait从SQLite读回，因此即使页面服务退出，已经确认的结果也能继续读取。

保存草稿会更新项目并使旧审阅失效，Agent读到stale后重开当前阶段。已完成请求重复读取返回同一决定。发生用户新消息时以最新要求调整，不把旧确认扩大到新镜头。

## 当前限制

首版验收对象是Windows Codex；其他Agent或系统尚未验收。无复杂多轨编辑器、无自动联网找素材、无新音色克隆、无逐字ASR字幕、无自动退款或后台唤醒。基础转场为cut或fade（画面淡入淡出，声音连续）。素材审阅和修改由Agent统筹，不自动假设AI画面符合脚本。生成接口和供应商质量须用用户单独批准预算验证。
