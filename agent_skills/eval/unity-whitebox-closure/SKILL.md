---
name: unity-whitebox-closure
description: "在 bench 工作区执行 Unity、Godot、Three.js、UE/UE5 whitebox 真实测评与恢复：按作者源码和原生反馈修正式 adapter/非评分语义工具链，闭环 plan、record、evidence、judge，按授权单列或多列发布并逐例安全核缓存。用于测评接管、正式迁移验收、阶段恢复和真实双端接入；不用于补写作者玩法或擅改评分标准。"
---

# 跨引擎动态适配与真实测评闭环

保留 `unity-whitebox-closure` 名称、目录和 `$unity-whitebox-closure` 调用以兼容已有引用；**适用于 Unity、Godot、Three.js、UE/UE5，不限 Unity，也不默认八列**。支持一种引擎的流程不代表另一种已原生验收。

## 使用边界与当前任务选择

先读根 `AGENTS.md`、`AGENT.md`、当前用户请求及对应专项的唯一 `current_plan.md`、接管文档、协议/修订/契约/scope。按适用指令优先级确定模型、题号、tier、上传者、引擎、评分列、排除项与重评/跳过政策；**skill 不扩大授权，不接管其他会话，不因共享目录新增另一专项就启动其评分列**。

- Mechanic v3 专项计划：`GameFactory-3A/workspaces/whitebox_eval_mechanic_basic_path_v3/current_plan.md`；旧 Unity 八列任务计划：`docs/whitebox_eval_current_plan.md`。按当前任务选一个，不互相覆盖，不另建实时计划。
- 实时 PID、分数、数量、剩余身份和下一任务只写当前计划，更新前归档；历史报告、snapshot、inventory 不代替现场。不要把这些时序快照固化进 skill。
- 当前编码代理承担读项目、修正式链、验证、恢复的循环；不凭 skill 切模型、另开代理或修改冻结 planner/judge 配置。Mechanic `whitebox-mechanic10-50-100.v3` / `outcome_frame_v1` 的 static/planner/judge 使用冻结的 `gpt-6.1-sol`，不外推其他协议。
- **用户仅要求整理 skill、交接或暂停时，只完成相应文档工作，不启动引擎、admission、模型调用、队列或缓存删除。** 获授权实测后逐例推进，不以文档、排队或监护代替测评。

进入实测/修复前读 [执行与问题恢复手册](references/eval-workflow.md)：按实际引擎查“原生入口”，迁移查“正式链验收”，规划/送达故障查对应章节，出分后查“发布与缓存”。正式模块路径是导航，不是可绕过资格化/持锁的内部调用许可。

## 1. 先核现场，禁止重复派发

- 重核所有相关进程身份、启动时间、后代、心跳、phase/deadline、stop/cleanup 标记、租约、正式执行锁、共享锁及发布锁；读取请求/响应、来源 SHA、adapter pin 和匹配引擎版本的原生验收。旧 PID 或一次锁探测不证明归属/持锁。
- 其他会话持锁时保留锁与归属回执，暂停依赖它的 native 派发，做允许的离线来源/工程工作；不删锁、不终止外来进程、不绕锁调用底层函数，也不让整批案例反复制造同一种 flock 失败。admission 前失败不是新录制，更不是产品零分。
- 先查最靠后的合格阶段：完整有效发布→按当前跳过政策复用；合格 record→evidence/judge；合法 plan→record；真实作者入口→plan。文件存在、runtime 首次 snapshot、static 初始分或 accepted 单个分区都不等于整例完成。
- 导入、record、evidence 等高占用阶段前实测空间、估算用量并另留至少 **8GiB**；不足先核已发布例的安全纯缓存，仍不足保存缺口，做低磁盘工程，不删除证据。

## 2. 范围、原始来源与跨批次已有新分

- 按用户指定题号完整盘点 tier、模型、实际引擎、原始交付及缺交付；不沿用旧小批数，不按分数、可测性或已有实录挑样，不以 Godot/Three.js 子集代替全范围。M/L 与明确排除按授权单列，不能隐藏。
- 冻结原始需求/rubric、确定性候选、项目路径/marker、源码与资产 SHA、上传来源和 adapter pin/验收。已有冻结身份与新发现候选不同时保留原身份并解释差异，不换更有利交付；scope 及其 SHA 在看本轮结果前冻结。
- 上传者限制须保存仓库、路径、commit/上传记录、身份/login/作者关联证据，以及 Git blob/本地文件 SHA 对应；提交作者、后续修复者不自动等于上传者。历史 uploader audit 只是线索，不是完整范围证明。
- **当用户要求“已有新版成绩不重跑”时，跨批次核验**协议/修订、来源、完整判词、计算分数和正式 publication/引用绑定，再按冻结身份去重跳过；不能只看本批 report。旧版分、HARNESS_ERROR、plan、零分占位和不完整判词不算完成。明确授权独立重评时按其重评政策，不把跳过规则外推。
- 分别报告本批新增、跨批复用、去重已分/总范围和严格同题配对均分的分母；缺失不填零，不把多份 publication 当多个已测项目。

## 3. 多引擎正式迁移与非评分语义修复

实际引擎由作者 marker、入口和源码核验，分别使用 `engine_adapters/{unity3d,godot,three_js,ue5}/` 正式能力。缺原生 adapter/验收、作者入口或真实双端时保存具体证据、根因、恢复条件并推进其他项；**不能移植引擎、补写作者玩法或用修复交付冒充原始交付**。

除非用户明确授权建立新协议，保持 rubric、endpoint/tier/credit、各列/机制权重、资产分母、judge 判定语义、证据充分性、引用有效性、PASS/FAIL/UNVERIFIED、HARNESS_ERROR 与 audit 规则不变；不以修工具链为名放宽评分或校验。

从完整编译/启动日志、真实输入、state/event/log、capture/cleanup 及最早失败定位最小修复。隔离兼容仅限有授权且源码可证等价的 API/包/编译适配，保留作者只读原件、patch、前后 SHA 和 provenance；缺失场景/方法/GUID/联网玩法不能凭空补齐。

- 生产评分、契约、scope/source 绑定、plan、原生 record、evidence/图片送达、judge/schema、计算与引用校验、持久化/发布、恢复、cleanup、cache 均须正式入口可达；不能以部分文件已在 pipeline 宣称迁移完成。
- 正式运行不得 import、动态加载或 subprocess 执行 `workspaces/`、历史 `validation/` 的旧评估工具/快照；显式只读历史证据和正式 adapter 允许。workspace 承载配置与材料，不盲搬整个目录，不移动已绑定证据，不覆盖其他会话修改。
- 保存完整调用链/入口映射、前后文件清单/SHA/patch、根因、评分语义等价论证、定向回归与真实案例验证。input/state/event/record/cleanup 能力改变须匹配引擎版本原生验收；仅无损包装改变且 pin/验收有效才可复用实录。
- **新模块通过单测、旧 migration acceptance 存在或旧入口仍能 run，不代表新代码已验收。** 核完整生产绑定集合与变化，完成相应回归、真实链路及正式迁移验收；保持旧 v2 默认行为不变。

## 3b. 双客户端（dual client）——两个独立客户端

用户明确要求某个 Playable 检查必须由两个真正独立运行的客户端各自完成时，用独立客户端模式，而不是单端跑两次或在一端开两个窗口：

- 两个客户端各用一份独立的作者项目副本（各自 admission、各自构建/导入、各自的录制插件），不是同一份副本跑两遍，也不是一个客户端加一个伪客户端。
- 用 `pipeline/eval/stage1/independent_ue_pair.py` 的 `run_playable(delivery, out, models=..., authorization=...)`：它以 `pair_slots()` 先按固定顺序占用两条录制通道，两个客户端并发启动；每个客户端走原有原生录制和 `playable_rules`，**规则不变**。
- 聚合：`aggregate(client_checks)` 逐项要求**两个客户端都 PASS 才 PASS**；任何一端工具故障记为未验证（不计分，不是产品失败），并在报告里写明是哪一端、哪一步。
- 保留两端各自的 request/response、actions、frames、cleanup、receipt 和来源 SHA；只报告一端的结果不等于双客户端完成。双客户端是"两个独立客户端"，**不声明联机/多人**，也不得用同题另一模型或另一 run 的结果顶替第二端。
- 与普通录制共用同一组引擎资源：双客户端必须持 `pair_slots` 的预约，不能绕开全局引擎互斥；空间不足或锁被占用时保留预约记录并暂停，不降级成单端。
- 需要验证"两个玩家同时玩、互相能看见/影响"这类交互时，**代理自己开多个独立客户端**去做：为每个客户端准备一份独立的评估副本、各自启动一个引擎实例（各自 `-projectPath`/`.uproject`、各自端口与录制目录），依次或并发接入同一个共享后端，用各端真实输入和真实帧观察交互，两端各自的 actions/frames/evidence 都保留。代理有能力这样起多端，按本 skill 的通用要求执行（真实输入、真实帧、不伪造、不跨端顶替）即可，不需要改评分。
- 自己开多客户端时同样受资源约束：先核全局引擎互斥与磁盘，两个引擎实例并发前确认内存/显存够用（UE 每个实例数 GB），不够就串行并保留各端合流的证据；结束时逐端真实 cleanup。

## 4. Plan → 真录制：近期规划恢复教训

能进入作者真实入口就解决到可执行 plan，有 plan 就真实 record，有合格 record 就继续完整 judge。局部计划、失败、死亡、未通关和低分均可测，不以全覆盖或完美计划为开录门槛。

- 恢复 plan 的观察元数据、共享观察条件和身份/SHA 绑定；保持既有物理动作、目标和评分语义，走原 schema、native、capture 和引用验证，不通过重置已有 admission/runtime 状态假装未录制。
- **无按键 `mouse_move` 仍是物理输入，不是 passive wait**；延长它也推迟 last-input，不能修好 endpoint。确需观察等待时使用 adapter/schema 支持的真实 wait，重新校验 coverage/probe/window 时钟与原采样约束；不以 timing 修复增添评分门槛。
- 保留所有失败 attempt、请求/响应/schema/actual_delivery、claim、指纹、次数和预算。代码 SHA 已进入 claim 时，修复后身份漂移必须有正式父失败绑定/恢复 lineage；不能删 claim、清计数或换目录原样重试。模型调用前失败须保留“未调用”证据，区别于服务已接单。
- 录制使用正式引擎/浏览器后端、真实输入/时钟/原生帧；禁止 OS 键鼠、窗口激活回退、replay、合成帧与虚构动作/状态/事件。双端须真实共享玩法、双方输入与采集，不以两个独立单端冒充。
- 录完立即关闭本任务本例自有引擎/浏览器及已核归属后代，保存真实 input/view/process cleanup 后再 evidence/judge；`report_only`、父进程消失或 cleanup 文件存在均不等于三项成功。

## 5. Evidence → Judge：源码、图片和传输不能漏

- 作者源码优先完整送达；所有契约预声明的真实窗口帧及 endpoint 帧须实际送达，不只传路径/manifest。核每帧原生像素、SHA、身份与 `actual_delivery`，不得缩放、合成、裁掉必要上下文或静默丢帧。
- 合格历史实录仅在来源、pin、原生验收及实际源码/图片送达均核验后复用；新协议重新 judge 时明确标记“按新结果导向契约重新评价历史实录”，生成新判词，不能给旧 verdict 换标签或冒称新录制。
- 输入超限/HTTP 413、输出截断、超时、502/503、schema/引用/解析失败分别分类为工具故障；不生成产品零分。先查已保存 accepted response，实质修复后只补缺失部分，不无变化无限重发。
- 模型反复读 schema 路径耗尽时间时，可用正式完整 inline schema/固定上下文传输解决，不删 schema/源码/工具必要上下文；无损图像编码也须像素等价及送达证明，不能把“文件更小”当 413 已解决。
- 重复/超长 EVENT 仅可逆无损包装，保存原文/schema、实际提交、SHA、逆展开证明、原物理行号/次数/引用。拆分合并保留原判项、完整必要上下文、图片限制/白名单和校验，不提高上限、不手填判词。
- 查阅 [实测故障模式与恢复步骤](references/eval-workflow.md#6-模型与-evidence-故障分层)：涵盖完整源码/帧请求超限、bounded correction 耗尽后的恢复 lineage，以及 original/refine/reference 与合格原生实录的区分。

### Mechanic v3 专项评分护栏（不外推其他列）

同题跨模型首次 runtime judge 前冻结相同目标结果、可接受画面、正确对象/必要因果与基本 bug 条件。逐机制沿用冻结身份/权重取最高档不累加：10% 有效源码存在；50% 实测基本功能、对象正确且无已知基本 bug，目标结果未充分证明；100% 真实结果画面证明原始意图效果发生、对象/必要上下文成立且无已知基本 bug。

精确时序、空间、速度、数值/公式、全部边界/模式只诊断，不从 full_requirement、endpoint 或 schema 偷渡为门槛；不统一要求双时点、内部字段、逐弹 ID、守卫日志、完整对照或通关。清楚单帧足够，歧义才补最少上下文；整局失败不抹去已完成机制。动画/成功文字不等于效果；扣错对象、攻击回血、凭空资源不能判成功。正确拒绝须证实操作发生且被正确处理；未覆盖不是产品 bug。

## 6. 按授权发布 → 精确缓存核查 → 交接

- **单列/多列专项**：完整有效目标列判词、分数、来源持久化即走专项正式发布，标 `SCORED_PENDING_AUDIT（未审计）`；仅更新授权列与新旧对照，保留旧分，不调用其他列、不生成八列总分。使用正式对应列缓存资格，不伪造八列绕门槛。
- **旧八列任务**：完整有效八列后按正式定向流程更新 `scores.md`、`score_new.md`、`score_verify.md`、`final_report.md` 和来源，保留结构/独立诊断口径。两种发布都不等全批或 audit，独立审计通过才升级 formal effective。
- 发布后立即持所需正式锁核本例 cleanup、进程、引用、恢复、共享与 audit 依赖，再按**精确路径**处理可证再生成的纯缓存。外来锁占用记 `BLOCKED_LOCK`，保留并稍后复核；检查 `COMPLETE` 也可能全部 `PRESERVED`、删除 0 bytes，不能报成已回收。
- 不通配批删、不删整副本/项目，不动原始源码/资产、帧/录像、state/event/action/log、请求/响应/schema/actual_delivery、失败/claim、来源/判词/publication/cleanup/audit、共享/系统缓存与他人依赖。各引擎缓存名不等于删除许可，特别保护混存证据目录。
- 保存精确删除/失败/保留路径、原因、实际删除 bytes 和前后 free；候选大小、空间差额和历史回收量不是本次回收量。
- 阻塞先保存根因、最后合格阶段、下一正式工程动作与恢复条件，切换可推进项，实质修复后回访；约十分钟排错时间片不是永久放弃。报告分开列真实新 record、历史复用、新判词/已发布未审计、回归/真实验收、缓存实际 bytes、缺失与下一动作；文档、排队、监护、工具错误和排除均不计完成。


## 追加经验索引（2026-11-06）

[执行与问题恢复手册：新增故障与恢复经验](references/eval-workflow.md#新增故障与恢复经验) 追加记录冻结模式/BUG 输出纠错、完整源码传输准备顺序及本地插件锁路径重定位；逐条区分真实验收边界与待验证状态，不能用文档记录替代正式执行。
