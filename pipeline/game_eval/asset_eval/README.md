# asset_eval

独立三列评分，不合成总分；当前限定 G001 小样本，不扩全量。

- **3D object**：12条计划记录中已有4份交付实测，完成真实18视角渲染、sol rubric/style、色板、MUSIQ及trimesh几何。其余8条缺交付为null。
- **3D scene**：G001_scene_001 来自用户确认的 Marble（兼容 `mable` 拼写）。只读从 Godot ZIP 提取指定GLB到eval目录，复用原 renderer 完成18视角。没有修改项目或启动引擎。评价对象是包内交付GLB，不能推断其下游加工前的原始Marble输出。
- **CG**：新增16帧、prompt/rubric判定、角色reference匹配与sol框、DINO裁剪、MUSIQ、静态区域闪烁代理及规格符合度。属于小样本链路，尚非逐帧/VBench验证。
- **音效**：新增官方 CLAP + 本地LUFS/削波/静音。未验证听音通道和Audiobox等感知模型时，第2/3列为null。对话ASR/emotion/ECAPA未实现，不能把音效指标用于对话。

## 安全与资源

只写本目录与 `test_data/outputs/eval/asset_eval/`。输入、priority_assets、whitebox_eval、engine_adapters、playtest只读；不改生成侧、不下载更多生成资产、不做motion/VFX。

所有运行使用 `/opt/miniconda3/envs/asset_eval/bin/python -B`，版本必须匹配锁。nice=19、数值线程=1；这些不是资源隔离，也不是零影响保证。检查到白膜batch或sol活跃时，重计算与新sol调用暂缓，不停止/修改其他进程。

sol只import既有`whitebox_eval.codex.call_codex`，gpt-6.1-sol/medium/600秒；本模块API串行，502/断流最多重试一次。原始prompt/response/invocation保留，无代码补判词/补分。

模型优先MPS，不支持算子回CPU并记录；媒体模型逐个加载与释放。官方权重仅来自facebook/dinov2-base、laion/clap-htsat-unfused及pyiqa官方权重。未完成指标为JSON null及CSV字面`null`，不填0、不重分配质量权重。

## 命令

在 `GameFactory-3A/` 运行，`--out`须为新的eval子目录：

```sh
# obj：默认含sol；明确不要sol可加 --no-sol
/opt/miniconda3/envs/asset_eval/bin/python -B -m pipeline.game_eval.asset_eval.run \
  --scope obj --games G001 --providers meshy tripo

# scene：默认marble；mable为alias
/opt/miniconda3/envs/asset_eval/bin/python -B -m pipeline.game_eval.asset_eval.run \
  --scope scene --games G001 --providers marble

# 小样本媒体：两份CG、两份音效；不扩量
/opt/miniconda3/envs/asset_eval/bin/python -B -m pipeline.game_eval.asset_eval.media_pilot --metrics

# 仅一种媒体；cg为video别名
/opt/miniconda3/envs/asset_eval/bin/python -B -m pipeline.game_eval.asset_eval.run --scope cg --games G001
/opt/miniconda3/envs/asset_eval/bin/python -B -m pipeline.game_eval.asset_eval.run --scope audio --games G001

# 只做轻量obj预检；只做媒体解码/信号测量
/opt/miniconda3/envs/asset_eval/bin/python -B -m pipeline.game_eval.asset_eval.run --scope obj --mode preflight --no-sol
/opt/miniconda3/envs/asset_eval/bin/python -B -m pipeline.game_eval.asset_eval.media_pilot
```

完整object阶段仍未通过：G001 image任务交付缺失，生成资产跨游戏负对照未做。参考图self=1.0、跨游戏同role参考图=0.29979、纯色色板ΔE=0.0只是部分对照，不冒充全部验收。

历史 `20261024_203121_obj_no_sol_smoke` 名称误标，实际含8份sol判词；后续审计保留来源与hash，不改原始响应。

## 指标与null

3D：输入text/image分开；风格分0–4、色板ΔE及覆盖率分开。几何必需测量缺失则子分null；Q=0.5×MUSIQ+0.5×几何。Scene未指定decimation_target，所以总质量null，同时保留真实MUSIQ/几何原值。

CG：第二列是与明确任务角色reference的DINO余弦（不是3D的0–4风格分）。主体框缺失时不以全帧相似度代替。没有可靠分割mask时前景色板null，全帧色板另记诊断。Qv=100×(0.35C+0.20F+0.30M+0.15S)，缺任何必需项null。公式与阈值写入每次appendix。

Audio：CLAP余弦不是0–100 MOS。LUFS/削波不能代替感知质量；文字prompt不能冒充实际听音。VABench定义、已执行与未执行部分见appendix，不声称数值已对齐。

输出包含逐资产score.json、scores.csv、report.md、appendix.md、run.json、证据图与模型来源；3D/控制测试另有pilot_summary.md与验收状态。

```sh
/opt/miniconda3/envs/asset_eval/bin/python -B -m unittest \
  pipeline.game_eval.asset_eval.test_smoke \
  pipeline.game_eval.asset_eval.test_additions -v
```
