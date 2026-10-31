# 两种使用方式

1. 只看V2原型：README中的clone和preview命令即可。不需要模型环境，没有真实上传/保存/付费。
2. Agent制作：先读根SKILL.md，选择子Skill；项目目录放仓库外，不把素材放进源码。下面仅是依赖诊断，不会提交付费任务：

```sh
python scripts/workbench.py skill talking-edit -- doctor
python scripts/workbench.py skill 92k-video-director -- doctor
python scripts/workbench.py skill narration-footage -- --help
```

实际命令以各子Skill的SKILL.md及references为准。narration-footage没有doctor，使用help了解discover/download/audit。付费任务仅在用户配置自己的Key并确认当前方案/预算后执行。根包装器不替代子工具自己的审阅与原单门禁。

完整仓库是一个总入口Skill，子Skill无需另外复制到宿主同名安装目录。若只取子Skill可单独运行，但不带根包装器的版本检查；不要据此承诺自动更新。
