# 制作与验收

命令使用Python3.10+，项目在包外，FFprobe通过PATH或DIRECTOR_FFPROBE指定。脚本不含API密钥，也不调用付费生成。搜索使用Agent可用搜索工具，不能假称脚本能搜索全网。

```
python scripts/footage.py --project PROJECT discover --page HTTPS_PAGE
python scripts/footage.py --project PROJECT download --url HTTPS_MEDIA --page HTTPS_PAGE --id ID --product "产品及准确版本" --publisher "发布者"
python scripts/footage.py --project PROJECT audit --plan PLAN_JSON
```

发现器解析HTML的video/source属性（含无引号、WebM与MP4），不执行站点JavaScript。动态播放器未发现媒体时由Agent检查官方播放器/允许导出方式，不能猜文件地址。下载有限体积/超时，拒绝非公网HTTPS目标与越界项目路径；不同服务的密钥不发给素材站。失败文件不能冒充完成，重复id不覆盖。

计划JSON含assets字典和timeline数组。assets每项含file/hash字段sha256/duration/product/source_page/publisher/usage。timeline每项含id/kind/start/end/asset/source_in/product/match_reason/visually_reviewed；时间均秒，半开区间。视觉记录由Agent实际查画面后填写；不是用户采纳。audit只查确定规则，Agent另外核事实、许可、旁白与画面动作。

参考片研究流程：保留完整转写草稿→校对段落→逐句列画面意图→查精确版本原始出处→比较参考画面和候选关键帧→定素材源入点→设计旁白时刻与素材事件时刻映射→短段制作→整片。原参考中的视频片段不能记成已从网上独立收集。

推荐场景记录还包含source_audio_range/caption/visual_role/crop_focus/source_event_time/narration_event_time。转场先考虑硬切、片内推近、构图切换；不强制每镜淡入淡出。整段包含进入、动作发生、阅读停留和退出，关键动作可提前约0.1—0.3秒引导注意，但不得造成语义失真。

交付注明哪些是自己制作的动画、哪些是外部素材、哪些沿用参考音轨、哪些尚未核实。支持原工程继续，不共享本地会话URL和用户媒体到Git。

## 示例与研究素材
本发行包不包含研究片、参考音轨或下载的视频。请使用自己有权使用的素材，并为当前稿件制定来源和时间映射；不要把其他项目的研究片直接当作通用模板。根目录examples提供原创合成计划数据，不代表已下载或授权任何媒体。
