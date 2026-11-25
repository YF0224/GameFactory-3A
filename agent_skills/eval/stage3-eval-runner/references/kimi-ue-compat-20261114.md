# 2026-11-14 Kimi UE 兼容恢复：已验证事实与限制

本记录只对应用户“这些都修复一下，继续测评”的 Stage3 Kimi 授权，不扩展到其他评估或改变冻结评分。默认技能的工具代码边界保持不变；本次用户已明确授权修 harness。原件和冻结 input 未改，失败目录唯一改名归档而未删除。

材料目录：`<repo>/test_data/outputs/eval/refine/supervision/opus_astra_20261113/kimi_failure_followup_20261114_125508`。生产 SHA、测试、独立审查及 admission 回执见 `prelaunch_verified.json`；队列配置见 `config.json`，动态进度见 `events.jsonl` 和 `progress/`。这些是带时间的回执，不是实时完成清单；接管先核现场。

## 正式恢复中的两个工具问题

- 历史 UE admission 携带旧 compatibility receipt 时，先按其历史 provenance 校验；不能强加当前 selection SHA。原 plan 已变化时，沿正式 rebuild transaction 归档历史 transaction 原字节并绑定历史 SHA，再写 rebuild intent 与新事务。不可删 transaction 或改冻结来源绕过校验。
- 评分 provenance 的必需 takes 从真实 verdict evidence 和带 calls_result/verdicts 的 direct/state/takes 记录确定。未参与判分的 optional 失败 take 不能只因残留 binding 阻断发布；已判分 take 的 record/binding/evidence 缺失仍必须失败。`regression_review_fix/receipt.json` 为33项通过；`review_followup_response.txt` 为独立只读审查通过。

## 项目验收与故障诊断

- G030/G055/G060 兼容 overlay 通过真实 UE5.4 编译与 admission，`native_acceptance.json` 同时核 input 不变。补丁绑定 `<repo>/test_data/outputs/eval/refine/supervision/opus_astra_20261113/kimi_failure_followup_20261114_125508/compat_plan.json` 的原 SHA；这不代表游戏已完成录制或出分。
- G035 最初仅见 native exit timeout。未携带正式 RemoteControl 参数的隔离录制成功不能证明正式路径正常；带相同参数复现到了 `USoundWaveProcedural::GeneratePCMData` 的数组越界及 `FAsyncDecodeWorker` 栈，见 `diagnostic_g035_formal_ports/take/unreal.log`、`hang_sample.txt`。
- 对本例共享 procedural wave 在创建后设 `bCanProcessAsync=false`，保留原PCM、采样率、频率、音量及全部 playback 调用。仅作为本例已审查的调度兼容修复，不自动推广。专用计划 `g035_audio_compat/compat_plan.json` 独立绑定，不改已验收其他项目的计划 SHA。
- G035 新计划真实编译/admission 通过；相同动作、采帧计划、正式端口的隔离录制完成180/180帧并正常退出，见 `diagnostic_g035_audio_sync/take/result.json`、`verification.json`、`cleanup.json`。静态独立审查见 `g035_audio_review_response.txt`。未单独证明可听音效时序完全等价；诊断录制不代替正式评估 take，不导入分数。

## 续跑

`supervisor.py` 使用各 row 的 plan 环境覆盖，并同时更新父进程环境与 evaluator 子进程环境，避免 selection() 读取错误计划。续接 G030、G055、G060、G035，跳过既有完整分（包括G040）；与Opus最多两个 evaluator，共用单引擎锁。CLI仍0.166.0；Sol planner/judge，普通两次/direct一轮；20GiB停线。每30分钟落盘阶段/当前run分数，工具错误保留status、原文、日志并继续下一例。运行状态须现场核验，不能把本记录当作已经全部出分。
