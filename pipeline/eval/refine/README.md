# Sol 游戏 repair + import batch

代码归属：`pipeline/eval/refine/`；唯一便捷入口：仓库根的
`scripts/refine/batch.py`。这是独立的修复后测评身份，不修改现有 whitebox
的八列成绩、原始 collect、原工程、历史 attempt 或另一对话的 Sol G005。

## 一游戏一个编辑会话

按 `game_id` 合并 Mechanic、Gamefeel 和所有 import 任务，生成**一个 prompt**，
直接调用 GameFactory-3A 的 `AgentRunner` / `get_adapter`，而非自建 subprocess 会话。
会话在隔离工程上修改；修复工具日志、完整 trajectory、prompt 和本地 ArtifactStore
保存在该游戏目录。不向全局 train_data 注册。不为每个条目开一个 agent。

准备阶段不调用编辑 agent、Sol、引擎或浏览器。执行阶段使用与 whitebox 相同的生产租约，
全批串行；共享五锁忙或 cleanup 不确定就停止，绝不删除锁标记、激活窗口或操作其他 Editor。
编辑 prompt 禁止启动引擎/OS 键鼠和修改 evaluator；编辑 CLI 自身的沙箱和权限仍需配置，
不是一个可对任意 provider 强制隔离的安全虚拟机。不要配置绕过审批/宿主沙箱的参数。

## 命令与配置

从 bench 根运行：

```sh
# 可运行的清单准备命令；不会启动模型/游戏。
python3 scripts/refine/batch.py \
  --config GameFactory-3A/pipeline/eval/refine/config.example.json \
  --output test_data/outputs/game_refine/my_batch --mode prepare

# 复制 example 为自己的 JSON，配置 provider/可写 workspace 参数、精确 Sol ID、资产路径和验收。
# 同一个 output 可先 repair 后 evaluate，或者 run 顺序完成二者。
python3 scripts/refine/batch.py --config /path/to/my_config.json \
  --output test_data/outputs/game_refine/my_run --mode repair
python3 scripts/refine/batch.py --config /path/to/my_config.json \
  --output test_data/outputs/game_refine/my_run --mode evaluate
# 一条命令执行两阶段：
python3 scripts/refine/batch.py --config /path/to/my_config.json \
  --output test_data/outputs/game_refine/my_run --mode run
```

`--mode` 默认 `prepare`，防止误启动高费用批量任务。当前 example 的 `sol.model` 和
`unity.editor_acceptance` 刻意为 null，不能直接用于真实全链。此入口不启动其他 whitebox 队列。
`games` 为空表示当前 collect 全部13例；可填写精确 game_id 限定单例。
`agent.provider/executable/args` 传给框架 adapter；选用已配置可用的修复模型/provider。
`sol.model` 必须是服务端实际 Sol 模型 ID，不推测别名、不静默换模型。
超时独立为 static 900 / plan **1800** / 每个 judge shard 900 秒；每次模型调用
最多一次，不因 schema/条件失败无限重试。实际预算、原响应和墙钟耗时在 `model_calls/`。

资产解析优先 `asset_map`，键可用 `import_id` 或 `task_id`，值为**一个真实文件路径**：

```json
{"asset_map":{"G050_aftermath_holdout_obj_001":"/actual/assets/source.glb"}}
```

也可设置 `asset_roots`，按 `ROOT/game_id/assets/asset_kind/task_id/` 查找。
声明目录内有多个候选时记 `AMBIGUOUS_PAYLOAD`，不根据质量自动挑选。
缺少资产记 `MISSING_PAYLOAD`，不影响其他 Mechanic/Gamefeel 修复；缺失导入项为
UNVERIFIED/null，不拿伪资产或零分凑数。不声称全盘没有资产，只陈述已配置位置的结果。

G050 旧 `repair_initgame_collect.jsonl` 未选中工程，但 import collect 已指向真实的
`gamefactory_G050_aftermath_holdout_20261023_120741/.../project/Aftermath.uproject`。
解析器保存双方 SHA/物理行来源，以有效 import 绑定恢复；example 同时提供用户指定路径的
显式 override。原清单不改。若多个真实项目冲突则要求显式 override，不猜一个。

## 失败会话的有界续接

普通 `repair/run` 不自动重跑 ERROR，也不为同一游戏新开编辑对话。ZCode 已持久化的原会话因服务中断时，可显式使用一次同 session 续接：

```sh
/opt/miniconda3/bin/python3.14 scripts/refine/batch.py \
  --config /path/to/original.config.json --output /path/to/original_output \
  --mode resume-repair --resume-game G015_garden_revival \
  --resume-session sess_original-session-id
```

续接校验原配置、collect、原始交付及实际资产 SHA，以及原 provider 事件中的 session/model。
使用 `repair_continuation_001/` 独立保存绑定、新旧实现身份、轨迹、状态、修复清单与 cleanup；
已有该目录即拒绝再次续接。原 ERROR stage/ledger 与原始响应不覆盖；不重复创建对话。
恢复结果以续接目录的 `status.json` 为准，`REPAIRED` 只表示会话完成且源码清单已保存，
不是 runtime PASS。当前原 output 的普通 `evaluate` 仍要求原成功 stage 与冻结实现身份，
不能直接拿续接清单绕过检查；后续测评需独立绑定已验证修复输出及新实现身份。
原始 token 流仍保存在 redacted raw archive；轨迹不再逐 token 重写全量 checkpoint，
避免采集积压丢失会话终止事件。Python 环境沿用本机已验证的 3.14。

## 测评与纹理

1. 冻结修复后真实源码、任务和输入 SHA，Sol static 保存逐项初始源码分及实际入口引用。
2. 同一次 Sol plan 给出真实键/鼠输入、每项条件、最后动作、稳定采样点及非单帧证据要求。
   不可达项保存原因，不伪造终点。Gamefeel/动作/视频/音频要求短连续观察窗。
3. 只使用现有已验收 Unity 零激活后台录制器。生成 endpoint schedule，关联
   `task -> probe/action -> physical rows -> frame/state/event`，保留真实全日志。
4. 对原始 GLB 调用现有 `priority_assets/renderer/render.mjs`，用 Three.js 真正解码和渲染
   原几何/材质，多视角 PNG 带 SHA。原文件另存 frozen，不让编辑 agent 修改参考。
5. Sol judge 接收真实引擎截图、连续短窗和原 GLB 视图，分开判断 integration / geometry /
   texture，检查白膜、粉材质、丢贴图、错绑定及形变；纯白原模型不能因为白就判丢贴图，
   视角/光照差不能单独当形变。每次 judge 最多100张真实图片，按任务分 shard，不丢窗口。
6. 代码/真实输入/状态事件/日志/稳定终点以确定性门槛给最高 **10% / 50% / 100%**，不累加。
   `sent=true`、没崩溃或没有报错本身不能给50%。原 GLB 参考缺失、目标不可见、纹理未证实时，
   不能给几何导入100%。PASS 与档位分开，门槛缺失会把未证实的模型 PASS 降为 UNVERIFIED。
7. 独立的无模型 `audit.py` 重算来源与档位，检查原交付、源码、图片/物理行 SHA 和 cleanup，
   通过才保存本地 `result.json`。不调用旧 whitebox 发布、不写 scores.md。

## 真实限制（不等于全链已验收）

- **UE5 运行链未接通。**当前 UE5 adapter 会用 OS/前台输入，违反后台约束；本实现不调用它。
  可完成编辑、静态检查和可用 GLB 参考渲染，runtime 为 `BLOCKED_UNSUPPORTED_BACKGROUND_BACKEND`，
  没有 plan/录制/judge 或正式运行分。G050 是 UE5，同样受此限制。
- **Unity 要求现有合格20/180秒原生验收**，相同 Editor/adapter/pin 原件通过核验。
  显式配置 adapter_root 为本交付 GameFactory-3A、editor_acceptance、共享 control_root。
  原生录制目前仅支持 macOS / 实际 `Assets/*.unity` 场景。正式 native admission 在隔离副本迁移旧输入，
  实际导入并打开交付场景；可用 `unity.input_system_package_root` 显式指定本地 InputSystem 1.14.0 包。
  原项目与冻结输入不改；包缺失/错误 Editor/超时属于工具或环境问题，不当作产品编译失败。
- 现有 sparse 输出是真实稀疏帧，不伪称整段连续录像。连续视频/音频有硬要求的 import，
  缺对应原生通道就不能凭截图给完整通过；当前音频没有采样通道，最高只证明运行集成50%。
- 原 GLB 只支持自包含 GLB；外置纹理依赖明确阻塞，不静默忽略。Three.js decode/render 失败留原日志。
  没有真实引擎截图就不能声称纹理保真通过。
- 已有 GLM 真实同 session 修复输出与 8 个源 GLB 的 49 张 Three.js 参考图。
  新编排的正常 plan/record/judge 集成回归使用明确标注的 fixture，不能当真实引擎全链验收。
  生产验收状态以对应 output 的 ledger、原生 receipt 与 independent_audit 为准。

## 恢复与数据布局

相同配置和代码身份、collect SHA 不变时可重复同一命令：已完成会话/模型/录制阶段复用，
不再创建会话。进程中断留下 STARTED 或 ERROR 不自动重跑，需显式新 output 建立新身份并保留旧证据。
成功结果也核验保存的原证据；不会根据低分重测。配置/资产映射变更必须新 output。
如果仅需在同一成功修复结果上继续测评，使用同一配置/output 的 evaluate。

```
OUTPUT/configuration.json, code_identity.json, inventory.json, ledger.json
OUTPUT/games/GAME/
  workspace/project/      # 唯一编辑副本
  frozen/assets/          # 不可变原资产参考
  agent_session/, blobs/, repair_prompt.txt, agent_report.json
  input/project/, tasks.json, source_manifest.json, source_delivery.json
  stages/, model_calls/, static_code_scores.json, plan.json
  references/, capture_schedule.json, native_actions.json
  background_record/, evidence/, independent_audit.json, result.json
```

## 依赖 / 交付清单

不是单拷 refine 目录即可运行。一起交付：

- `pipeline/eval/refine`、`scripts/refine/batch.py`、collect 数据与用户配置。
- `pipeline/data_collection`（adapters/runtime/core 及其仓库依赖），对应编辑 CLI/登录配置。
- `pipeline/eval/stage1`（Sol调用/schema、预算、动作校验、sparse审计、锁/cleanup等及传递依赖）。
- `engine_adapters/unity3d` 及共享 action/mouse/input helpers、`pipeline/code_gen/playtest` 的分派依赖。
- `pipeline/eval/priority_assets/renderer/{render.mjs,package.json,package-lock.json}`，
  Node、Three.js依赖、Playwright/Chromium。在 renderer 目录按 lock 安装 npm 依赖，
  将 `renderer.playwright_root` 指向包含 `node_modules/playwright` 的根目录。
- Python 框架 requirements、实际 Editor、冻结验收/pin/所引用回执、原项目及真实资产。
  共享 control_root 只是可配置锁/cleanup 数据位置；新实现不从 workspaces 导入生产工具源码。

局部回归：
```sh
python3 -m pytest GameFactory-3A/test/test_refine_batch.py -q
```


## GLM 单游戏试跑

实际脚本请使用 Python >=3.10；本机验收解释器为 `/opt/miniconda3/bin/python3.14`。
系统 `python3` 可能为3.9，现有框架部分模块使用3.10类型语法。

修复器配置 `agent.provider="zcode"` 时仍使用框架的 AgentRunner，不另造对话调度。
`agent.executable` 填 Python绝对路径，`agent.args` 以 `scripts/run_zcode_agent.py` 的绝对路径开头，
后接 `--provider-config <personal-config> --expected-model glm-5.3 --mode yolo`；
`agent.model` 必须填实际预期模型（例如 `glm-5.3`）。该适配依赖交付中的
`scripts/run_zcode_agent.py` 和本机ZCode安装；配置保存个人配置路径，凭据不写入命令/产物。
完成时核验实际session集合恰为一个、modelId相符且存在真实turn.completed和terminal result。
框架原样保留provider事件，不虚构请求边界/工具定义。

HF按单游戏获取资产：`scripts/asset/download_refine_pilot.py --game GAME_ID --inventory HF_INVENTORY --output NEW_DIR`。
先 `--dry-run` 查看固定版本、选择与字节数。资产库存由HF真实file metadata冻结得到；脚本保留commit和SHA，
默认最多下载1GiB、空闲保留20GiB，按6倍payload加1GiB预算副本/解包；不删除用户数据。
物件固定Meshy原始GLB，不下载其他方法或处理后副本。场景Portable包只提取有界task_id/scene.glb成员并保存SHA绑定；
不解压其他路径。存在.gitkeep不能当成真实motion。将输出asset_map.json配置到batch后再prepare。

2026-10-29实际pilot为 `test_data/outputs/game_refine/glm_sol_g015_pilot_20261029_v1/`，
6mechanic/8gamefeel、11个可用导入资产、7缺失motion。该目录README记录实际状态与可复查来源；
不重复运行已有STARTED/COMPLETE会话。GLB参考图不等于修复后引擎验收。

## benchmark 产物失败与已有修复输出

编辑会话完成表示拿到了模型产物，缺少 repair_report.md 或最终答复为空不作为游戏质量闸门。
正常项目走 static → native admission → plan → record → evidence → judge → audit。
原生 Editor 实际报告产品 C# 编译错误时，走 static → admission → 独立 audit → result，
`status=EVALUATED / pipeline_completed=true / product_status=COMPILE_FAILED`；逐项保留可证明的
10%代码分，运行层为NOT_RUN，缺资产为null，不伪造录制、截图或judge。工具故障仍记ERROR。

可在新配置中绑定已完成会话，不重新启动编辑 agent，不覆盖旧错误身份：

```json
{"repair_sources":{"G015_garden_revival":{
  "output":"test_data/outputs/game_refine/glm_sol_g015_pilot_20261029_v1",
  "continuation":"repair_continuation_001"
}}}
```

`--mode static` 只冻结产物、调用Sol静态检查并渲染源GLB，不启动引擎或获取Unity生产租约；
可在其他对话录制期间独立执行。之后同一配置/output用 `--mode evaluate` 复用静态结果和参考图，
获取共享生产租约再准入；租约忙就停止，不抢占其他队列。STATIC_EVALUATED不表示pipeline全链完成。

```sh
/opt/miniconda3/bin/python3.14 scripts/refine/batch.py \
  --config test_data/outputs/game_refine/glm_sol_g015_pipeline_20261029_v2.config.json \
  --output test_data/outputs/game_refine/glm_sol_g015_pipeline_20261029_v2 --mode evaluate
```


## Stage3：每项目独立 GLM 会话，先纯修复再测评

配置 `repair_rounds` 为 1..10，首轮包含在总数内；默认仍为 1。
多轮模式当前使用 ZCode/GLM：首轮建立项目独立会话，后续以同一 session ID 续接，
每轮保存 prompt、原始轨迹、实际模型/会话、源码 manifest、变化路径和失败回执。
`include_vfx: true` 将 `repair_vfx_collect.jsonl` 原始边界、验收与来源一并纳入。
四份输入及作者原交付保持只读，所有修复在候选 `games/GAME/workspace/project` 中进行。

```sh
python -m pipeline.eval.refine.batch --config CONFIG --output OUTPUT --mode prepare
python -m pipeline.eval.refine.batch --config CONFIG --output OUTPUT --mode repair
```

`repair` 不调用 static、planner、record、judge 或引擎。每次续接先核原交付与上一轮源码，
最多执行配置轮数，**完成可做编辑就提前停止，不要求跑满**。每轮提交外层
`repair_status.json`，按原始 selection_id/import_id 完整、唯一地列出已完成项与剩余项；
只剩明确外部阻塞也结束编辑，缺失或无效清单则保守继续。超时的真实调用消耗该轮预算；
后续轮超时只在保存原 ERROR、partial source、原 session/model 与来源 checkpoint 后，
用下一轮编号续接。首轮超时仍须单独来源绑定恢复，不能新开替代会话或清空计数。
已完成轮次直接复用，失败或在途轮次不原样重跑。
会话完成只表示修复产物已保存，不表示 mechanic/gamefeel/VFX 的运行验收通过。

全部选定项目修完后才能调用 `evaluate` 或 `static`；`run` 的多轮模式先完成整批修复，
再进入整批测评。最终测评闸门核每个项目的预算、成功/中断轮次、提前停止报告、完成标记以及会话独立性。
配置/模块/输入冻结后不可原地改变；新增真实资产时保留旧准备目录，建立有来源关联的新准备。

Hugging Face 下载沿用 `scripts/asset/download_refine_pilot.py` 的预定资源选择，
固定远端 commit，逐文件验证 LFS SHA256 或 Git blob SHA，并保存场景解包成员与 SHA。
缺失 motion 等资源保持缺失事实，不以占位文件、其他任务资源或新生成替代物冒充。

`post_repair_evaluation` 只记录用户指定的 mechanic/UE 工作区与目标，不代表已经绑定可执行后端。
当前 refine 的原生入口仍为 Unity；UE 接入必须针对修复后候选重新核真实入口、原生输入、
采集与 cleanup，不能将历史 G025 实录用作新候选的验收，也不能走 OS 输入回退。


## 修复后的资产细项与自动衔接

`pipeline/eval/refine_asset_diagnostics.py` 在原生测评、来源/证据独立复核之后，
对每个原始资产任务给出补充结论，原权重、原结果和历史成绩不变：

- 物件/场景：真实槽位与场景接入、几何/比例/轴向/蒙皮形变、原 GLB 的材质/UV/texture。
- VFX：触发/停止时机、轮廓/轨迹/范围/位置；时机须引用实际触发前后连续原生帧。
- Motion：目标 mesh/skeleton/clip 绑定、实际播放/触发/循环/结束、动态形变。

每个细项有自身的图片、原生 state/event/log 物理行及必要绑定源码引用。
物件/场景接入及 motion 绑定需要有效源码引用；形变/texture 要引用原 GLB 渲染。
只复制文件、没有目标画面、只有单帧、没有原资源、引用越界或 harness 出错，均不能记 PASS。
VFX 的旧 planner 窗口主要在动作之后，补充判定不会凭空补出触发前/停止证据；
须在后续原生采集接入时补足真实采样，缺失则 UNVERIFIED。

`pipeline/eval/refine_followup.py` 是有独立来源合同的后续调度入口，放在冻结 repair
包外，不修改活跃修复的代码身份。它等待原 worker 正常结束和**全部项目**修复闸门，
随后检查源码 SHA、共享锁、cleanup 与空间，再调用正式 Stage3 测评；
只有本候选合格实录与 runtime result 存在时才调用资产细项 judge。
外部锁忙时等待；修复未完成、已保存请求失败或来源改变时留下准确工程状态，不盲重试。

从 `GameFactory-3A` 根目录执行：

```sh
# 只冻结补充范围和实现身份；不调用模型/引擎。
python -m pipeline.eval.refine_followup --output OUTPUT --prepare --worker-pid REPAIR_PID
# 已有调度进程时不要重复启动；本入口另持 dispatcher.lock。
python -m pipeline.eval.refine_followup --output OUTPUT --watch
```

配置、collect、旧修复身份不变，补充范围与实际调度状态保存于 `OUTPUT/postrepair/`。
`WAITING_FOR_ALL_REPAIRS` 不是评测已开始；`BLOCKED_RUNTIME` 不是产品失败或零分。
UE 项目仍需来源绑定、参数化的正式原生 backend 与本候选验收，当前不能借调度器绕过此条件。
