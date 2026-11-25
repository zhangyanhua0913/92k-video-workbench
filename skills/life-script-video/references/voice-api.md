# 人生剧本配音：阿里云百炼

默认音色「张琰华的音色」，voice_id `cd105126e4254060a3ad75d70c8b374c`，走本机 92K CLI 的 speech quote → create → status → result。音色内置约 1.2 倍速，不另行变速。音色重建后通过 `92k --site cn speech voices --mine` 核查并使用新 ID。

复用 `E:/n8n/92k-video-workbench/skills/footage-mix-v2/scripts/aliyun_tts.py`：

```sh
python "E:/n8n/92k-video-workbench/skills/footage-mix-v2/scripts/aliyun_tts.py" --script "文案.txt" --out "新项目目录"
```

脚本按自然语句分块，逐块报价并确认提交，结果是 `配音/NN.mp3` 和对应文本；平台请求 WAV 后转 MP3。合并为连续旁白并按实际音频重新对齐字幕和镜头。已有输出默认跳过；不要使用 --force 覆盖旧版。读取和使用本机 CLI 已配置的认证，不复制或输出密钥。调用会产生费用；按用户对具体制作任务的授权执行。状态未知时保留原任务句柄，查询原任务，勿重复提交。

原 `scripts/tts.py` 和工作台人生剧本配音界面仍是火山旧通道，仅供历史兼容，默认流程不要调用。阿里音色在混剪流程已有实现；人生剧本流程尚未完成真实调用验证，不能称为工作台界面已切换。

## 2026-11-25 本机核验
92K CLI 已核验为 1.9.0；使用 `92k --site cn speech voice cd105126e4254060a3ad75d70c8b374c` 查得该克隆音色状态 OK、绑定模型 qwen-audio-3.1-tts-flash。当前目录中长稿接口 bailian-tts-long 返回 temporarily_unavailable / storage_budget，长稿能力不可假设可用；先核验当前状态。旧版 CLI 1.7.0 无 speech 命令，需使用已核验的 1.9.0。不要因长稿不可用自动拆分多笔付费请求，先核对任务授权与实际报价。尚未对人生剧本真实合成验收。
