# 项目格式 v1

create输入是JSON对象。最小可用内容包含title、script、format与shots。create自动补project_id、revision和稳定镜头ID；update传完整项目及实际revision，禁止直接编辑SQLite来批准费用。

```json
{
  "title": "一个小故事",
  "format": "9:16",
  "script": "人物介绍，场景展示，字幕收尾。",
  "shots": [
    {
      "id": "opening",
      "method": "avatar",
      "visual": "人物正面，自然讲述",
      "line": "今天，带你看看这个小故事。",
      "duration": 5.0,
      "reference": "media/portrait.png",
      "voice": {"audioId": "填写实际有效音色ID"},
      "limits": {"audio": 10, "visual": 100}
    }
  ]
}
```

示例积分上限仅说明字段，不是售价或真实生成授权。用户实际批准之前不得提交。

镜头字段：

|字段|用途|
|---|---|
|id|稳定编号，重排不改变|
|method|local_image/local_video/image/image_edit/video/image_video/avatar/lipsync|
|visual、line、prompt|画面要求、台词/字幕、实际生成提示词；prompt留空使用visual|
|duration|目标秒数，0.1—180；真实模型限制以目录为准|
|source|本地画面文件，先通过import复制到media|
|reference|本地人物/商品图片，或对口型参考视频|
|audio|已准备音频；有此字段时不重新TTS|
|voice|普通音色audioId，或本人已有成功clone_task_id|
|audio_mode|source保留原声、narration使用配音、mute明确静音；avatar/lipsync始终保留最终视频原声|
|limits|audio/visual每任务最高积分，缺失时prepare拒绝准备相应付费任务|
|model、parameters|显式模型和高级参数，只使用当前目录支持字段|
|start|本地非口播视频裁切起点；保留原声时禁止截断讲话|
|motion、transition|图片zoom或none；转场cut或fade|
|candidates、accepted|执行器维护候选，用户通过素材页采纳，Agent不能在项目JSON伪造采纳|

项目bgm为已导入的音乐相对路径。所有素材路径必须位于本项目，media与exports之外的私密文件不通过页面提供。

运行数据：project.json为可读镜像，.director/state.sqlite3为权威账本，.director/history保存版本，media保存导入与生成素材，exports保存每轮MP4/SRT/manifest。不要将整个项目上传到公共仓库。凭据存于用户目录的.92k-video-director，Windows DPAPI绑定当前账户，不能复制密文到另一台机器当作可用Key。
