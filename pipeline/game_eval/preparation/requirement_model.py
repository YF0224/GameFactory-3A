"""Parse one game case into a requirement inventory + extractable authoring facts.

The case's ``general_requirement.txt`` (and its declared variants such as
``general_requirement_threejs.txt``) is the primary authority. Every numbered
requirement anchor (``- S01 …``, ``- M02 …``, ``- W03 …``) is inventoried with
its source file, section, anchor line and full text; nothing is invented —
sections/anchors that do not exist are recorded as gaps, never fabricated.

The extracted ``GameFacts`` (key bindings, lifecycle states, runtime events,
HUD items, camera rules, story elements, cutscene list, sound list, reference
bindings, per-kind task inventory) drive the deterministic authoring engine;
every fact records the requirement id (or file) it was extracted from so the
generated rubric stays traceable to the original requirement.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: canonical zh→shared-verb map for the recorders' action vocabulary. The
#: shared verbs are frozen (wait/move/look/jump/attack/interact/dash/pause/
#: restart); everything else maps to the closest recorded verb.
_ZH_ACTION_VERBS: dict[str, str] = {
    "跳跃": "jump", "跳": "jump", "跳跃/滑铲": "jump", "起跳": "jump",
    "滑铲": "dash", "滑": "dash", "冲刺": "dash", "闪避": "dash", "翻滚": "dash",
    "翻面": "dash", "疾跑": "dash", "奔跑": "dash",
    "攻击": "attack", "轻击": "attack", "重击": "attack", "挥击": "attack",
    "蓄力": "attack", "击球": "attack", "开火": "attack", "射击": "attack",
    "出拳": "attack", "格挡": "attack", "防御": "attack", "斩击": "attack",
    "互动": "interact", "交互": "interact", "确认": "interact", "开始": "interact",
    "拾取": "interact", "放置": "interact", "使用": "interact", "对话": "interact",
    "调查": "interact", "技能": "interact", "施法": "interact", "建造": "interact",
    "移动": "move", "前进": "move", "瞄准": "move", "转向": "look", "视角": "look",
    "暂停": "pause", "继续": "pause",
    "重开": "restart", "重试": "restart", "重打": "restart", "重新开始": "restart",
    "等待": "wait", "切换": "look", "全览": "look", "镜头": "look",
}

_ENGINE_ALIASES = {"unity": "unity3d", "unity3d": "unity3d", "godot": "godot",
                   "godot4": "godot", "three.js": "three_js", "three_js": "three_js",
                   "threejs": "three_js", "unreal": "ue5", "ue5": "ue5",
                   "ue4": "ue5", "blender": "blender"}

_ANCHOR_RE = re.compile(
    r"(?m)^(?:-\s+)?([A-Z]{1,4}\d{2,3}(?:\.\d{1,2})?)(?=\u3000|\s|[:：])")
_TABLE_ROW_RE = re.compile(
    r"(?m)^\|\s*([A-Z]{1,4}\d{2,3})\s*\|[^\n]*")
_SUBHEADING_RE = re.compile(
    r"(?ms)^###\s+([A-Z]{1,4}\d{2,3}(?:\.\d{1,2})?)\s*[：:]?\s*(.*?)\n"
    r"(.*?)(?=^###\s+|^##\s+|\Z)")
_SECTION_RE = re.compile(r"(?m)^(?:##\s+|(?=[一二三四五六七八九十]{1,3}、))(.+?)\s*$")
_RANGE_RE = re.compile(r"\[([A-Z]{1,4}\d{2,3})\s*[–—-]\s*([A-Z]{1,4}\d{2,3})\]")
_QUOTED_RE = re.compile(r"「([^」]{1,20})」")
_BACKTICK_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,30})`")


@dataclass
class Requirement:
    requirement_id: str
    source_file: str
    section: str
    anchor: str
    text: str

    def brief(self, limit: int = 160) -> str:
        return self.text.replace("\n", " ")[:limit]


@dataclass
class KeyBinding:
    action_zh: str
    keys: list[str]
    verb: str
    requirement_ids: list[str]
    preconditions: list[str] = field(default_factory=list)

    def key_string(self) -> str:
        return "/".join(self.keys)


@dataclass
class TaskInfo:
    task_id: str
    kind: str                  # 3d_object|3d_scene|tpose|motion|audio|cg_video
    name: str                  # asset_name / cg_name / motion_name
    role: str                  # character|enemy|prop|building|scene|... (best effort)
    prompt: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def image_reference(self) -> str | None:
        return self.raw.get("image_path") or None


@dataclass
class GameFacts:
    """Everything the authoring engine may use — all traceable to the case."""

    title: str = ""
    category: str = ""
    tier: str = ""
    engine: str = ""
    seed: int | None = None
    keys: list[KeyBinding] = field(default_factory=list)          # from I01-like lines
    lifecycle_states: list[str] = field(default_factory=list)     # 「…」 quoted states
    runtime_events: list[str] = field(default_factory=list)        # backticked events
    hud_items: list[str] = field(default_factory=list)             # from I06-like line
    camera_rules: list[str] = field(default_factory=list)          # F01/F02 facts
    story_elements: dict[str, str] = field(default_factory=dict)    # W01.. anchors
    cg_items: list[dict[str, str]] = field(default_factory=list)    # cutscene tasks
    sound_items: list[str] = field(default_factory=list)            # F06 frozen list
    asset_roles: list[str] = field(default_factory=list)             # object asset_name list
    mechanics: list[dict[str, str]] = field(default_factory=list)     # M0x systems
    win_condition: str = ""
    lose_condition: str = ""
    recovery_rule: str = ""
    loop_summary: str = ""
    scope_notes: list[str] = field(default_factory=list)             # N0x notes
    gaps: list[str] = field(default_factory=list)                     # honest extraction gaps
    task_inventory: dict[str, list[TaskInfo]] = field(default_factory=dict)
    reference_files: list[str] = field(default_factory=list)           # case-relative ref paths


#: sections whose heading text marks them for a semantic family
_C1_SECTIONS = ("世界设定", "世界背景", "故事前提", "创作基线", "定位与完整流程",
                "一句话概念", "玩家身份", "玩家角色", "失败代价", "总体循环与目标")
_C2_SECTIONS = ("机制系统", "核心循环", "操作与输入", "流程", "潜行", "证据推理",
                "礼法", "压力来源", "轻度动作", "谜题", "任务与解锁", "选择与结局",
                "对话规则", "抽卡", "转会", "比赛", "成长", "保存与恢复", "机制验收",
                "移动与交互", "条件事件", "居民与关系", "载具与街道", "原创任务",
                "输入、镜头与基础探索", "扫描、潜行与警觉", "队伍、仓库", "购买经济",
                "实时操作", "武器、护甲", "动作与结算", "房间、电脑", "调查笔记",
                "技能、回合", "开局配置", "配置与正式评测边界", "多人同步",
                "干员原型", "证据目录", "任务、解锁与结算", "收集、徽章",
                "关键角色功能表", "角色、动作与场景设计", "技能与恢复", "操作与界面",
                "数值与战斗", "冻结必测场景", "最终生成命令", "阶段重开与历史状态保留")
_G_SECTIONS = ("数值口径", "成功、失败与恢复", "关卡总览", "区域数据", "邻里注意与后果",
               "经济与工作", "时间与生活状态", "存档", "公平性红线", "多轮", "类型、状态",
               "敌人与首领", "失败恢复", "保存、恢复与稳定性")
_C3_SECTIONS = ("内容清单", "关卡与内容", "路段与内容", "车间与内容", "路线与内容",
                "地图、目标", "区域与交付清单", "资产、性能", "六种生灵", "地图、区域与地标")
_Q_SECTIONS = ("演出、镜头与反馈", "美术、声音与 UI", "环境氛围", "外观与视听",
               "UI 与信息", "游戏定位与完整流程", "跨干员克制", "UI、反馈与无障碍")
_ASSET_SECTIONS = ("过场视频", "参考图绑定", "主角与原创外观绑定", "证据目录")
_NOTES_SECTIONS = ("范围与正向能力", "统一口径与冲突处理", "未冻结事项", "最低测试目录",
                   "分阶段验收", "附录", "档位与历史", "复杂度档案", "交付清单",
                   "实现配置", "关键校验点", "跨阶段后果表", "来源稿历史",
                   "使用规范", "AI 产出顺序", "原型范围", "规则优先级")


def parse_engine(text: str) -> str:
    match = re.search(r"(?m)^engine:\s*['\"]?([A-Za-z0-9_.-]+)", text)
    raw = match.group(1).lower() if match else ""
    return _ENGINE_ALIASES.get(raw, raw)


def parse_yaml_header(text: str) -> dict[str, Any]:
    match = re.search(r"(?ms)^```yaml\n(.*?)^```", text)
    if not match:
        return {}
    try:
        import yaml
        data = yaml.safe_load(match.group(1))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — header is informational only
        return {}


def _split_sections(text: str) -> list[tuple[str, str]]:
    """``## heading`` → [(heading, body)] preserving order."""
    out: list[tuple[str, str]] = []
    matches = list(_SECTION_RE.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        out.append((match.group(1).strip(), text[match.end():end]))
    return out


def _section_range_ids(heading: str, body: str) -> list[str]:
    """Requirement ids a section heading declares: ``[P14]`` or ``[S01–S05]``."""
    ids: list[str] = []
    single = re.findall(r"\[([A-Z]{1,4}\d{2,3})\]", heading)
    for req_id in single:
        if req_id not in ids:
            ids.append(req_id)
    match = re.search(r"\[([A-Z]{1,4})(\d{2,3})\s*[–—-]\s*"
                      r"([A-Z]{1,4})(\d{2,3})\]", heading)
    if match:
        prefix, start, prefix2, end = match.groups()
        if prefix == prefix2:
            width = len(start)
            lo, hi = int(start), int(end)
            if 0 < hi - lo <= 40:
                for value in range(lo, hi + 1):
                    req_id = f"{prefix}{str(value).zfill(width)}"
                    if req_id not in ids:
                        ids.append(req_id)
    return ids


def _subheading_items(body: str) -> list[tuple[str, str, str]]:
    """ID-leading and bracket-ID headings, bounded by their heading level."""
    headings = list(re.finditer(r"(?m)^(#{3,6})\s+([^\n]+)", body))
    items = []
    for index, match in enumerate(headings):
        title = match.group(2).strip()
        identifier = re.match(r"([A-Z]{1,4}\d{2,3}(?:\.\d{1,2})?)(?=\s|[:：]|$)", title)
        bracket = re.search(r"\[([A-Z]{1,4}\d{2,3}(?:\.\d{1,2})?)\]", title)
        found = identifier or bracket
        if not found:
            continue
        end = next((h.start() for h in headings[index + 1:]
                    if len(h.group(1)) <= len(match.group(1))), len(body))
        rid = found.group(1)
        items.append((rid, title, body[match.end():end].strip()))
    return items


def _anchor_items(body: str) -> list[tuple[str, str, str]]:
    """Inventory actual definitions; split inline IDs without expanding ranges."""
    items: list[tuple[str, str, str]] = []
    current: list[str] | None = None
    current_id = ""
    fence = ""
    # Only semicolon-separated declarations are split; ordinary cross references
    # (e.g. "按 G03 结算") stay in the original requirement.
    normalized = []
    for line in body.splitlines():
        first = _ANCHOR_RE.match(line)
        if first:
            prefix = re.match(r"[A-Z]+", first.group(1)).group(0)
            line = re.sub(r"[；;]\s*(" + prefix + r"\d{2,3}(?:\.\d{1,2})?)\s+",
                          r"；\n- \1 ", line)
        normalized.append(line)
    body = "\n".join(normalized)
    for line in body.splitlines():
        fence_match = re.match(r"^\s*(`{3,}|~{3,})", line)
        anchor = None if fence else _ANCHOR_RE.match(line)
        heading = not fence and re.match(r"^#{3,6}\s", line)
        if anchor or heading:
            if current is not None:
                items.append((current_id, current[0], "\n".join(current)))
                current = None
            if anchor:
                current_id = anchor.group(1)
                current = [line]
        elif current is not None:
            current.append(line)
        if fence_match:
            marker = fence_match.group(1)
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ""
    if current is not None:
        items.append((current_id, current[0], "\n".join(current)))
    return items


def _anchor_refinement(anchor: str) -> str | None:
    """Anchor-text semantics for ids whose *section* stays ambiguous.

    Only consulted when the section-based family is ``needs-clarification`` —
    a strong anchor signal (art-style wording, HUD wording, numeric-oracle
    wording) resolves the family per id instead of per section.
    """
    if re.search(r"四维仅评|benchmark contract|contract_id|正式四维分数|派生总分",
                 anchor, re.IGNORECASE):
        return "notes"
    if re.search(r"画风|风格|外观|服装|形象|造型|比例|参考图|动画.{0,3}(自然|质量)",
                 anchor):
        return "assets"
    if re.search(r"HUD|标签|可读|清晰|同步|音效|镜头|视角|UI|画面", anchor):
        return "Q"
    if re.search(r"数值|公式|概率|判定|对账|上限|误差", anchor):
        return "G"
    if re.search(r"动作目标|指令|状态|事件|结算|循环|操作|机制", anchor):
        return "C2"
    if re.search(r"世界|背景|身份|动机|剧情|叙事|世界观", anchor):
        return "C1"
    return None


def _section_family(heading: str, prefix: str) -> str:
    """Semantic family for a requirement prefix/section (C1/C2/C3/Q/G/assets/notes).

    The W prefix is only a story family when its section is a 世界设定-style
    section — migrated cases repurpose letters (G045's W01–W08 are the
    delivery-region list), so the heading text decides, never the letter alone.
    """
    if prefix in ("W", "WD") and any(k in heading for k in
                                      ("世界设定", "世界背景", "创作基线")):
        return "C1"
    if any(k in heading for k in _NOTES_SECTIONS):
        return "notes"
    if prefix in ("S",) and any(k in heading for k in _C1_SECTIONS):
        return "C1"
    if any(k in heading for k in _C2_SECTIONS):
        return "C2"
    if any(k in heading for k in _G_SECTIONS):
        return "G"
    if prefix in ("L", "W", "R") and any(k in heading for k in _C3_SECTIONS):
        return "C3"
    if prefix in ("F", "FE", "P", "U", "R") and any(k in heading for k in _Q_SECTIONS):
        return "Q"
    if prefix in ("C", "CG", "VC") and any(k in heading for k in _ASSET_SECTIONS):
        return "assets"
    if prefix in ("A", "REF"):
        return "assets"
    if prefix in ("N", "NR"):
        return "notes"
    # unknown prefix → classify by heading keywords, else needs-clarification
    if any(k in heading for k in _C1_SECTIONS):
        return "C1"
    if any(k in heading for k in _C3_SECTIONS):
        return "C3"
    if any(k in heading for k in _Q_SECTIONS):
        return "Q"
    if any(k in heading for k in _ASSET_SECTIONS):
        return "assets"
    return "needs-clarification"


#: press-modality decorations frozen inside key tokens — the modality is a
#: playable note, not part of the key name the dispatcher must press
_KEY_DECORATIONS = re.compile(r"（(?:按住|长按|单击|双击|连发|点按)）|\((?:按住|长按|单击|双击)\)|"
                              r"^(?:按住|长按|单击|再按|点按)")

#: precondition prefix — ``结算界面 Enter`` names WHERE the key applies
#: (the settlement screen) plus the native key; the two must be separated
#: so the frozen verb→key map stays a real key name
_KEY_PRECONDITION = re.compile(
    r"^([\u4e00-\u9fff]{2,10}(?:界面|画面|菜单|面板|提示|条))\s*(?:\+|\s)\s*(.+)$")


def _normalize_key_token(token: str) -> tuple[str, str | None]:
    """One key token → (clean native key, precondition or None).

    ``结算界面 Enter`` → ``("Enter", "结算界面")``; ``Shift（按住）`` →
    ``("Shift", None)``; ``再按右键`` → ``("右键", None)``. The native key
    stays the game's own declared name — nothing is guessed or replaced.
    """
    token = token.strip()
    precondition: str | None = None
    match = _KEY_PRECONDITION.match(token)
    if match:
        precondition, token = match.group(1), match.group(2).strip()
    token = _KEY_DECORATIONS.sub("", token).strip()
    return token, precondition


def _parse_key_line(line: str, req_ids: list[str]) -> list[KeyBinding]:
    """``Space 或 W/↑＝跳跃；Esc＝暂停`` → key bindings.

    Splits on ；/; then on ＝/=/: the left side names keys, the right side the
    action. Mouse idioms (按住左键/松开/滚轮/鼠标移动) keep their own verb.
    Look/camera actions outrank attack words so a camera toggle never becomes
    an attack press in the trial plan. Precondition prefixes (``结算界面
    Enter``) are split from the native key and recorded on the binding.
    """
    bindings: list[KeyBinding] = []
    for chunk in re.split(r"[；;，]", line):
        chunk = chunk.strip().rstrip("。.")
        if not chunk:
            continue
        parts = re.split(r"[＝=]", chunk, maxsplit=1)
        if len(parts) != 2:
            # G055-style ``E 互动`` (key + space + action, no ＝)
            inline = re.match(r"^([A-Z][A-Za-z]?|WASD|Esc|Enter|Space|Tab|Shift|"
                              r"LMB|RMB|左键|右键|滚轮|鼠标)\s+([一-龥]{2,8})$", chunk)
            if inline:
                left, right = inline.group(1), inline.group(2)
            else:
                continue
        else:
            left, right = parts
        action = right.strip()
        if not action:
            continue
        keys: list[str] = []
        preconditions: list[str] = []
        for piece in re.split(r"[/、或和+]|以及", left.strip()):
            key, precondition = _normalize_key_token(piece)
            if not key:
                continue
            if key not in keys:
                keys.append(key)
            if precondition and precondition not in preconditions:
                preconditions.append(precondition)
        if not keys:
            continue
        verb = "interact"
        if any(k in action for k in ("切换", "视角", "镜头", "俯视", "观察", "全览")):
            verb = "look"
        elif any(k in action for k in ("移动", "瞄准", "走", "前进")):
            verb = "move"
        else:
            for zh, canonical in _ZH_ACTION_VERBS.items():
                if zh in action:
                    verb = canonical
                    break
            else:
                if "鼠标" in action or "移动" in action:
                    verb = "move"
                elif "左键" in action or "点击" in action or "按" in action:
                    verb = "attack"
        bindings.append(KeyBinding(action_zh=action, keys=keys, verb=verb,
                                   requirement_ids=list(req_ids),
                                   preconditions=preconditions))
    return bindings


def _clean_anchor_content(anchor: str) -> str:
    """``- I01 键位：Space 或 W/↑＝跳跃`` → ``Space 或 W/↑＝跳跃``.

    Also strips unnumbered labels (``- 键盘：WASD 移动…``) so body-fallback
    key lines parse the same way as anchored ones.
    """
    match = re.match(r"^-\s*[A-Z]{1,4}\d{2,3}\s+[^：:]{0,8}[：:]\s*(.*)$", anchor)
    if match:
        return match.group(1).strip()
    match = re.match(r"^-\s*[^：:]{1,6}[：:]\s*(.*)$", anchor)
    if match:
        return match.group(1).strip()
    match = re.match(r"^-\s*[A-Z]{1,4}\d{2,3}\s+(.*)$", anchor)
    return match.group(1).strip() if match else anchor.strip()


def _extract_events_text(text: str) -> list[str]:
    """English runtime event names from one requirement/section text.

    Recognizes backticked names, ``crash 事件`` adjacency, and frozen
    slash-separated event lists (``jump_takeoff/波结算/漏怪事件``).
    """
    found: list[str] = []
    for token in _BACKTICK_RE.findall(text):
        if token not in found:
            found.append(token)
    for token in re.findall(r"([a-z][a-z_0-9]{2,30})\s*[、]?\s*事件", text):
        if token not in found:
            found.append(token)
    # mixed zh/en slash lists before 事件 (``wave_start/波结算/漏怪事件``)
    for token in re.findall(r"\b([a-z][a-z_0-9]{2,30}(?:/[一-龥a-z_0-9]+)*/)"
                            r"[^，。；）]*事件", text):
        for part in token.split("/"):
            if re.match(r"^[a-z][a-z_0-9]{2,30}$", part) and part not in found:
                found.append(part)
    for group in re.findall(r"（([a-z][a-z_0-9]{2,30}(?:/[a-z_0-9]{2,30}){1,12})）", text):
        for token in group.split("/"):
            if token not in found:
                found.append(token)
    return found


#: quoted tokens that name player OPERATIONS or UI buttons, not game states.
#: A lifecycle state is a configuration the game is in; 继续/重开/返回菜单
#: are actions the player performs on it. Exact-match plus substring
#: operation verbs — ``全量重开（Enter）`` and ``重打本段（R）`` both carry
#: the restart family and must never become declared states.
_OPERATION_STATE_EXACT = frozenset(
    ("继续", "开始", "下一步", "确认", "取消", "返回", "返回菜单", "重开", "重试"))
_OPERATION_STATE_MARKS = ("重开", "重试", "重打", "重新开始")


def _is_lifecycle_state(token: str) -> bool:
    """Whether one quoted 「token」 names a game state, not an operation.

    Frozen classification rules (uniform for every game):

    * tokens carrying an action-sequence separator (``跳-铲-跳``) or a
      transition arrow (``P1→P2 阶段切换``) name sequences/transitions, not
      states — dropped;
    * restart/return-family tokens (``重开``/``重试``/``重打本段（R）``…) are
      player operations — dropped;
    * bare operation words (``继续``/``开始``/``下一步``…) are buttons —
      dropped; screen names built from them (``开始界面``, the start
      screen) are states and stay.
    """
    if not token or len(token) > 12:
        return False
    if "-" in token or "→" in token:
        return False
    if any(mark in token for mark in _OPERATION_STATE_MARKS):
        return False
    if token in _OPERATION_STATE_EXACT:
        return False
    return True


class CaseModel:
    """One parsed game case: inventory + facts (nothing generated here)."""

    def __init__(self, case_root: str | Path):
        self.root = Path(case_root)
        self.game_id = self.root.name
        general = self.root / "general_requirement.txt"
        if not general.is_file():
            raise FileNotFoundError(f"missing {general}")
        self.general_text = general.read_text(encoding="utf-8", errors="replace")

        # declared variant requirement files — recorded, never replacing the
        # canonical general_requirement.txt
        self.variants: list[dict[str, str]] = []
        for variant in sorted(self.root.glob("general_requirement_*.txt")):
            text = variant.read_text(encoding="utf-8", errors="replace")
            self.variants.append({
                "file": variant.name,
                "engine": parse_engine(text),
                "note": "declared engine variant of the canonical requirement; "
                        "the canonical general_requirement.txt stays the "
                        "authoritative rubric input",
            })

        header = parse_yaml_header(self.general_text)
        self.title = str(header.get("title") or self.game_id)
        self.category = str(header.get("category") or "")
        self.tier = str(header.get("tier") or "")
        self.engine = parse_engine(self.general_text)
        seed = header.get("fixed_seed")
        self.seed = int(seed) if isinstance(seed, (int, float)) else None

        # requirement inventory over all sections
        self.requirements: dict[str, Requirement] = {}
        self.section_of: dict[str, str] = {}
        self.sections: list[tuple[str, list[str]]] = []
        for heading, body in _split_sections(self.general_text):
            ids: list[str] = []
            # Some migrated requirements declare a range in the section heading
            # but define each item under its own ``### S03: ...`` subsection.
            # Preserve those bodies instead of assigning the first bullet to
            # every id in the range.
            for req_id, title, subbody in _subheading_items(body):
                if req_id in self.requirements:
                    continue
                anchor = f"- {req_id} {title.strip()}".rstrip()
                text = "\n".join(part for part in (anchor, subbody.strip()) if part)
                self.requirements[req_id] = Requirement(
                    requirement_id=req_id, source_file="general_requirement.txt",
                    section=heading, anchor=anchor, text=text)
                self.section_of[req_id] = heading
                ids.append(req_id)
            for req_id, anchor, text in _anchor_items(body):
                if req_id in self.requirements:
                    continue  # first declaration wins; duplicates recorded below
                self.requirements[req_id] = Requirement(
                    requirement_id=req_id, source_file="general_requirement.txt",
                    section=heading, anchor=anchor.strip(), text=text.strip())
                self.section_of[req_id] = heading
                ids.append(req_id)
            # markdown-table requirement rows (``| E01 | 旧香囊残灰 | … |``):
            # migrated docs freeze their content lists as id-keyed tables, and
            # task spec_refs legitimately point at those rows — they are
            # inventoried with the row as the anchor so nothing declared is
            # silently dropped
            for match in _TABLE_ROW_RE.finditer(body):
                req_id = match.group(1)
                if req_id in self.requirements:
                    continue
                row = match.group(0).strip()
                self.requirements[req_id] = Requirement(
                    requirement_id=req_id, source_file="general_requirement.txt",
                    section=heading, anchor=row, text=row)
                self.section_of[req_id] = heading
                ids.append(req_id)
            # section-level ids: documents that number whole sections by a
            # bracket range (``## 18. 键盘鼠标操作与无障碍 [P14]``) without
            # repeating the id on each body line still declare requirements —
            # they are inventoried with the section's first body line as the
            # anchor so nothing declared is silently dropped.
            for req_id in _section_range_ids(heading, body):
                if req_id in self.requirements:
                    # A migrated RTS catalog first names F01..F14 briefly;
                    # its later explicitly headed faction specification owns
                    # the definition. References elsewhere never override it.
                    previous = self.requirements[req_id]
                    if (re.match(r"^[一二三四五六七八九十]+、", heading)
                            and re.search(r"\[" + re.escape(req_id) + r"\]", heading)):
                        previous.anchor = heading
                        previous.section = heading
                        previous.text = body.strip()
                        self.section_of[req_id] = heading
                        ids.append(req_id)
                    continue
                children = [rid for rid in ids if rid.startswith(req_id + ".")]
                if children:
                    parent_text = f"{heading}；具体规则见 " + "、".join(children)
                    first = heading
                else:
                    parent_text = body.strip()
                    first = next((ln.strip() for ln in body.splitlines()
                              if ln.strip() and not ln.startswith("#")), "")
                if not first:
                    continue
                self.requirements[req_id] = Requirement(
                    requirement_id=req_id, source_file="general_requirement.txt",
                    section=heading, anchor=first, text=parent_text)
                self.section_of[req_id] = heading
                ids.append(req_id)
            self.sections.append((heading, ids))
        self.facts = GameFacts(title=self.title, category=self.category,
                               tier=self.tier, engine=self.engine, seed=self.seed)
        self._extract_facts()
        self._extract_tasks()
        self._extract_references()

    # ── inventory helpers ────────────────────────────────────────────────────

    def requirement(self, req_id: str) -> Requirement | None:
        return self.requirements.get(req_id)

    def requirements_with_prefix(self, prefix: str) -> list[Requirement]:
        out = [r for rid, r in self.requirements.items()
               if re.match(rf"^{prefix}\d+$", rid)]
        return sorted(out, key=lambda r: r.requirement_id)

    def ids_text(self) -> str:
        return "\n".join(
            f"{r.requirement_id}\t{r.section}\t{r.brief(100)}"
            for _, r in sorted(self.requirements.items()))

    # ── fact extraction ──────────────────────────────────────────────────────

    def _extract_facts(self) -> None:
        facts = self.facts

        # key bindings: the first requirement anchor that reads like a key map
        for req in self.requirements.values():
            if not re.search(r"＝|=", req.anchor) or not re.search(
                    r"(Space|Esc|Enter|WASD|左键|鼠标|按键|键盘|Tab|Shift)", req.anchor):
                continue
            if any(k in req.section for k in ("操作", "输入", "无障碍", "键鼠")):
                facts.keys = _parse_key_line(_clean_anchor_content(req.anchor),
                                             [req.requirement_id])
                if facts.keys:
                    break
        if not facts.keys:
            # fallback 2: a controls section whose lines carry no anchor ids
            # (G055-style ``- 键盘：WASD 移动，E 互动，…``); the section's own
            # bracket id (e.g. [P14]) becomes the traceability anchor
            for heading, body in _split_sections(self.general_text):
                if not any(k in heading for k in ("操作", "输入", "无障碍", "键鼠")):
                    continue
                section_ids = _section_range_ids(heading, body)
                for line in body.splitlines():
                    if re.search(r"(WASD|[ESCMQ]\s+[一-龥]|Esc|Enter|Space)", line) \
                            and any(k in line for k in ("移动", "互动", "暂停", "观察", "蹲")):
                        facts.keys = _parse_key_line(
                            _clean_anchor_content(line.strip()), section_ids[:1])
                        if facts.keys:
                            break
                if facts.keys:
                    break
        if not facts.keys:
            # fallback 3: mechanics/controls anchors that embed the key inside
            # prose (G045-style ``跳跃 Space`` / ``Shift 跑步``)
            embedded = re.compile(
                r"(?P<a1>[一-龥]{2,4})[＝:=]?\s*(?P<k1>\b(?:Space|Shift|Esc|"
                r"Enter|Tab|LMB|RMB|WASD)\b)"
                r"|(?P<k2>\b(?:Space|Shift|Esc|Enter|Tab|LMB|RMB|WASD)\b)"
                r"\s*(?:键)?[＝:=]?\s*(?P<a2>[一-龥]{2,4})")
            for req in self.requirements.values():
                if not any(k in req.section for k in
                           ("操作", "输入", "移动与交互", "机制系统")):
                    continue
                found: list[KeyBinding] = []
                for match in embedded.finditer(req.anchor):
                    action = (match.group("a1") or match.group("a2") or "").strip()
                    key = match.group("k1") or match.group("k2") or ""
                    if not action or not key:
                        continue
                    action = re.sub(r"^[按用以]", "", action)
                    verb = "interact"
                    if any(k in action for k in ("切换", "视角", "镜头", "俯视", "观察")):
                        verb = "look"
                    elif any(k in action for k in ("移动", "走", "跑", "瞄准")):
                        verb = "move"
                    else:
                        for zh, canonical in _ZH_ACTION_VERBS.items():
                            if zh in action:
                                verb = canonical
                                break
                    found.append(KeyBinding(action_zh=action, keys=[key], verb=verb,
                                             requirement_ids=[req.requirement_id]))
                if len(found) >= 2:
                    facts.keys = found[:6]
                    break

        # lifecycle states + events from the flow/mechanic sections
        for heading, body in _split_sections(self.general_text):
            if not any(k in heading for k in
                       ("流程", "核心循环", "机制系统", "阶段", "数值口径", "验收")):
                continue
            for line in body.splitlines():
                if "state_change" in line or "进入「" in line or "next_actions" in line:
                    for token in _QUOTED_RE.findall(line):
                        if _is_lifecycle_state(token) and \
                                token not in facts.lifecycle_states:
                            facts.lifecycle_states.append(token)
                if "observable" in line or "事件" in line:
                    for token in _extract_events_text(line):
                        if token not in facts.runtime_events:
                            facts.runtime_events.append(token)
        # vibration/haptic event lists (F06/FE06) are runtime-observable events
        for req in self.requirements.values():
            if "震动事件" in req.text or "音画同步" in req.text:
                for token in _extract_events_text(req.text):
                    if token not in facts.runtime_events:
                        facts.runtime_events.append(token)

        # HUD line (I06/U01-like): UI 必须显示 / 必显状态 / HUD 须常驻
        for req in self.requirements.values():
            if re.search(r"UI\s*(必须显示|须常驻|必显|必须呈现)|"
                         r"HUD\s*(须|需|必须|：:)", req.anchor):
                facts.hud_items = [req.anchor]
                break

        # camera rules: F01/F02-style lines
        for req in self.requirements.values():
            if re.match(r"^F(E)?0[12]\b", req.requirement_id) and any(
                    k in req.anchor for k in ("视角", "镜头", "相机", "安全区")):
                facts.camera_rules.append(f"{req.requirement_id}: {req.anchor}")

        # story elements: W01.. anchors (fallback: 世界背景/玩家角色 bodies)
        for req in self.requirements_with_prefix("W"):
            facts.story_elements[req.requirement_id] = req.brief(220)
        if not facts.story_elements:
            for heading, body in _split_sections(self.general_text):
                if any(k in heading for k in ("世界背景", "故事前提", "玩家角色",
                                              "一句话概念", "核心循环", "选择与结局")):
                    lines = [ln.strip() for ln in body.splitlines()
                             if ln.strip() and not ln.startswith("#")][:2]
                    if lines:
                        facts.story_elements[heading] = " / ".join(lines)[:220]
        for key in ("W01", "W02", "W03", "W04", "W05", "W06", "W07", "W08"):
            if key not in facts.story_elements:
                facts.gaps.append(f"story element {key} not found in the requirement "
                                  "document — recorded, not fabricated")

        # cutscene items: C0x / CG0x anchors with type/duration
        for req in list(self.requirements.values()):
            if re.match(r"^(C|CG)\d{2}$", req.requirement_id) and any(
                    k in req.section for k in _ASSET_SECTIONS):
                duration = re.search(r"(\d+(?:\.\d+)?)\s*秒", req.anchor)
                res = re.search(r"(\d{3,4})\s*[×x]\s*(\d{3,4})", req.anchor)
                facts.cg_items.append({
                    "requirement_id": req.requirement_id,
                    "title": req.anchor.split("：")[0].strip(),
                    "duration_s": duration.group(1) if duration else "",
                    "resolution": "x".join(res.groups()) if res else "",
                    "anchor": req.brief(200),
                })

        # sound list: the F06-style frozen 清单 line
        for req in self.requirements.values():
            if "音效清单" in req.anchor and ("冻结" in req.anchor or "one_shot" in req.anchor):
                facts.sound_items = [req.brief(300)]
                break
        if not facts.sound_items:
            for req in self.requirements.values():
                if re.search(r"音效|音频范围|声音语言", req.anchor) and re.search(
                        r"清单|冻结|语言", req.anchor):
                    facts.sound_items = [req.brief(300)]
                    break

        # win/lose/recovery + loop + scope notes. The V01/V02/V03 anchors are
        # only trusted when their text matches outcome semantics — several
        # migrated cases repurpose the letters (G045 V01 = a bicycle spec,
        # G058 V01 = a gacha rule), and those must not become win conditions.
        guards = {"win_condition": ("成功条件", "胜利", "通关", "达成", "完赛", "判胜"),
                  "lose_condition": ("失败条件", "判负", "失败", "败北", "Game Over"),
                  "recovery_rule": ("恢复语义", "恢复", "重开", "重试", "复活")}
        for prefix, attr in (("V01", "win_condition"), ("V02", "lose_condition"),
                             ("V03", "recovery_rule")):
            req = self.requirements.get(prefix)
            if req is None:
                continue
            keyword_hit = any(k in req.anchor for k in guards[attr])
            section_hit = any(k in req.section for k in ("成功", "失败", "恢复"))
            if keyword_hit and section_hit:
                setattr(facts, attr, req.brief(240))
        if not facts.win_condition:
            for heading, body in _split_sections(self.general_text):
                if any(k in heading for k in ("选择与结局", "成功、失败", "失败恢复")):
                    lines = [ln.strip() for ln in body.splitlines()
                             if ln.strip() and not ln.startswith("#")][:2]
                    if lines:
                        setattr(facts,
                                "win_condition" if "结局" in heading or "成功" in heading else
                                ("lose_condition" if "失败" in heading else "recovery_rule"),
                                " / ".join(lines)[:240])
        if not facts.win_condition:
            facts.gaps.append("no explicit win-condition anchor found — the outcome "
                              "assertion grounds itself in the flow text instead")
        for req in self.requirements_with_prefix("S"):
            if "核心循环" in req.anchor or "一句话" in req.anchor:
                facts.loop_summary = req.brief(240)
                break
        if not facts.loop_summary:
            for heading, body in _split_sections(self.general_text):
                if "核心循环" in heading:
                    facts.loop_summary = " / ".join(
                        ln.strip() for ln in body.splitlines()
                        if ln.strip() and not ln.startswith("#"))[:240]
                    break
        for req in self.requirements_with_prefix("N"):
            facts.scope_notes.append(f"{req.requirement_id}: {req.brief(160)}")

        # mechanic systems inventory (M0x headers) with their own observable
        # vocabulary: the events/states a mechanism's anchor text itself names
        # drive the per-mechanism C2 behavior probes — an anchor with no
        # observable vocabulary is probed through the human path instead of
        # being silently dropped
        for req in self.requirements_with_prefix("M"):
            name = re.split(r"（", req.anchor.split("：", 1)[-1])[0].strip() or req.brief(60)
            facts.mechanics.append({
                "requirement_id": req.requirement_id,
                "name": name, "anchor": req.brief(200),
                "events": _extract_events_text(req.text)[:6],
                "states": [t for t in _QUOTED_RE.findall(req.text)
                           if _is_lifecycle_state(t)][:4],
            })

    def _extract_tasks(self) -> None:
        facts = self.facts
        for kind, dir_name, jsonl_name in (
                ("3d_object", "3D_object", "object_tasks.jsonl"),
                ("3d_scene", "3D_scene", "scene_tasks.jsonl"),
                ("tpose", "tpose", "tpose_tasks.jsonl"),
                ("motion", "motion", "motion_tasks.jsonl"),
                ("audio", "audio", "audio_tasks.jsonl"),
                ("cg_video", "cg_video", "cg_tasks.jsonl")):
            path = self.root / dir_name / jsonl_name
            tasks: list[TaskInfo] = []
            if path.is_file():
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("//"):
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        facts.gaps.append(f"unparseable line in {dir_name}/{jsonl_name}")
                        continue
                    if not isinstance(row, dict) or not row.get("task_id"):
                        continue
                    tasks.append(TaskInfo(
                        task_id=str(row["task_id"]), kind=kind,
                        name=str(row.get("asset_name") or row.get("cg_name")
                                or row.get("motion_name") or row.get("task_id")),
                        role=str(row.get("role") or row.get("task_type")
                                or row.get("audio_type") or row.get("cg_type") or ""),
                        prompt=str(row.get("prompt") or ""), raw=row))
            facts.task_inventory[kind] = tasks
        facts.asset_roles = [t.name for t in facts.task_inventory.get("3d_object", [])]
        if not any(facts.task_inventory.values()):
            facts.gaps.append("no asset task jsonl found in the case")

    def _extract_references(self) -> None:
        """Reference files actually usable by the asset tasks.

        Authority: the per-task ``image_path`` of the task jsonl files (what
        the task really receives), resolved to case-relative paths; backed by
        a scan of the kind reference directories.
        """
        facts = self.facts
        found: list[str] = []
        for tasks in facts.task_inventory.values():
            for task in tasks:
                # jsonl paths are repo-relative like
                # test_data/test_samples/<game>/<kind>/ref_images/x.png
                raw = task.image_reference
                if not raw:
                    continue
                marker = f"{self.game_id}/"
                if marker in raw:
                    rel = raw.split(marker, 1)[1]
                else:
                    rel = raw
                candidate = (self.root / rel).resolve()
                if candidate.is_file():
                    rel_path = candidate.relative_to(self.root.resolve()).as_posix()
                    if rel_path not in found:
                        found.append(rel_path)
        for pattern in ("ref_images/*", "ref_audio/*", "ref_video/*"):
            for kind_dir in ("3D_object", "3D_scene", "tpose", "motion",
                             "audio", "cg_video"):
                for path in sorted((self.root / kind_dir).glob(pattern)):
                    if path.is_file():
                        rel = path.relative_to(self.root).as_posix()
                        if rel not in found:
                            found.append(rel)
        facts.reference_files = found

    # ── dispositions ────────────────────────────────────────────────────────

    def semantic_family(self, req_id: str) -> str:
        req = self.requirements.get(req_id)
        if req is None:
            return "needs-clarification"
        prefix = re.match(r"^([A-Z]+)", req_id)
        family = _section_family(req.section, prefix.group(1) if prefix else "")
        if family == "needs-clarification":
            refined = _anchor_refinement(req.anchor)
            if refined is not None:
                return refined
        return family


__all__ = ["CaseModel", "Requirement", "KeyBinding", "TaskInfo", "GameFacts",
           "parse_engine", "parse_yaml_header"]
