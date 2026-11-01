# Changelog

## 0.1.0-prototype.12

- Add a reusable blue-and-yellow portrait cover Skill as the default creative direction for talking-head video projects.
- In the existing delivery step, save a per-project cover plan, import and review real cover images, and download registered covers. Agent-assisted generation remains explicit and does not create paid jobs.
- Keep cover revisions and video approvals separate; reject stale or changed files while retaining older cover versions.

## 0.1.0-prototype.11

- Register an Agent's independent talking-head composition against its original project and revision, with manifest/hash validation, idempotency and retained history.
- Show registered previews in the existing review and delivery steps, with playback and subtitles; distinguish them from built-in render tasks and user approval.
- Reject stale registrations and detect missing or modified files without changing the original six-step flow.

## 0.1.0-prototype.8

- Fix authenticated playback of talking-head media through the workspace: bind the current child's media cookie internally while keeping parent authentication and Range requests.
- Follow project hash navigation without requiring a manual reload; save current edits before switching.
- Add per-project local transcription language (auto/zh/en/ja/ko) and offline VAD to avoid detecting the language from a silent camera-preparation section. Invalid timings remain rejected and failed attempts are preserved.
- Hide animation keyframe review in the no-animation preview flow; keep all original six workflow steps.

## 0.1.0-prototype.7

- Match the original import-step hierarchy: video selection precedes optional project text, keeping the first action visible immediately.
- Include the full original six-step restoration from prototype.6 with real backend capabilities preserved.

## 0.1.0-prototype.6

- Restore the approved original four V2 workflows, each with its exact six step labels and order, right-side plan and bottom navigation.
- Keep real project/import/edit/style/review/export adapters; move diagnostics, recovery, retry and Agent handoff into collapsed project tools.
- Save before changing steps, retain the current step on failure, and resume saved UI position without granting execution or budget approval.
- Present model/budget and voice controls in their corresponding generation steps; standalone editors remain compatible.
- Persist the user's requirement to explain and obtain confirmation before future changes to workflow steps or primary interaction.

## 0.1.0-prototype.5

- Real `open` workspace, separate from the retained static `preview`: four modes, persistent project registration, legacy-project discovery and same-origin editors.
- Isolated subprocess adapters and a shared UI/Agent API; revision conflicts, per-project job deduplication, restart recovery and explicit local-failure retry.
- Local-cut talking-head export without FredTalk; existing gold template, complex Agent packaging, subtitle/speed/music reviews and real delivery.
- Persistent narration footage projects with local imports, provenance/permission/visual checks, continuous narration and 720p MP4/SRT synthesis.
- Director budget/original-task adapters and hybrid source-clip mapping/replacement. No new paid model acceptance or automatic budget authorization.
- Explicit style-version adoption; checkout newline differences no longer reject identical cached gold dependencies.
- Independent behavioral tests, real synthetic-media acceptance and opt-in browser/template verification. Source-only distribution remains unchanged.

## 0.1.0-prototype.1

- Independent V2 prototype and three related Skill source packages.
- Root Agent Skill and launcher with fast-forward update checks and local-change protection.
- Opt-in Windows author file-event publication with version bump and remote verification.
- Source-only distribution; no parent-project services, private runtime or research media.

## 常用设置与1.35倍速

- 原字幕与粗剪增加1.35倍速，字幕/音画时间映射及真实合成沿用现有执行器。
- 现有配置中心新增显式保存常用参数、记住当前项目和恢复默认；口播/混搭各自保存，重启保留，仅作用于新项目。原四入口六步不变。
