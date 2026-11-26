# Eval 故障处置手册

agent 在 eval 链路中遇到问题时查这份手册。按现象找对应节，从最后合格阶段续接。

---

## 一、先做：链路状态检查

**每次接管或遇到问题，先做这些，不要直接动手修：**

1. 读 `status.json` → `error` 字段
2. 读 `takes/<k>/record/record_error.json`
3. 读引擎日志：
   - UE：`takes/<k>/record/native/take/unreal.log`、`runtime/ue_admission*/build.json`
   - Unity：`takes/<k>/record/import.log`、`import_result.json`
4. 找**最后合格阶段**：有完整有效发布 → 复用；有合格 record → evidence/judge；有合法 plan → record；有作者入口 → plan
5. 判断问题属于哪一类（见第二节）

---

## 二、问题分类

| 现象 | 类别 | 处置 |
|---|---|---|
| `HARNESS_ERROR` | 工具链故障 | 第三节 |
| `Non-frozen trigger mode` | 判词输出不合法 | F01 |
| `Basic BUG needs real observed counterexample` | 判词引用不足 | F02 |
| `measured judge request exceeds versioned transport limits` | 请求超限 | F03 |
| `JSONDecodeError: Unterminated string` | JSONL 分行错误 | F04 |
| capture slot busy / GUI slot busy | 引擎锁冲突 | 等待，不并发 |
| UE 编译错误 / 缺插件模块 | 项目启动故障 | 第四节 |
| Unity `error CS*` / 缺包 / 场景打不开 | 项目启动故障 | 第四节 |
| 游戏崩溃 / 死亡 / 低分 | 产品表现 | 不处理，保留原貌出分 |
| `OUTPUT_TRUNCATED` | 传输截断 | F05 |
| TIMEOUT / 502 / 503 | 服务故障 | F06 |
| 图片 SHA 正确但像素变化 | 图片被缩放 | F07 |
| package-lock 路径变化（Three.js/npm） | 本地插件路径漂移 | F08 |
| `EXACT_RUNTIME_INTAKE_COMPLETE` schema 拒绝 | 回执 enum 错误 | F09 |
| `Incomplete response returned, reason: unknown` | 响应不完整 | F10 |
| `Recorded plan native import bytes differ` | 录后派生来源不匹配 | F11 |
| `Author gameplay changed outside exact device-read translation` | SHA 摘要方式不一致 | F12 |
| `Unreviewed isolated migration changes` | 隔离迁移审查失败 | F13 |
| `Preserved EVENT wire receipt conflicts with current source` | 并发 EVENT 校验冲突 | F14 |
| `max_output_tokens` 截断 / schema 形状错误 | 输出截断或格式错 | F15 |
| `Cannot uniquely bind input handler setting` | 输入后端字段缺失 | F16 |
| `Operation not permitted` cleanup 失败 | 清理权限错误 | F17 |
| `NORMAL lacks genuine functional/processing proof` | NORMAL 引用不足 | F18 |
| `scope/final` 路径缺失 | 路径定位错误 | F19 |
| `Vite three/addons ENOENT` | Vite alias 阻塞 | F20 |
| 缓存扫描 `ReferenceScanDeferred` | 超大元数据阻塞扫描 | F21 |
| 大型报告占用磁盘 | 诊断报告过大 | F22 |

---

## 三、工具链故障：写恢复脚本

### 3.1 诊断原则

- 从最早的失败定位根因，不猜测
- 判断是否属于"可修复"范围（见 `pipeline/eval/repair/README.md`）
- 做最小改动，每处只修一个错误

### 3.2 写脚本

在 `pipeline/eval/repair/` 下新建 `<engine>_<场景>_recovery.py`：

```python
from pathlib import Path

DESCRIPTION = "一句话：解决什么问题、适用条件"
ENGINES = ["ue5"]          # ["unity3d"] / ["godot"] / ["three_js"] / ["*"]
ERROR_PATTERNS = ["关键词"]

def apply(out: Path, **kwargs) -> dict:
    """返回 {"ok": bool, "action": str, "detail": str}"""
    ...
```

在 `__init__.py` 的 `REGISTRY` 里加一行后验证：

```python
from pipeline.eval.repair import describe
print(describe())
```

### 3.3 不能修的情况

以下情况停止写脚本，记录为阻塞：
- 作者交付文件真实缺失
- 修复需要改玩法逻辑、数值、AI、关卡、资产
- 需要联网或外部服务但不可用
- 修复需要改评分语义

---

## 四、项目启动/编译修复

**只在评估副本 `runtime/project` 内工作，原始交付只读。**

### 允许

- 工程/环境配置：`.uproject`、`*.Build.cs`、`Config/*.ini`、Unity `ProjectSettings/`、`Packages/manifest.json`、`*.asmdef`
- 不改变行为的编译兼容：缺 `#include`/`using`、API 改名（等价新 API）、类型转换、`const`/`override`
- 只为修上面问题而新增的引擎模板文件

### 禁止

- 改玩法逻辑、数值、胜负、AI、关卡、UI 文本
- 改场景/关卡/预制体/资源文件
- 删除或注释作者代码、改成空实现
- 改评估工具 / adapter / 录制插件
- 联网下载、安装第三方包
- 碰 `Library/`、`Intermediate/`、工作目录外任何东西

### 做法

1. 读失败日志，找**最早**的真实错误
2. 判断是否属于允许类型；做最小改动
3. 不在此运行引擎
4. 修不了时返回 `not_repairable`，不做任何改动

---

## 五、逐类故障处置

### F01 判词输出不合法（trigger / BUG / NORMAL）

**识别**：
- `Non-frozen trigger mode`：trigger_mode 不在冻结枚举内
- `Basic BUG needs real observed counterexample`：BUG 没有真实运行反例
- `NORMAL lacks genuine functional/processing proof`：NORMAL 只引用 SRC/ACTION

**原则**：
- schema 字符串合法 ≠ 逐项合同合法
- BUG 要求真实观察到反例（错误行为、崩溃）；源码怀疑、未覆盖不够
- NORMAL 要求有真实运行效果的引用；ACTION 证明输入，不证明效果
- UNVERIFIED 仍须遵守冻结 enum

**处置**：一次明确反馈（提醒正确规则），由模型独立重判。单次纠正再次失败则停，保留原失败材料。不手填模式、不放宽 enum、不把未覆盖当产品 bug。

---

### F02 源码/帧超限

**识别**：`measured judge request exceeds versioned transport limits`

**处置顺序**：

1. 先测真实完整请求大小与冻结限制，不用本地估算代替
2. 完整源码有序分段，保存原 body/wire、分段顺序/边界/SHA
3. 每个独立评分任务须取得全部源码/必要上下文、全部预声明帧
4. 保留同一会话且无 compaction
5. 预准备阶段失败是本地前置问题，不是模型容量结论

**禁止**：裁剪源码、缩小帧、提高冻结上限、原样无限重试。

---

### F03 JSONL Unicode 被 splitlines 误拆

**识别**：intake 返回正确 chunk/SHA、exit0，本地 `verify_session` 却报 `JSONDecodeError: Unterminated string`

**根因**：`str.splitlines()` 会切 U+0085/U+2028/U+2029，这些可能是合法 literal 键，不是模型截断。

**处置**：只按 `\n`（LF）分行；不重发成功段，不删 call 目录。

---

### F04 OUTPUT_TRUNCATED / 输出截断

**识别**：响应中途截断，schema 解析失败，或 accepted 分区不完整。

**处置**：

- 保存原输出，不补写结尾
- 复用已 accepted 的分区，仅补缺失部分
- 合并时核全部原判项、引用、冲突和完整上下文

**禁止**：手填结尾、丢弃 accepted 分区、原样无限重发。

---

### F05 TIMEOUT / 502 / 503 / 无完整响应

**识别**：final 只留 thread/turn started，invocation 为 TIMEOUT 无 response。

**处置**：

1. 先查真实请求状态、迟到输出、events/预算；不仅凭超时确认根因
2. 保留全部成功 intake，最后合格阶段就是当前边界
3. 若需新路由，先正式实质修复，精确绑定父失败，回归后再继续
4. 外部服务不可用时保存可恢复状态，推进离线工作

**禁止**：原样重发超时请求；以超时推断容量根因。

---

### F06 图片实际被缩放（文件 SHA 正确但像素变化）

**识别**：文件 SHA、CLI 参数、actual_delivery 一致，retained `input_image` 却尺寸/RGB 改变。

**根因**：CLI 默认图片预处理会缩放，仅凭文件级审计无法发现。

**处置**：解码 retained data URL，逐图比对尺寸/RGB。不能用文件相等/exit0/registry 登记宣称完整送达。

---

### F07 package-lock 本地插件路径随评估副本变化（Three.js/npm）

**识别**：作者 `package.json` 精确字节不变，`file:` 指向同一 A3GamePlayable 插件，但 lock 的 link 路径键/resolved 变化。

**处置**：证明路径等价；不 npm update、不改 package/alias、不换插件。已有 attempted capture 时保留并拒绝重录，从原 record 续 judge。

---

### F08 Unity M：回执 enum 失败（`EXACT_RUNTIME_INTAKE_COMPLETE` 被拒）

**识别**：runtime 最后一段已由 app-server 完成，但返回 `EXACT_RUNTIME_INTAKE_COMPLETE`，原 schema 仅接受 `EXACT_RUNTIME_CHUNK_RETAINED`。

**适用条件**：只有最终 runtime chunk 的单字段字符串回执 enum 失败；实际 turn 已完成，完整原始 chunks 顺序、继承源码/原像素会话、无 compaction/工具行为及剩余上下文容量均通过正式校验。

**处置**：

- 同一 thread 追加一次只纠正回执的调用，schema 保持原样，不重发/摘要/压缩原件
- 保留失败 snapshot、请求/response/schema/RPC 的 SHA
- 建立不可覆盖 `receipt_correction.json`，最多一次新调用
- 恢复次数耗尽、绑定漂移、不同 thread、响应缺失或不合法时停止，不原样无限重试

**注意**：此方案也适用于任意单个 runtime chunk（不限最后一个），整个 group 最多一次纠错。

---

### F09 `Incomplete response returned, reason: unknown`

**识别**：RPC turn/completed 返回 failed，error.message 精确为 `Incomplete response returned, reason: unknown`，且无完整 response。

**原则**：unknown 不能改称 max_output 截断。

**适用条件**：已保存对应 thread/turn、原请求/schema/events、保留会话且无 accepted 该任务的录后恢复。

**处置**：

- 仅一次同会话 exact-equivalent 共享 schema，扩展还原全部原约束
- 保存原失败，原 validator、完整源码/原像素及冻结上限不变
- 不能声称恢复验证或一般扩批准入

---

### F10 `Recorded plan native import bytes differ`（录后派生来源不匹配）

**识别**：Editor 对 `UserSettings/EditorUserSettings.asset` 增加最近场景偏好；receipt 能精确逆还原全部原件字节，隔离 snapshot policy 明确省略该路径，但录后 plan 绑定要求 native recorded SHA。

**处置**：

- 只适用于精确 receipt、原件/实录/derived SHA、snapshot policy 和完整来源迁移同时匹配的路径
- 材质、URP asset 和其它内容仍须匹配实录，不外推一般豁免
- 不重录、不填工具零分
- 失败已部分物化时：保留全部旧失败/claim/次数及 partial，以最新父失败建立不可变后继

---

### F11 `Author gameplay changed outside exact device-read translation`（SHA 摘要方式不一致）

**识别**：隔离 native 输入迁移报此错误；原 source 完整 SHA 绑定未变、after 字节匹配、精确设备读取转换文本相等，但 change.before_sha256 与原文件 raw SHA 不同。

**根因**：migrator 用 `Path.read_text()` 读取 CRLF 源码，hash 计算通用换行转 LF 的文本摘要；input_adapter.verify 却用 sha(before) 原始字节摘要比较。

**处置**：

- 同时核 raw 和 read_text.UTF8 摘要、CRLF 数量、完整原 source binding
- 不凭报错把它当作者改玩法
- 不手改既有 receipt 或重新迁移以绕 guard
- 在保护原 raw source 绑定前提下，明确区分 byte/text 哈希语义

---

### F12 `Unreviewed isolated migration changes`（隔离迁移审查失败）

**识别**：evidence 在模型调用前报此错误，通常涉及 `UserSettings/EditorUserSettings.asset`。

**根因**：Editor 在实录中新增最近场景偏好；原件/实录只有 m_ConfigSettings 下 RecentlyUsedSceneGuid-0 三行插入；隔离 snapshot 合法省略 UserSettings。

**处置**：

- 严格逆还原全部原件字节，仅同 tag/schema、首个最近场景 key 及 hex value/flags0
- 额外设置、多个 key、不同路径/原件/Editor/清理均拒绝
- 不重录、不填产品零分

---

### F13 并发 EVENT 回执校验冲突

**识别**：新的 Unity 两列阶段在 admission 历史已发布结果重核时，`event_wire.persist` 抛出 `Preserved EVENT wire receipt conflicts with current source`。

**根因（候选）**：历史 evidence 使用共享发布锁，packet 重建仍会调用 persist 对相同现有文件无条件 write_bytes；两个校验器并行时可能有截断/读取竞态。

**处置**：

- 先只读按每份 equivalence 的 source、原 physical lines 和 encoding 重建完整 wire，核原 source SHA 和两个完整回执字节
- 确认在途共享历史校验器状态后，从原 identity 合格实录**串行**正式 evidence 续接
- 不删锁或历史回执，不再次 native
- 若稳定重现真正差异：保存差异并修正式链、精确旧代码与 producer 绑定、定向并发回归及真实 Unity E2E

---

### F14 Unity M：输出截断或 schema 形状错误

**识别**：Gameness 完整 judge 响应实际为 `{"checks":[...]}` 而非 dict，或 `max_output_tokens` 明确截断。

**处置**：

- 原 schema 拒绝后，仅对此精确已完成响应限一次同会话完整 schema 纠错
- 仍须原完整证据/源码/原像素保留、父失败/生产 SHA 绑定、无 compaction、剩余容量合格
- 不本地补字段或推断分数
- 真实完整 judge 响应出现后再计算/持久化/发布

---

### F15 Unity M：回执上下文包装与连续整数 schema 等价传输

**识别**：原件回执恢复因实际 session 包含 AGENTS/environment 及图片开闭包装而被过严字符串等式挡住；或连续整数 enum 在 schema 反复展开导致超限。

**处置**：

- 回执恢复：仅识别明确 envelope，要求原完整 prompt 与图片顺序精确一致，原 snapshot 字节前缀保留、同 thread 两轮、无 compaction
- 整数 enum 压缩：只在所有成员为真正整数且集合**完全连续**时替换为等价 minimum/maximum；有缺口的 enum 原样保留
- 每处保留原 enum SHA、位置、计数与边界
- 不重发已 accepted 原件或 runtime chunks，不提高窗口/帧/事件上限

---

### F16 Unity ProjectSettings 缺输入后端字段

**识别**：`Cannot uniquely bind input handler setting`；原始 PlayerSettings 字段缺失且保存的隔离副本逐文件 SHA 完全匹配。缺失不是错误原值 0 的证明。

**处置**：

- 仅在唯一 PlayerSettings 映射内插入缩进 `activeInputHandler: 1`，原件只读
- 保留其它字段字节，拒绝重复/格式异常字段
- 真实原生成功后才允许通过正式 admission 扩批
- 单测通过不能视作新能力

---

### F17 录后清理失败（`Operation not permitted`）

**识别**：Editor 已 exit0、原 input/view teardown 通过，但 group/detached 核验记录 EPERM，原 capture 不合格并持久 stop。

**处置**：

- 保留原 cleanup/verification 不改，`capture_accepted=false`、`scoring_authorized=false`
- 不能把事后退出认证成原录制通过
- 不证明 EPERM 根因或 adapter 已修复
- 新 native 仍须匹配完整 production admission
- 旧实录禁止用于出分

---

### F18 `NORMAL lacks genuine functional/processing proof`

见 F01（NORMAL 引用不足）。

---

### F19 scope/final 路径缺失

**识别**：找不到 scope/final/config 路径，或 nested/后代/owner 混淆。

**处置**：

- 由既有 publication.score_file 和精确身份/祖先/来源找证据 root
- 冻结 scope/修订与 publication 可能属于父 owner
- 顶层 auth 只有 intake 不证明有效后代没有 final
- 不复制 scope、移动 run、填造 invocation/auth 或重录

---

### F20 Vite three/addons ENOENT

**识别**：`ENOENT .../node_modules/three/addons/controls/PointerLockControls.js`，但 `examples/jsm/...` 真实存在。

**根因**：作者 alias `three: path.resolve(here, 'node_modules/three')` 前缀替换绕过 exports；不同于包没安装。

**处置**：

- 最后合格为冻结 plan，无合格 record
- 只有固定远端同原交付确有下载遗漏才能找回
- 否则保留作者配置阻塞：不能改 alias、补 addons symlink 或换插件冒充原件
- 保留阻塞事实，继续其他可推进项目

---

### F21 缓存扫描 `ReferenceScanDeferred`

**识别**：`receipt.status=COMPLETE`、所有候选 `PRESERVED`、实际删除 0，`reference_scan.scan_complete=false`，错误为 `ReferenceScanDeferred('Metadata exceeds bounded scan size; no deletion authorized')`。

**根因**：当前 `native_scored_cache.reference_scan` 对大于 `MAX_REFERENCE_FILE_BYTES` 的历史元数据停止扫描；即使 `hits=[]` 也没有证明引用已查全。

**处置**：

- 保留超大原日志、原缓存、失败及全部旧/新扫描回执
- 不删除日志或旧扫描、不排除引用根、不提高冻结上限
- 不把 COMPLETE 当已删，或手动 rmtree 绕过资格
- 记录为阻塞，继续不依赖该缓存回收的其他工作

---

### F22 大型诊断报告占用磁盘

**识别**：数 GiB 的历史 `reference_scan.json` / `reference_classifications.json` 被证据链引用，不能作为无引用缓存删除。

**处置（文件系统无损压缩，仅限静止文件）**：

适用条件：静止、无打开句柄、单硬链接、无已有特殊 resource fork 的生成诊断文件。不修改作者原件、judge 传输或评分。

1. 核所属发布锁和写入者
2. 保存完整 SHA/大小/mtime/xattrs 及分配块数
3. 估算临时空间并留 8 GiB
4. 仅在同目录新临时文件用系统 LZFSE 按 64 KiB 块压缩
5. 本轮保持压缩 resource 小于 2 GiB 格式边界，超界即保留原文件
6. 先完整读回核 SHA、用户 xattrs 与大小，再重核原文件身份/SHA 和无打开句柄
7. 持锁原子替换同路径；替换后再完整读回核 SHA 与实际分配块
8. 失败只清自己的临时副本

**注意**：F22 只减磁盘分配，不解除 F21 的扫描问题。

---

## 六、Unity M 特有故障

### Unity M：production binding 漂移导致 admission 失败

**识别**：Unity M 两列正式 admission 按完整 production bindings 的规范化 JSON SHA 寻址；接管时找不到当前 SHA 的 admission，但 workspace 中有早期合格 admission 和/或已发布列。

**根因**：旧 `unity-m-complete-two-column-admission.v1` 的 `verify_transition` 仅接受五个指定 gate 文件的 `GATE_ONLY_NO_SCORING_OR_TRANSPORT_CHANGE` 差异；新增模块（input adapter、evidence/judge/runtime、materialization/runtime-reuse）不能伪装为 gate-only。

**处置**：

1. 只读计算全 production SHA 和差集
2. 归档待改正式 verifier 的精确旧字节
3. 保留每个旧 producer/publication 的历史绑定
4. 建立允许 identity/column/operation 的最小 requalification 范围
5. 运行正式 targeted regression
6. 再用未完成的合格目标列执行真实 Unity E2E
7. 完整完成后才可生成 current-SHA admission

**禁止**：清 claims、重复 native、重判已有有效列；把测试通过当 E2E 完成。

---

### Unity M：自定义 assembly csproj IDE 变换

**识别**：在 F11（Build 快照排除）已证明 Build 遗漏后，实际 evidence 继续于 `changed_authored` 失败；5 个自定义 assembly csproj 仅输入 define 切换及已知输入 shim 引用索引变化，`.vscode` 仅默认 solution 选择。

**处置**：

- 对任意根 csproj 精确逆还原输入 define 及已知引用增量，其余 XML 须字节相同
- `.vscode` 仅单一字面字段替换，前后 solution 真实存在
- 仍仅该既有实录 evidence/judge，未通过真实两列 publication+sync 前不得扩 native/批量

---

### Unity M：长资格核验后共享原生租约竞态

**识别**：资格核验耗时后，外来会话取得共享队列 EX 租约；capture 的一次 LOCK_NB 抛出 `BlockingIOError`。

**处置**：

- 以 lsof/真实祖先进程确认归属，锁文件内容旧 PID 不作证明
- 以一个 workspace native worker 有界等待真实 flock（1200 秒、5 秒检查）
- 获取共享租约后仍执行原 safety/source/pin/Editor/disk/record/cleanup 资格
- 不绕外来锁、不终止其他会话
- 外来锁保留，不绕锁

---

## 七、通用原则

- **最后合格阶段优先**：有 accepted 结果就从它续，不重录已合格实录
- **保留原材料**：失败/claim/次数/原输出不删；实质修复必须绑定父失败
- **工具故障 ≠ 产品失败**：`HARNESS_ERROR` 不计为产品零分，不填占位 0
- **不无变化重试**：同样的输入无限重发只浪费预算；必须有实质修复才能重试
- **约 10 分钟排错时间片**：不是永久放弃资格；根因清楚后回访继续
- **磁盘**：每次启动引擎前 `df -h /`，低于 20 GiB 停下汇报，始终保留 8 GiB
- **并行资源**：`A3GAME_EXCLUSIVE_ENGINE=1 A3GAME_GUI_SLOTS=1`，不让两个会话同时占一个录制槽位

---

## 九、UE5 特有故障

### UE01 录制完成后 shutdown 超时

**识别**：UE take 录制期间完整观察窗口和全部输入都已完成，但关闭引擎时 media component teardown 超时，`record_error.json` 显示 shutdown 相关错误。

**根因**：UE 关闭时 media/audio component teardown 耗时超出预算，不是录制本身的故障。

**处置**：

- 核查 take 是否确实完成：全部计划输入都已送达（有回执）、完整观察窗口已经过、exit 请求在全部观察之后
- 如果以上全部满足，使用 `ue_completed_shutdown_recovery.py` 资格化这个 take
- 保留所有原始 record 材料不动，不重录，不改评分

**禁止**：录制不完整（游戏崩溃、startup 失败）时不能用此方案；不删 shutdown 失败证据。

**脚本**：`pipeline/eval/repair/ue_completed_shutdown_recovery.py`

---

### UE02 UE 编译/配置兼容问题

**识别**：UE native admission 失败，`build.json` 显示 C++ 编译错误，或 `unreal.log` 有 `error` 级别编译失败。常见场景：引擎版本升级导致 API 改名、缺 `#include`、`const`/`override` 修饰符不匹配。

**根因**：作者用旧引擎版本写的代码在新版引擎编译失败，不是游戏逻辑问题。

**处置**：

1. 读 `build.json` 找第一条 `error` 行，确认是编译兼容问题（不是缺资产、缺模块）
2. 在评估副本里做最小修改：缺 `#include`、API 改名用等价新 API、类型转换、`const`/`override`
3. 设置 `A3GAME_UE_COMPILE_COMPAT_PLAN` 环境变量指向 SHA 绑定的修复计划，使用 `ue_compile_compat.py`

**禁止**：改任何游戏逻辑、改 `.uasset`/`.umap`、删作者代码、改评分。

**脚本**：`pipeline/eval/repair/ue_compile_compat.py`

---

### UE03 UE 录制插件缺失（missing recorder）

**识别**：UE admission 失败，报 `recorder not found`、`A3GamePlayable plugin not loaded` 或类似插件缺失错误。

**根因**：作者提交的 `.uproject` 里没有声明 `A3GamePlayable` 插件依赖，或插件路径不对。

**处置**：

1. 核查 `.uproject` 的 `Plugins` 数组，确认缺失 `A3GamePlayable` 条目
2. 在评估副本的 `.uproject` 里补上插件声明
3. 使用 admission recovery 脚本，绑定原 plan 和已有 admission 材料，不重新 plan

**禁止**：不改 `Source/` 下任何游戏代码；不删已有 admission 材料；不改评分。

**脚本**：`pipeline/eval/repair/ue_g020_admission_recovery.py`

---

### UE04 UE launch_source 路径不对

**识别**：plan 里的 `launch_source` 指向的 `.uproject` 路径不存在，报 `launch_source <path> does not exist in the project`。

**根因**：作者交付的项目目录结构与 plan 预期的入口路径不一致（如 `.uproject` 在子目录里而不是根目录）。

**处置**：

1. 确认 delivery 里实际的 `.uproject` 位置
2. 使用 `ue_g025_launch_path_recovery.py`，只修改 plan 的 `launch_source` 字段为正确路径
3. 绑定已失败的原始 plan SHA，不重新调用 planner

**禁止**：不移动项目文件；不改游戏代码；不新增 planner 调用。

**脚本**：`pipeline/eval/repair/ue_g025_launch_path_recovery.py`

---

### UE05 UE take1 工具故障后续跑 take2

**识别**：take1 因工具链故障失败（不是游戏崩溃），有完整 plan，需要续跑一次 take2。

**根因**：take1 的失败来自 admission 或 capture 工具链问题，不是游戏本身的问题，原 plan 仍然有效。

**处置**：

1. 确认 take1 失败原因是工具链问题（不是游戏崩溃、UI 完全无响应）
2. 保留 take1 的全部材料（plan、失败 record、admission 材料）
3. 使用 `ue_g025_take2_recovery.py`，只跑一次 take2，不重新调用 planner

**禁止**：不删 take1 材料；不改评分；take2 失败后不再重试。

**脚本**：`pipeline/eval/repair/ue_g025_take2_recovery.py`

---

### UE06 UE 缺少 Editor target 文件

**识别**：UE admission 失败，报 `Editor target not found` 或 `{ProjectName}Editor.Target.cs missing`。

**根因**：作者未提供 Editor target 文件，UE 编译时找不到 Editor 入口。

**处置**：

1. 确认 `Source/` 下缺 `{ProjectName}Editor.Target.cs`
2. 在评估副本里新增一个标准 Editor target 文件（引擎模板内容，不写任何游戏逻辑）
3. 使用 `ue_g035_target_recovery.py`，绑定原 plan 和已有 admission 材料

**禁止**：不改任何游戏代码；不改 `.umap`/`.uasset`；不改评分。

**脚本**：`pipeline/eval/repair/ue_g035_target_recovery.py`

---

## 八、发现新故障时的流程

1. 确认不是已有 `pipeline/eval/repair/` 脚本能处理的故障
2. 保存根因、最后合格阶段、失败的精确证据
3. 写 `<engine>_<场景>_recovery.py`，注册到 REGISTRY
4. 切换到其他可推进项目，回访后用新脚本重试
5. 在本文件底部追加一节（格式同上），标注引擎、阶段和验证状态
