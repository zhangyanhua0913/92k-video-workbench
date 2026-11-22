# 配音接口

**不要自己拼 HTTP 请求、不要读令牌文件、不要输出密钥。** 一律通过工作台脚本调用。

## 调用方式

```bash
python "E:/n8n/92k-video-workbench/skills/life-script-video/scripts/tts.py" \
  --text-file 文案.txt --output 输出.mp3 --allow-paid
```

`mix.py` 已经封装好，正常不需要手调。

## 依赖

| 项 | 位置 |
|---|---|
| 工作台服务 | `http://127.0.0.1:18737`（必须先启动） |
| 会话描述 | `~/.92k-video-workbench/session.json` |
| 令牌 | `~/.92k-video-workbench/life-tts/04-market.dpapi`（DPAPI 加密，Windows 用户绑定） |

起服务：

```bash
cd E:/n8n/92k-video-workbench && python scripts/workbench.py open --port 18737
```

## 音色

`speaker = S_FwhCVmzP1`（人生剧本角色），`resource_id = seed-icl-2.0`，
输出 mp3 / 24000Hz。这是人生剧本系列固定音色，混剪沿用，不要自己换。

## 关键约束

- **`--allow-paid` 必传**，不传脚本直接报错退出——这是费用闸门，别绕过
- **输出路径已存在会失败**（`xb` 模式打开），不会覆盖旧音频
- 单次调用约 75 秒超时，调用失败**不要自动重试**，先看是不是令牌/服务问题
- 返回的 mp3 有时带多个 ID3 头，解码要拆（`mix.py` 的 `mp3_to_wav` 已处理）

## 分块策略

整篇一次配 vs 分段配，选**分段**：

| | 整篇一次 | 分段（当前做法） |
|---|---|---|
| 对齐精度 | 只能按字数比例全文分配，误差累积 | 每块实测时长，误差不累积 |
| 语气连贯 | 好 | 段间略有断点 |
| 单次失败代价 | 全篇重来 | 只重一块 |

每块目标 120 字（约 20–40 秒），上限 180 字。

## 没有配音服务怎么办

`--no-voice`：把音频自己放进 `<项目>/配音/01.mp3`、`02.mp3`…，编号与文案块顺序一致。
脚本只做解码和对齐，不校验音频内容对不对。
