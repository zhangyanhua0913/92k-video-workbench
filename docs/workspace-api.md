# 本地统一接口与 Agent 接续

真实服务：`python scripts/workbench.py open`，默认127.0.0.1:18737。静态原型preview仍在18735。只支持本机单用户，不开放公网。当前项目描述schema=1；子数据库仍为原工具权威。注册旧工程只改索引，不改原目录。新项目附workbench-project.json及口播/混搭风格版本记录，删除索引后可以重新登记。

## 调用方式

页面用临时会话初始化，再由HttpOnly/SameSite=Strict Cookie访问；API也接受X-Workbench-Session。写请求须带精确Origin。不开放跨域、任意代理目标或shell命令。会话保存在包外home/session.json，禁止提交、写笔记或分享完整临时URL。

Agent无需读取或输出会话：

```sh
python scripts/workbench.py api --path /api/projects
python scripts/workbench.py api --path "/api/project?id=PROJECT_ID"
python scripts/workbench.py api --path /api/action --input ABS_REQUEST_JSON
```

自定义服务home时，api同样传`--home ABS_DIRECTORY`。使用已有服务不会触发源码更新。请求JSON放项目work或其他包外位置。

## 接口

| 方法/地址 | 输入 | 作用与返回 |
|---|---|---|
| GET /api/projects | 无 | 最近工程、版本、默认保存目录；坏目录显示错误 |
| GET /api/project?id=ID | 已登记ID | 原工具状态、调用job、当前状态和历史输出 |
| POST /api/create | mode、title、可选parent绝对目录 | 创建独立工程，返回id/root/mode/title |
| POST /api/register | root绝对目录、可选mode | 检查唯一工程类型和ID，登记索引；不迁移 |
| POST /api/preferences | id、revision、patch | 保存step(0–5)、素材/生成风格意向或feedback；项目内workbench-ui.json，独立revision冲突保护，不修改制作数据库和预算 |
| POST /api/action | id、action、可选data对象 | 独立进程调用固定适配器；短动作直接返回，长动作返回job/status |
| POST /api/tool | id、可选review请求ID | 返回该工程的同源编辑/审阅页路径 |
| POST /api/upload?id=ID | 文件原始字节、X-Filename、可选X-File-Kind | 分块保存临时文件并导入工程，返回原工具导入结果；上限2GB，生成工具自身更低限制继续适用 |
| GET /media?id=ID&file=REL | 素材工程的媒体/字幕相对路径 | 鉴权读取，支持视频Range；不提供数据库/私密状态 |

mode为talk/footage/generate/hybrid。错误为HTTP状态＋message：401会话失效、403来源/路径拒绝、404未登记、409执行占用/版本冲突；子工具错误沿用其状态。读取失败不自动创建新工程。

GET project新增preferences，缺记录时返回schema=1/revision=0/step=0，不写旧工程。显式保存UI位置后可刷新恢复；风格及费用仍用原权威接口。POST tool返回路径可附`panel=roughcut/packaging/keyframes/storyboard/voices/budget/assets/final/config`供真实工作台嵌入对应步骤；只是展示过滤，独立工具页不变。内嵌保存使用同源/同window校验的postMessage回执，保存失败不离开当前步骤。

## 操作与顺序

所有类型：show、doctor、import、update、review、decide、recover。update用`data={"revision":当前版本,"patch":字段对象}`；冲突后重新读取并展示差异，不覆盖新版本。

口播本地转写可在patch设置transcribe_language为auto（默认）/zh/en/ja/ko。识别使用本机模型与VAD；语言进入本地任务指纹，已有失败记录保留，变更语言不自动重跑。云任务指纹/授权不变，不用本地语言设置重提云单。原始识别时码无效仍拒绝，不能排序或强行截断掩盖模型错误。

嵌入的口播/混搭媒体由工作台在已通过父会话认证后，向固定子工具内部附上该项目自己的临时媒体Cookie；不转发浏览器任意Cookie，不放宽独立工具的媒体鉴权，也不把子会话返回给前端。Range续读保持。

- talk/hybrid：analyze、transcribe、roughcut/packaging（Agent简报）、auto-gold、render、retry-local、attach-source、adopt-style。已有review/decide语义保持；导出前须确认粗剪，包装及关键帧有变时也须确认。auto-gold显式采用已有本地模板，自动记录技术审阅，不能视为用户实际认可。新项目默认本地剪切，不装FredTalk也可导出已有字幕的视频。

- talk/hybrid 独立组合登记：`POST /api/action`，JSON 为 `{"id":"项目ID","action":"register-preview","data":{"file":"exports/目录/film.mp4","revision":工程版本}}`。同目录 `manifest.json` 须注明 `type=independent-composition-preview`、`project_id`、`base_revision`、`sha256` 和 `technicalPass=true`；对应文件须位于该工程 exports。可选同目录 `captions.srt`。重复登记同一文件幂等；版本、工程或摘要不符拒绝。项目变更后显示历史，文件缺失或变更不提供播放。登记仅采信清单中的技术检查声明，不重新完整解码，不新建render任务、不授予最终认可；内部render的final确认不适用于独立审看片。

- 口播封面：GET project 返回 `cover_styles`、`cover_plan` 和 `covers`；未保存时默认 `blue-yellow-portrait`、封面方案revision 0。`save-cover-plan` 接收 `style`、可选 `title` 和当前方案 `revision`，保存后状态 `waiting_agent`；这不是后台生成任务，须由对话中的Agent继续。先将PNG/JPEG通过import或upload导入本工程，再调用 `register-cover`，data包含 `file`（项目内media/exports相对路径）、`sha256`、`style`、`plan_revision` 与 `project_revision`。校验风格、项目与方案版本、图片格式和摘要，重复登记幂等；生成或导入结果保留旧版本，文件更改后不可播放。登记不确认用户认可，不改视频项目版本或启动收费服务。
- generate：prepare、quote/submit/poll/download（data.operation为原operation ID）、render。预算在原director页面确认。未知任务保留原ID；paid和result_ready满足后才下载。没有新增自动收费授权。recover只读回原状态，解除pause须重新打开对应审阅并确认。
- footage：audit、render。update允许title/script/narration/narration_hash/shots/paused；不保存第二份财务状态。review阶段assets/final；decide用request_id/revision/action（confirm/revise/pause）。许可未确认、未审看、文件hash变动、素材短缺或旁白时长不符均拒绝采纳/合成。

retry-local仅允许明确失败的本地任务，data.task填写原本地task/render ID，保留失败记录并允许后续显式重新执行，不自动重试。director的running/未知合成和所有云operation不通过此入口重提。

动作示例：

```json
{"id":"PROJECT_ID","action":"review","data":{"stage":"roughcut"}}
```

review返回请求id和revision。用户通过页面确认后读取原reviews结果，不能由Agent代点预算。长动作（分析、转写、合成、模板、生成编排、报价/提交/查单/下载、资料映射）返回job，查GET project读取结果。重复请求同一执行中动作返回原job；同项目其他写入拒绝。进程重启标记调用interrupted，不自动重放；先核对原工具任务，只有明确失败的本地任务允许retry-local。

## 素材解说与混搭

素材shots每项包含asset/sha256/source_in/duration/line/source_page/publisher/product/match_reason/usage_confirmed/visually_reviewed。asset与narration是导入后项目内相对路径。duration为本镜时间轴时长；入点加时长不得越界。素材默认静音；旁白连续播放、镜头字幕按时长生成。总时长须与旁白相符（容差0.15秒），输出1280×720 MP4、SRT与来源清单。复杂动效由Agent先制作成素材再登记。许可证和事实准确性由人或Agent核对，技术审计不建立法律授权。

hybrid的attach-source输入file绝对路径、start/end真人源时间、source_page、match_reason、usage_confirmed=true、revision，可选scene_id/title/mode。file须是已裁好的本地视频，长度覆盖映射；原声保留，仅叠资料画面。指定scene_id可替换一段，其他片段和旧输出保留。跨剪切点应拆段。复杂布局使用原attach-scene机制。

风格记录只锁定选用版本，不复制整套旧执行器。检测到同一风格版本改变时阻止包装/导出；显式采用新版本后仍须按原指纹重新审阅。需要继续旧执行器的项目使用固定发行tag，禁止一边运行一边换源码。

状态：待配置/可执行/执行中/等待Agent/待审阅/失败/待核查/已暂停/完成。技术完成与最终认可分别记录；历史输出保留原版本。工作台关闭不等于取消上游任务，不自动退款。

现有独立CLI和工具页保留；批量入口及嵌套生成仍可通过原工具使用，本轮统一页单工程执行，禁止混用两个执行入口同时写同一工程。

## 本机常用参数

GET /api/defaults?mode=talk|hybrid 返回mode、revision、values；POST /api/defaults接收mode/revision/patch，沿用会话及Origin校验。patch白名单：speed（1/1.1/1.15/1.2/1.25/1.3/1.35/1.5）、subtitle_burn布尔、transcribe_language（auto/zh/en/ja/ko）、packaging（该入口原六种口播风格ID）。冲突409须重读，不覆盖。参数在本机home/workspace.sqlite3的user_defaults表，每类型一条，仅用于新建工程；登记和读取旧工程不应用默认。无个人媒体/任务/字幕副本、预算或授权。原始默认speed=1/subtitle_burn=true/language=auto/packaging=none；恢复通过显式保存这组值，不影响已有工程。

AI生成项目preferences.style支持director和life；life对应skills/life-script-video/SKILL.md，由Agent协作制作，不自动提交任务。风格意向保存不改变原引擎状态、预算或审阅。

人生剧本04配音已提供配置中心/人物与声音面板：独立DPAPI令牌、固定人生剧本角色、手动费用授权生成/试听/下载，详见skills/life-script-video/references/voice-api.md。当前仅本地/模拟验证，真实调用待用户填令牌。

04密钥是接口市场通用凭据，配音只是当前已接入的一个用途。此处名称调整沿用原加密存储和现有令牌，不迁移或重新保存凭据；不代表其他接口已自动接入。
