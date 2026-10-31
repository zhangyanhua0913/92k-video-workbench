# 命令与项目协议

所有命令：`python SKILL_DIR/scripts/cli.py [--project ABS_PROJECT] COMMAND`。JSON 输出为 `{ok,result}` 或 `{ok:false,error,message}`；不可向 Agent 输出 Key 或网络异常原文。

|命令|参数与用途|
|---|---|
|doctor / skills|依赖、媒体程序、可用适配器；无付费请求|
|configure-runtime|`--ffmpeg ABS_EXE --ffprobe ABS_EXE`，保存本机媒体程序位置|
|batch-create/add/list/enqueue/run/open|详见batch.md，创建批次、导入、串行排队和打开独立项目；create支持 `--mode manual/auto`|
|auto-gold-plan|只读当前字幕与剪切区间，返回暗金标题候选；不会执行制作或授权|
|create / show|创建/读取指定项目；create 可加 `--title`|
|import|`--kind video/subtitles/script/image/music --file ABS_FILE`，复制原素材到项目；video 须含原声音轨；music 返回文件及摘要，须再 update 采纳|
|update|`--input PATCH_JSON --revision N`，仅允许标题/文稿/速度/流程/字幕/剪切/场景/烧录字幕|
|review|`--stage project/workflow/transcribe-budget/roughcut/packaging/keyframes/final [--no-browser]`|
|wait|`--request ID --seconds 40`；同请求分段等待、认证保活；返回 pending/completed/stale|
|step|`analyze/transcribe/roughcut/packaging/render`；roughcut/packaging 返回 Agent 简报，其余实际执行|
|recover|读取项目/原任务/决定；`--resume` 只在用户要求恢复时解除暂停|
|stop-server|关闭辅助页面，不删项目|
|prepare-deps|`fredtalk [--path ABS_DIR]` 或 `whisper --download-model [--python PYTHON_3_12]`|
|catalog|`--query 中文画面对象与动作`；检索5个候选，不代表候选已可执行|
|fred-gate|`--manifest FRED_MANIFEST --stage suggestion/keyframes`，运行上游真实门禁|
|render-scene|`--scene ID --code REMOTION_DIR --entry SRC_FILE --composition ID [--browser CHROME_EXE] [--manifest FRED_MANIFEST]`；本地渲染与关键帧生成，FredTalk 必须先过建议门禁|
|register|`--input ADAPTER_JSON`，注册经 Agent 审阅的粗剪/包装扩展|
|attach-scene|`--scene ID --video MP4 --keyframe PNG --code REMOTION_DIR --entry SRC_FILE --component SOURCE_ID --source-revision SOURCE_COMMIT [--manifest FRED_MANIFEST]`；FredTalk 须过关键帧门禁|
|retry-local|`--task TASK_ID`，只为已明确失败的本地任务解除幂等占用、保留原失败证据；云端不允许|

项目默认原速，speed 可选 1/1.1/1.15/1.2/1.25/1.3/1.5，变速后重新确认；时间始终记录在原视频源坐标。cuts 与 scenes 是半开区间。重叠剪切合并执行，不能删除整片。字幕纯文字修订不产生剪切；句内剪切保留待校对提示，不推断剩余文字。修改时要同步按实际剩余发音修字幕和边界。

```json
{
  "cuts": [{"id":"cut-1","start":2.3,"end":3.6,"enabled":false,"reviewed":false,"reason":"失败重说候选，待试听"}],
  "scenes": [{"id":"scene-1","title":"解释工具差异","start":5,"end":8,"mode":"overlay","componentPlan":{"query":"两张卡片并排对比","candidates":[],"selected":null}}]
}
```

scenes 支持 overlay（默认右上，可用 layout={x:0.025,y:0.1,width:0.32} 这类归一化参数调整）和 fullscreen（画面替换，保留真人原声），片段自动淡入淡出。包装素材必须按对应时长制作，不混入旁白或私人品牌，字幕最后统一烧录。场景不得跨已删除范围；须按保留区间拆分。剪切或速度改变会使 timing_fingerprint 失效，须重新对齐与确认。attach-scene 不等于视觉门禁通过，Agent 仍须运行 FredTalk 门禁并实际检查。选择了包装能力但无实际场景时会拒绝导出；明确跳过须将 workflow.packaging 设为 none。

可选 music 对象：导入音乐得到 file/sha256，再 update {music:{file,sha256,gain_db:-20,fade_seconds:2,title,provenance}}。允许 -50 至 -6 dB；页面可调整或移除。新增/改配乐会使包装及成片确认失效，粗剪确认保持。合成时音乐循环补足、淡入淡出、人声侧链避让并做峰值保护；原声不额外增益。audio 下载为未混音乐的原声母带，MP4 含实际混音；默认 music 为 null/未设置。用户自备或本地原创音乐的来源应明确记录。

原始媒体/历史版本不覆盖。project.json 为镜像，`.talking-edit/state.sqlite3` 为权威数据，exports 为每轮产物，work 为中间音轨/识别及工程。项目可含私人录音和临时云数据，不上传仓库。不直接修改 SQLite、reviews 或 tasks 绕过确认。恢复时核对任务状态，未明确结算不猜账单。

本机页面 API：认证头 X-Talking-Session；写操作须精确 Origin；媒体使用每项目独立 HttpOnly/SameSite Cookie。POST update/decide/import 均绑定 revision，越界路径拒绝。session.json 含页面访问凭据，不能分享或放普通交接。

当前云端模型 `qwen-audio-3.1-asr-flash-filetrans` 的官方价格为输入/输出 Token 分别计费；未实现可信输入/输出上界合同，新提交明确关闭。verify-price 只保存核验材料，不能解除该关闭。原任务续查代码复用 FredTalk 传输与导出入口，本轮尚未真实付费验收。
