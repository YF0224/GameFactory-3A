# Eval 故障模式速查

提炼自实战经验，覆盖所有引擎（Unity / UE5 / Godot / Three.js）eval 链路中常见的工具链故障、模型请求故障和项目启动故障。每项列出识别方式和处置原则，不含内部批次或历史运营细节。

---

## 一、链路故障分类速查表

| 现象 | 先查 | 处置 |
|---|---|---|
| `HARNESS_ERROR` | `status.json` → `error`；`record_error.json` | 工具链故障，第二节处理 |
| `Non-frozen trigger mode` | judge 输出的 trigger 字段 | 判词输出不合法，见 F01 |
| `Basic BUG needs real observed counterexample` | basic_function.evidence 是否有真实 FRAME/STATE | 判词引用不足，见 F02 |
| `measured judge request exceeds versioned transport limits` | 请求构造阶段 | 源码/帧超限，见 F03 |
| `JSONDecodeError: Unterminated string` | JSONL 分行方式 | Unicode 被 splitlines 误拆，见 F04 |
| capture slot busy / GUI slot busy | 全局引擎锁 `A3GAME_EXCLUSIVE_ENGINE` | 等锁释放，不要并发占同一槽位 |
| UE `UE native admission failed` + 编译错误 | `ue_admission*/build.json` 和编译日志 | 项目启动故障，第三节处理 |
| Unity `error CS*` / `Scripts have compiler errors` | `import.log`、`import_result.json` | 项目启动故障，第三节处理 |
| 游戏崩溃 / 死亡 / 低分 | — | 产品表现，不是故障，保留原貌出分 |
| `missed its predeclared capture slot` | capture 调度 | 评估工具故障，记录，不修 |
| schema / 解析错误 | model_calls 目录下 events.jsonl | 见 F01 / F04 |
| `OUTPUT_TRUNCATED` | 模型响应长度 | 见 F05（分片恢复） |
| TIMEOUT / 502 / 503 | events.jsonl 是否还在增长 | 见 F06 |
| 图片送达后尺寸/RGB 变化 | 解码 retained input_image 核像素 | 见 F07 |
| `plan needs ... more than budget` | plan.json budgets | 评估工具配置问题，记录 |

---

## 二、模型请求与传输故障

### F01 判词输出不合法（trigger / BUG / NORMAL）

**识别**：judge 返回的 `trigger_mode` 不在冻结枚举内，或 `BUG` 没有真实运行反例，或 `NORMAL` 只引用 SRC/ACTION 而无 FRAME/STATE/EVENT。

**原则**：
- schema 字符串合法 ≠ 逐项合同合法
- `BUG` 要求真实观察到反例（错误对象、崩溃、错误行为）；源码怀疑、未覆盖、spec_deviation 不够
- `NORMAL` 要求有真实运行效果的引用；ACTION 证明输入，不证明效果
- 不手填模式、不放宽 enum、不把未覆盖当产品 bug

**处置**：一次明确反馈（提醒正确规则），由模型独立重判；单次纠正再次失败则停，保留原失败材料。

---

### F02 源码 / 帧超限

**识别**：`measured judge request exceeds versioned transport limits`；历史上限假设（如"64 张"）已证伪，不能沿用。

**处置顺序**：
1. 先测真实完整请求大小与冻结限制，不用本地估算代替
2. 完整源码有序分段，保存原 body/wire、分段顺序/边界/SHA
3. 每个独立评分任务须取得全部源码/必要上下文、全部预声明帧，保留同一会话且无 compaction
4. 预准备阶段失败是本地前置问题，不是模型容量结论

**禁止**：裁剪源码、缩小帧、提高冻结上限、原样无限重试。

---

### F03 JSONL 合法 Unicode 被 splitlines 误拆

**识别**：intake 返回正确 chunk/SHA、exit0，本地 `verify_session` 却报 `JSONDecodeError: Unterminated string`。

**根因**：JSONL 应按 LF 分行，但 `str.splitlines()` 还会切 U+0085 / U+2028 / U+2029，这些可能是合法 literal 键，不是模型截断。

**处置**：只按 `\n`（LF）分行；不重发成功段，不删 call 目录。

---

### F04 OUTPUT_TRUNCATED / 输出截断

**识别**：响应中途截断，schema 解析失败，或 accepted 分区不完整。

**处置**：
- 保存原输出，不补写结尾
- 按正式资格化拆分：复用已 accepted 的分区，仅补缺失部分
- 合并时核全部原判项、引用、冲突和完整上下文

**禁止**：手填结尾、丢弃 accepted 分区、原样无限重发。

---

### F05 TIMEOUT / 502 / 503 / 无完整响应

**识别**：final 只留 thread/turn started，invocation 为 TIMEOUT 无 response。

**处置**：
1. 先查真实请求状态、迟到输出、events/预算；不仅凭超时确认根因
2. 保留全部成功 intake，最后合格阶段就是当前边界
3. 若需新路由，先正式实质修复，精确绑定父失败，回归后再继续
4. 外部服务不可用时保存可恢复状态，推进离线工作，不计为产品零分

**禁止**：原样重发超时请求；以超时推断容量根因。

---

### F06 图片实际被缩放（文件 SHA 正确但像素变化）

**识别**：文件 SHA、CLI 参数、actual_delivery 一致，retained `input_image` 却尺寸/RGB 改变。

**根因**：CLI 默认图片预处理会缩放，仅凭文件级审计无法发现。

**处置**：解码 retained data URL，逐图比对尺寸/RGB；不能用文件相等 / exit0 / registry 登记宣称完整送达。

---

### F07 package-lock 本地插件路径随评估副本变化（Three.js / npm）

**识别**：作者 `package.json` 精确字节不变，`file:` 指向同一 A3GamePlayable 插件，但 lock 的 link 路径键/resolved 变化。

**处置**：证明路径等价；不 npm update、不改 package/alias、不换插件。已有 attempted capture 时保留并拒绝重录，从原 record 续 judge。

---

## 三、项目启动 / 编译故障（评估副本内修复）

**只在评估副本 `runtime/project` 内工作，原始交付只读。**

### 允许的修复范围

| 类型 | 说明 |
|---|---|
| 工程/环境配置 | `.uproject`、`*.Build.cs`、`Config/*.ini`、Unity `ProjectSettings/`、`Packages/manifest.json`、`*.asmdef` |
| 编译兼容（不改行为） | 缺 `#include` / `using`；API 改名（等价新 API）；显式类型转换；`const`/`override`/`virtual` 修饰；未初始化声明；重复定义限定名 |
| 空壳文件 | 只为修上面问题而新增的引擎模板文件（如缺失的 Target.cs、模块入口） |

### 禁止的修复范围

- 改任何玩法逻辑、数值、胜负条件、AI、关卡、UI 文本/行为
- 改场景/关卡/预制体/资源文件（`.unity`、`.umap`、`.uasset`、材质、音频等）
- 删除或注释作者代码、改成空实现、`#if 0`
- 改评估工具 / adapter / 录制插件（`A3GamePlayable`、`GameFactory3A*`）
- 联网下载、安装第三方包
- 碰 `Library/`、`Intermediate/`、工作目录外的任何东西

### 诊断流程

1. 读失败信息里的日志路径，找**最早**的真实错误（编译器第一条 error）
2. 判断是否属于"允许"的类型；做最小改动，每处只修一个错误
3. 不在此运行引擎（构建/导入由评估流程重新执行）

无安全可修的问题时：不做任何修改，记录 `not_repairable` 和原因。

---

## 四、发现新故障时的处理流程

1. 确认不是已有 `pipeline/eval/repair/` 脚本能处理的故障
2. 保存根因、最后合格阶段、失败的精确证据
3. 写 `<engine>_<场景>_recovery.py`，注册到 REGISTRY（见 `repair/README.md`）
4. 切换到其他可推进项目，回访后用新脚本重试
5. 追加到本文件底部（格式同上），标注引擎、阶段和验证状态

---

## 五、通用原则

- **最后合格阶段优先**：有 accepted 结果就从它续，不重录已合格实录
- **保留原材料**：失败/claim/次数/原输出不删；实质修复必须绑定父失败
- **工具故障 ≠ 产品失败**：`HARNESS_ERROR` 不计为产品零分，不填占位0
- **不无变化重试**：同样的输入无限重发只浪费预算；必须有实质修复才能重试
- **约10分钟排错时间片**：不是永久放弃资格；根因清楚后回访继续
