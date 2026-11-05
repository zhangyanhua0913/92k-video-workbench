# 04 人生剧本角色配音

固定POST https://a.92k.fun/api/api-market/invoke/volc-tts-stream?site_code=api-market，Bearer为工作台保存的独立04令牌（保留sk-前缀）。默认speaker=S_FwhCVmzP1，resource_id=seed-icl-2.0，audio_params={"format":"mp3","sample_rate":24000}，text为本次稿件。成功只接收audio/mpeg二进制，超时75秒；拒绝重定向、不自动重试，结果未知核查原调用，不能直接补扣。错误正文不返回界面/日志，避免反射凭据。

用户工作台配置中心→04 接口市场·通用密钥→填写密码框→保存通用密钥；或AI生成选人生剧本后在人物与声音步骤配置。只保存在WORKBENCH_HOME/life-tts/04-market.dpapi，Windows用户绑定DPAPI加密，不进工程、Git、Skill、环境变量或网页存储。页面/API状态只返回是否配置，不回显令牌。清除04令牌不影响旧音频和原积分Key。

手动填写文字、勾选本次配音可能产生费用后生成，试听并下载MP3，再用于分镜。接口费率尚未给出，不宣称免费或显示虚假报价。输出保存在工作台home/life-tts，ID和完成/未知记录留本机；页面关闭/超时不代表调用失败。新配音后重新对齐字幕和镜头。

Agent先启动或复用本机工作台，无需读取真实令牌。获取本次费用授权后执行：

```sh
python skills/life-script-video/scripts/tts.py --text-file ABS_SCRIPT_TXT --output ABS_NEW_MP3 --allow-paid
```

脚本读取本机会话而非04密钥，通过同一鉴权API合成并下载。不覆盖旧输出。未配置令牌会明确失败，不回退免费声线。

可选音色发现合同：同Bearer GET https://a.92k.fun/api/api-market/invoke/volc-tts-voices?site_code=api-market，筛resource_id=seed-icl-2.0，取voice_type作为speaker。当前产品固定使用人生剧本角色，不自动切到S_GwhCVmzP1，也未内置音色列表刷新。此文档为用户提供合同，真实凭据联验待用户手动配置。

本地接口：GET /api/life-tts/config（状态）；POST同路径{key:输入}或{clear:true}；POST /api/life-tts/synthesize {text,allow_paid:true}返回{id,url,bytes,speaker}；GET /api/life-tts/audio?id=结果ID读取MP3。全部沿用工作台会话/写请求Origin校验，前端只请求本机，不直接携带令牌访问公网。

04密钥是接口市场通用凭据，配音只是当前已接入的一个用途。此处名称调整沿用原加密存储和现有令牌，不迁移或重新保存凭据；不代表其他接口已自动接入。
