"""
models/gen_motion/tripo_rigging_model.py

Cloud wrappers for Tripo3D's rigging, animation and format-conversion endpoints
accessed through the Tencent Cloud TokenHub gateway.

These are the drop-in cloud replacements for PuppeteerModel (rigging) and
MoMaskModel (text-to-motion). The operator-visible signatures match: callers
pass bytes or text in and get bytes back, exactly like the local models do.

Endpoints:
  POST  /v1/api/3d/submit   — submit a task; returns {id, status, ...}
  POST  /v1/api/3d/query    — poll a task; returns {status, output:{model_url, ...}}

The Tripo-family model-id strings come from the TokenHub /v1/models list:
  tripo-3d-rigging-check, tripo-3d-rigging, tripo-3d-animation, tripo-3d-format

Mesh input is a URL, not bytes. `input` takes a publicly reachable direct link
(GLB/GLTF/FBX/OBJ/STL, <=150 MB) and the server fetches it. This gateway has no
upload endpoint and rejects `data:` URIs, so a mesh that exists only on local
disk cannot be submitted. Callers pass `mesh_url`; `mesh` bytes only key the
cache.

CONTRACT DEVIATIONS (model_require.md targets local-weight models;
                     see agent_skills/develop_harness/api_model_require.md):
  C1  R2.1/R2.2 → R9.1  `model_path` carries a model-id string, not a path.
  C2  R2.3      → R9.2  `device` accepted for interface parity, ignored.
  C3  R3.6/R5.5 → R9.3  no @torch.no_grad(); torch is not imported.
  C4  R4.1-R4.3 → R9.4  `unload()` closes the HTTP session only.
  C5  R3.3/R3.4 → R9.5  `seed` accepted for interface parity, ignored.
                        Server-side reproducibility is NOT guaranteed.
  C6  R3.1      → R9.6  submit → poll → download behind a synchronous
                        `infer()`. `timeout` default is 1800 s (generation
                        can run many minutes; a timeout carries `task_id`).
  C8  (new)     → R9.8  `cache_dir` prevents re-billing identical requests.
  C9  (new)     → R9.9  `max_retries` with exponential backoff; retryable
                        (5xx/429/transport) vs. terminal (4xx) split.

Environment:
    TOKENHUB_API_KEY   — required at first infer(), not at construction.
                         Obtain from console.cloud.tencent.com/tokenhub
                         then open: console.cloud.tencent.com/tokenhub/inference
                         to enable post-pay billing for the tripo-3d-* models.
    TOKENHUB_API_BASE  — optional override (default https://tokenhub.tencentmaas.com)
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Optional

from models.common import cloud_api

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

ENV_KEY = "TOKENHUB_API_KEY"
ENV_BASE = "TOKENHUB_API_BASE"
DEFAULT_API_BASE = "https://tokenhub.tencentmaas.com"
SIGNUP_URL = "https://console.cloud.tencent.com/tokenhub"

#: Verified from /v1/models on tokenhub.tencentmaas.com.
MODEL_RIG_CHECK = "tripo-3d-rigging-check"
MODEL_RIGGING = "tripo-3d-rigging"
MODEL_ANIMATION = "tripo-3d-animation"
MODEL_FORMAT = "tripo-3d-format"

#: `rig_type` values accepted by tripo-3d-rigging. Prefer the value rig-check
#: returns over a guess; the default is "biped".
RIG_TYPES = frozenset({"biped", "quadruped", "hexapod", "octopod",
                       "avian", "serpentine", "aquatic"})

#: Skeleton naming convention. "mixamo" is for DCC import only: the animation
#: endpoint refuses to retarget a mixamo-named skeleton.
RIG_SPECS = frozenset({"tripo", "mixamo"})

#: The only spec the animation endpoint accepts.
ANIMATABLE_SPEC = "tripo"

#: Preset clips available to a biped rig (RIG V2.5).
BIPED_PRESETS = frozenset({
    "preset:idle", "preset:walk", "preset:run", "preset:dive", "preset:climb",
    "preset:jump", "preset:slash", "preset:shoot", "preset:hurt", "preset:fall",
    "preset:turn",
})

#: The single preset each non-biped topology provides, keyed by `rig_type`.
NON_BIPED_PRESETS = {
    "quadruped": "preset:quadruped:walk",
    "hexapod": "preset:hexapod:walk",
    "octopod": "preset:octopod:walk",
    "serpentine": "preset:serpentine:march",
    "aquatic": "preset:aquatic:march",
}

#: A preset must match the rig's topology; the server refuses a mismatch.
PRESET_ANIMATIONS = BIPED_PRESETS | frozenset(NON_BIPED_PRESETS.values())


def default_preset(rig_type: str) -> str:
    """The walk-equivalent preset for one rig type."""
    return NON_BIPED_PRESETS.get(str(rig_type).strip().lower(), "preset:walk")


#: `out_format` values: GLB for the web, FBX for DCC tools and game engines.
OUT_FORMATS = frozenset({"glb", "fbx"})

#: Mesh containers the gateway will fetch and read.
INPUT_FORMATS = frozenset({"glb", "gltf", "fbx", "obj", "stl"})

#: Documented ceiling on the fetched mesh.
MAX_INPUT_BYTES = 150 * 1024 * 1024

#: Confirmed task state strings (case-insensitive comparison is used below).
_DONE = frozenset({"completed", "success", "succeeded", "finished"})
_FAILED = frozenset({"failed", "cancelled", "canceled", "banned", "expired"})

_SUBMIT_PATH = "/v1/api/3d/submit"
_QUERY_PATH = "/v1/api/3d/query"


def _api_base() -> str:
    return os.environ.get(ENV_BASE, DEFAULT_API_BASE).rstrip("/")


def resolve_mesh_url(mesh_url: Optional[str], mesh: Optional[bytes]) -> str:
    """
    Validate the mesh reference, or explain what is needed instead of bytes.
    """
    if mesh_url:
        url = str(mesh_url).strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError(
                f"mesh_url must be an http(s) direct link, got {url[:60]!r}. "
                "A data: URI passes /submit and then fails in the worker."
            )
        return url
    raise ValueError(
        "This endpoint fetches the mesh itself, so it needs a public URL "
        "(mesh_url=...), not file bytes.\n"
        "  - upload the mesh to object storage and pass the object URL, or\n"
        "  - pass a URL that is already reachable from the internet.\n"
        f"Accepted containers: {', '.join(sorted(INPUT_FORMATS))}; "
        f"max {MAX_INPUT_BYTES // (1024 * 1024)} MB."
    )


def _cache_seed(mesh_url: str, mesh: Optional[bytes]) -> bytes:
    """
    Cache-key material for one input mesh.

    Bytes are hashed when available so the cache survives re-hosting: the same
    mesh under a new URL is still a hit, and a hit is not billed.
    """
    if mesh:
        return hashlib.sha256(mesh).digest()
    return mesh_url.encode("utf-8")


# ── Base class ─────────────────────────────────────────────────────────────────


class _TripoCloudBase:
    """Shared HTTP plumbing for all Tripo-on-TokenHub wrappers."""

    MODEL_ID: str = ""

    def __init__(
        self,
        model_path: str = "",      # [CONTRACT-DEVIATION C1]
        device: str = "cuda",      # [CONTRACT-DEVIATION C2]
        *,
        api_key: Optional[str] = None,
        timeout: int = 1800,
        poll_interval: float = 4.0,
        max_retries: int = 3,
        cache_dir: Optional[str] = None,
        api_base: Optional[str] = None,
        http_timeout: int = 60,
        verbose: bool = False,
    ):
        # [CONTRACT-DEVIATION C1] model_path is a model-id, not a weight path.
        self.model_path = str(model_path or self.MODEL_ID)
        # [CONTRACT-DEVIATION C2] device accepted for interface parity, ignored.
        self.device = device

        self.api_key = api_key
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.cache_dir = cache_dir
        self.api_base = api_base or _api_base()
        self.http_timeout = http_timeout
        self.verbose = verbose

        self._client: Optional[cloud_api.CloudAPIClient] = None
        self._cache = cloud_api.ResponseCache(cache_dir, "tokenhub_tripo")

        #: Populated after each real call: task_id, elapsed_sec, credits_used.
        self.last_call_info: dict[str, Any] = {}

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def load(self) -> None:
        """No-op; present so this model is usable anywhere PuppeteerModel is."""

    def unload(self) -> None:
        """[C4] Close the HTTP session; idempotent."""
        if self._client is not None:
            self._client.close()
            self._client = None

    # ── plumbing ───────────────────────────────────────────────────────────────

    @property
    def client(self) -> cloud_api.CloudAPIClient:
        """[C6/R9.7] Lazy — key is read here, not in __init__."""
        if self._client is None:
            key = cloud_api.require_api_key(
                self.api_key, ENV_KEY, SIGNUP_URL,
                who=self.__class__.__name__)
            self._client = cloud_api.CloudAPIClient(
                self.api_base, key,
                timeout=self.http_timeout,
                max_retries=self.max_retries,
            )
        return self._client

    def _submit(self, body: dict) -> str:
        """POST to /v1/api/3d/submit and return the task id."""
        resp = self.client.request("POST", _SUBMIT_PATH, json_body=body)
        task_id = resp.get("id") or resp.get("task_id")
        if not task_id:
            raise cloud_api.CloudAPIRequestError(
                f"No task id in submit response: {resp!r}", payload=resp)
        return str(task_id)

    def _poll(self, task_id: str, model_id: str) -> dict:
        """Block until complete, failed, or timeout. [C6]"""
        deadline = time.time() + self.timeout
        while True:
            if time.time() > deadline:
                raise cloud_api.CloudTaskTimeout(
                    f"Task {task_id!r} did not finish within {self.timeout}s. "
                    "The task continues server-side — store the task_id.",
                    task_id=task_id)
            time.sleep(self.poll_interval)
            resp = self.client.request(
                "POST", _QUERY_PATH,
                json_body={"model": model_id, "id": task_id})
            state = str(resp.get("status") or "").lower()
            if state in _DONE:
                return resp
            if state in _FAILED:
                raise cloud_api.CloudTaskFailed(
                    f"Task {task_id!r} ended in state {state!r}.",
                    task_id=task_id, payload=resp)
            if self.verbose:
                logger.info("[%s] task %s: %s", self.__class__.__name__,
                            task_id, state)

    def _result_url(self, data: dict) -> str:
        """The artifact URL a completed task points at.

        ``output.model_url`` is the model; ``rendered_image_url`` is the preview
        and is only read when a task produced no model at all.
        """
        output = data.get("output") or {}
        url = output.get("model_url") or output.get("rendered_image_url")
        if not url:
            raise cloud_api.CloudAPIRequestError(
                f"Completed task returned no model_url. output={output!r}",
                payload=data)
        return str(url)

    def _run_task(
        self,
        cache_key: str,
        body: dict,
        result_ext: str = "glb",
    ) -> tuple[bytes, dict]:
        """Cache-check → submit → poll → download.  Returns (bytes, info)."""
        # [C8] Cache hit → no charge.
        cached = self._cache.get(cache_key, ext=result_ext)
        if cached is not None:
            self.last_call_info = {"cached": True, "task_id": None,
                                   "model_url": None}
            return cached, self.last_call_info

        t0 = time.time()
        task_id = self._submit(body)
        if self.verbose:
            logger.info("[%s] submitted task %s", self.__class__.__name__,
                        task_id)
        data = self._poll(task_id, body["model"])
        # The URL is kept alongside the bytes so a caller can hand the
        # provider-hosted result to something else. It is short-lived, so the
        # bytes are downloaded here regardless.
        url = self._result_url(data)
        file_bytes = self.client.download(url)
        elapsed = round(time.time() - t0, 2)

        info: dict[str, Any] = {
            "task_id": task_id,
            "model_url": url,
            "elapsed_sec": elapsed,
            "output_bytes": len(file_bytes),
            "cached": False,
        }
        logger.info("[%s] task %s done in %.1fs (%d bytes)",
                    self.__class__.__name__, task_id, elapsed, len(file_bytes))
        self._cache.put(cache_key, file_bytes, info, ext=result_ext)
        self.last_call_info = info
        return file_bytes, info


# ── Public model classes ───────────────────────────────────────────────────────


class TripoRigCheckModel(_TripoCloudBase):
    """
    Check whether a mesh can be rigged and return the recommended rig type.

    Return dict keys:
        riggable (bool)   — True when the mesh is expected to rig successfully.
        rig_type (str)    — One of `RIG_TYPES`; pass it on to TripoRiggingModel.
        raw (dict)        — Full query response for debugging.
    """

    MODEL_ID = MODEL_RIG_CHECK

    def infer(
        self,
        mesh: Optional[bytes] = None,
        mesh_format: str = ".glb",
        seed: int = 42,    # [C5] accepted, ignored
        *,
        mesh_url: Optional[str] = None,
        **_: Any,
    ) -> dict[str, Any]:
        """
        Args:
            mesh:        Optional file bytes, used only for the cache key.
            mesh_format: Extension such as ``.glb``; must be in `INPUT_FORMATS`.
            mesh_url:    Public direct link to the mesh. Required.
            seed:        [C5] Accepted for interface parity, ignored.
        """
        url = resolve_mesh_url(mesh_url, mesh)
        _check_format(mesh_format)

        cache_key = hashlib.sha256(
            b"check:" + _cache_seed(url, mesh)
        ).hexdigest()

        # Cache stores the JSON verdict, not a binary file.
        import json as _json
        cached = self._cache.get(cache_key, ext="json")
        if cached is not None:
            self.last_call_info = {"cached": True}
            return _parse_check(_json.loads(cached))

        body = {"model": self.model_path, "input": url}
        t0 = time.time()
        task_id = self._submit(body)
        # A "not riggable" verdict arrives as a *failed* task, and the rig type it
        # inferred is only in the error message. Letting the exception through
        # would throw away the one useful thing the call returned.
        try:
            data = self._poll(task_id, self.model_path)
        except cloud_api.CloudTaskFailed as exc:
            data = exc.payload if getattr(exc, "payload", None) else {
                "status": "failed", "error": {"message": str(exc)}}
        elapsed = round(time.time() - t0, 2)

        self.last_call_info = {"task_id": task_id, "elapsed_sec": elapsed,
                               "cached": False}
        self._cache.put(cache_key, _json.dumps(data).encode(),
                        self.last_call_info, ext="json")
        return _parse_check(data)


def _check_format(mesh_format: str) -> str:
    ext = mesh_format.lstrip(".").lower()
    if ext not in INPUT_FORMATS:
        raise ValueError(
            f"unsupported mesh format {mesh_format!r}; the endpoint reads "
            f"{', '.join(sorted(INPUT_FORMATS))}"
        )
    return ext


#: What rig-check reports for a mesh whose body plan it could not classify. Not a
#: value `rig_type` accepts, so it must not be forwarded to the rigging call.
UNCLASSIFIED = "others"


def _parse_check(data: dict) -> dict[str, Any]:
    """
    Read the verdict out of a rig-check response, pass or fail.

    A refusal comes back as ``status: failed`` with the classification buried in
    ``error.message`` ("model is not riggable, rig_type=others"), while a pass
    puts it in ``output``. Both carry the same useful fact, so both are parsed:
    the rig type is what a caller needs either to proceed or to understand the
    refusal.

    A missing flag reads as not riggable, so an unexpected response shape stops
    the caller before the billed rigging call rather than after it.
    """
    import re

    output = data.get("output") or {}
    riggable = bool(output.get("riggable", output.get("is_riggable", False)))
    rig_type = str(output.get("rig_type") or output.get("type") or "")

    if not rig_type:
        message = str((data.get("error") or {}).get("message") or "")
        found = re.search(r"rig_type\s*=\s*([A-Za-z_]+)", message)
        if found:
            rig_type = found.group(1).lower()

    return {
        "riggable": riggable,
        "rig_type": rig_type or "biped",
        # True when the mesh has no recognised body plan. Distinct from a plain
        # refusal: there is no rig_type to retry with, so retrying is pointless.
        "unclassified": rig_type == UNCLASSIFIED,
        "raw": data,
    }


#: Named limb chains each topology should yield. A rig with fewer has not
#: resolved the whole body.
EXPECTED_LIMBS = {
    "biped": 4,        # two arms, two legs
    "quadruped": 4,
    "hexapod": 6,
    "octopod": 8,
    "avian": 4,        # two wings, two legs
    "serpentine": 0,
    "aquatic": 0,
}


def inspect_rig(glb_bytes: bytes) -> dict[str, Any]:
    """
    Report how much of a rigged GLB's skeleton is anatomically named.

    Two naming schemes come out of this service, and both are meaningful:

      * generic  — ``tripo::0_Left_Limb_0``, used for quadrupeds, birds and
        anything else described only as numbered limb chains.
      * humanoid — ``L_Thigh``, ``R_Forearm``, ``Spine01``, used for bipeds.

    Anything else (``bone_N``) is structure the rigger did not resolve. Only
    named joints are retargeted onto by a preset clip, so a rig whose joints are
    mostly anonymous animates almost nothing and leaves the body in bind pose.
    Bone count does not show this; naming does.

    Returns:
        bones (int)         — total joints
        named (int)         — joints carrying a recognised name
        anonymous (int)     — unresolved joints
        limbs (int)         — distinct named limb chains
        limb_names (list)   — e.g. ["0_Left", "0_Right"] or ["L_arm", "R_leg"]
        scheme (str)        — "generic", "humanoid", or "none"
        has_spine (bool), has_head (bool)
    """
    import json as _json
    import re
    import struct as _struct

    offset, gltf = 12, None
    while offset < len(glb_bytes):
        length, kind = _struct.unpack_from("<II", glb_bytes, offset)
        if kind == 0x4E4F534A:
            gltf = _json.loads(glb_bytes[offset + 8: offset + 8 + length])
            break
        offset += 8 + length
    empty = {"bones": 0, "named": 0, "anonymous": 0, "limbs": 0,
             "limb_names": [], "scheme": "none",
             "has_spine": False, "has_head": False}
    if gltf is None or not gltf.get("skins"):
        return empty

    nodes = gltf["nodes"]
    joints = gltf["skins"][0]["joints"]
    names = [str(nodes[j].get("name") or "") for j in joints]

    generic = [n for n in names if n.startswith("tripo::")]
    if generic:
        # The trailing index is a segment along one limb, so segments collapse
        # to a chain: 0_Left_Limb_0..2 is one limb, not three.
        chains = set()
        for name in generic:
            match = re.match(r"tripo::(\d+_(?:Left|Right))_Limb_\d+$", name)
            if match:
                chains.add(match.group(1))
        return {
            "bones": len(joints),
            "named": len(generic),
            "anonymous": len(names) - len(generic),
            "limbs": len(chains),
            "limb_names": sorted(chains),
            "scheme": "generic",
            "has_spine": any("Spine" in n for n in generic),
            "has_head": any("Head" in n for n in generic),
        }

    # Humanoid scheme. A limb counts as present when its root bone is there;
    # twist and segment bones hang off those and would inflate the count.
    HUMANOID_LIMB_ROOTS = {
        "L_arm": ("l_upperarm", "leftarm", "l_arm"),
        "R_arm": ("r_upperarm", "rightarm", "r_arm"),
        "L_leg": ("l_thigh", "leftupleg", "l_leg"),
        "R_leg": ("r_thigh", "rightupleg", "r_leg"),
    }
    lowered = [n.lower() for n in names]
    chains = {
        label for label, aliases in HUMANOID_LIMB_ROOTS.items()
        if any(n in aliases for n in lowered)
    }
    if not chains:
        return {**empty, "bones": len(joints), "anonymous": len(names)}

    # Anonymous means unresolved, so `bone_N` and empty names only. Everything
    # else in a humanoid rig is anatomy: hands, toes, twists, clavicles.
    anonymous = sum(1 for n in lowered if not n or re.fullmatch(r"bone_\d+", n))
    return {
        "bones": len(joints),
        "named": len(names) - anonymous,
        "anonymous": anonymous,
        "limbs": len(chains),
        "limb_names": sorted(chains),
        "scheme": "humanoid",
        "has_spine": any("spine" in n or "pelvis" in n for n in lowered),
        "has_head": any("head" in n for n in lowered),
    }


def rig_quality_note(report: dict[str, Any], rig_type: str) -> str:
    """One line describing whether a rig is fit to animate, and why."""
    expected = EXPECTED_LIMBS.get(str(rig_type).lower(), 0)
    if report["bones"] == 0:
        return "no skeleton at all"
    parts = [f"{report['bones']} bones",
             f"{report['named']} named", f"{report['anonymous']} anonymous",
             f"{report['limbs']}/{expected} limb chains"]
    if expected and report["limbs"] < expected:
        parts.append(
            "— preset clips will only drive the named chains, so the unnamed "
            "limbs stay in the bind pose"
        )
    return ", ".join(parts[:4]) + ("  " + parts[4] if len(parts) > 4 else "")


#: Degrees of first-frame deviation from a joint's rest orientation that indicate
#: a failed retarget rather than a pose. A clip legitimately starts mid-stride,
#: and deviations past 100 deg were seen on a horse that animated correctly; a
#: near-180 deg flip is a bone pointing the wrong way, which shears the mesh
#: bound to it.
FLIPPED_JOINT_DEGREES = 150.0


def inspect_animation(glb_bytes: bytes) -> dict[str, Any]:
    """
    Check an animated GLB for joints the retarget flipped.

    A clip whose first frame sits ~180 deg from a joint's rest orientation has
    not been retargeted onto that joint, it has been inverted on it: the bone
    points backwards and the skin stretched across it shears into spikes. This
    is visible on screen but not in any status field, bone count or clip
    duration, and the geometry's overall bounds stay plausible — the tearing is
    local to the affected limb.

    Returns:
        clip (str)          — name of the longest clip
        joints (int)        — joints the clip drives
        moving (int)        — joints with more than 5 deg of travel
        flipped (list)      — [(name, degrees), ...] past FLIPPED_JOINT_DEGREES
        worst (float)       — largest first-frame deviation, in degrees
    """
    import json as _json
    import math
    import struct as _struct

    component = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
                 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
    counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    offset, gltf, binary = 12, None, None
    while offset < len(glb_bytes):
        length, kind = _struct.unpack_from("<II", glb_bytes, offset)
        chunk = glb_bytes[offset + 8: offset + 8 + length]
        if kind == 0x4E4F534A:
            gltf = _json.loads(chunk)
        elif kind == 0x004E4942:
            binary = chunk
        offset += 8 + length

    empty = {"clip": None, "joints": 0, "moving": 0, "flipped": [], "worst": 0.0}
    if not gltf or not gltf.get("animations") or binary is None:
        return empty

    def read(index):
        acc = gltf["accessors"][index]
        fmt, size = component[acc["componentType"]]
        n = counts[acc["type"]]
        view = gltf["bufferViews"][acc["bufferView"]]
        base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride") or size * n
        return [_struct.unpack_from("<" + fmt * n, binary, base + i * stride)
                for i in range(acc["count"])]

    def angle(a, b):
        dot = min(1.0, abs(sum(x * y for x, y in zip(a, b))))
        return math.degrees(2 * math.acos(dot))

    animation = max(gltf["animations"],
                    key=lambda a: len(a.get("channels", [])))
    nodes = gltf["nodes"]
    flipped, worst, moving, seen = [], 0.0, 0, set()

    for channel in animation["channels"]:
        target = channel["target"]
        seen.add(target["node"])
        if target["path"] != "rotation":
            continue
        values = read(animation["samplers"][channel["sampler"]]["output"])
        rest = nodes[target["node"]].get("rotation", [0, 0, 0, 1])
        deviation = angle(values[0], rest)
        worst = max(worst, deviation)
        if max(angle(values[0], v) for v in values) > 5:
            moving += 1
        if deviation >= FLIPPED_JOINT_DEGREES:
            flipped.append((str(nodes[target["node"]].get("name") or "?"),
                            round(deviation, 1)))

    return {
        "clip": animation.get("name"),
        "joints": len(seen),
        "moving": moving,
        "flipped": sorted(flipped, key=lambda item: -item[1]),
        "worst": round(worst, 1),
    }


class TripoRiggingModel(_TripoCloudBase):
    """
    Predict a skeleton and bind skin weights. Drop-in for PuppeteerModel.

    Return dict keys (parallel to PuppeteerModel.infer()):
        file_bytes (bytes)
        output_format (str) — "glb" or "fbx", as requested
        glb_bytes (bytes)   — the same bytes when out_format is "glb", else None
        task_id (str)
        elapsed_sec (float)
    """

    MODEL_ID = MODEL_RIGGING

    def infer(
        self,
        mesh: Optional[bytes] = None,
        mesh_format: str = ".glb",
        seed: int = 42,             # [C5] accepted, ignored
        *,
        mesh_url: Optional[str] = None,
        rig_type: str = "biped",
        rig_spec: str = "tripo",
        out_format: str = "glb",
        post_filter: bool = True,   # accepted, no cloud equivalent
        **_: Any,
    ) -> dict[str, Any]:
        """
        Args:
            mesh:        Optional file bytes, used only for the cache key.
            mesh_format: Source extension; must be in `INPUT_FORMATS`.
            mesh_url:    Public direct link to the mesh. Required.
            rig_type:    Skeleton topology; see `RIG_TYPES`. `rig-check`
                         recommends one for a given mesh.
            rig_spec:    Bone naming: "tripo" or "mixamo".
            out_format:  "glb" or "fbx".
            post_filter: Accepted for signature parity, ignored.
            seed:        [C5] Accepted for interface parity, ignored.
        """
        url = resolve_mesh_url(mesh_url, mesh)
        _check_format(mesh_format)
        rig_type = _one_of(rig_type, RIG_TYPES, "rig_type")
        rig_spec = _one_of(rig_spec, RIG_SPECS, "spec")
        out_format = _one_of(out_format, OUT_FORMATS, "out_format")

        cache_key = hashlib.sha256(
            b"rig:" + _cache_seed(url, mesh)
            + f":{rig_type}:{rig_spec}:{out_format}".encode()
        ).hexdigest()
        body = {
            "model": self.model_path,
            "input": url,
            "rig_type": rig_type,
            "spec": rig_spec,
            "out_format": out_format,
        }
        file_bytes, info = self._run_task(cache_key, body,
                                         result_ext=out_format)
        return {
            "file_bytes": file_bytes,
            "output_format": out_format,
            "glb_bytes": file_bytes if out_format == "glb" else None,
            "model_url": info.get("model_url"),
            "task_id": info.get("task_id"),
            "elapsed_sec": info.get("elapsed_sec"),
        }


def _one_of(value: str, allowed: frozenset[str], label: str) -> str:
    normalised = str(value).strip().lower()
    if normalised not in allowed:
        raise ValueError(
            f"{label}={value!r} is not accepted; use one of "
            f"{', '.join(sorted(allowed))}"
        )
    return normalised


class TripoAnimationModel(_TripoCloudBase):
    """
    Drive a rigged mesh with a preset animation. Stands in for MoMaskModel.

    Not a free-text motion model: MoMask generates a clip from a description,
    this endpoint retargets one of a fixed library onto a skeleton the rigging
    step produced. `animation` takes a `preset:` identifier; `PRESET_ANIMATIONS`
    lists what exists.

    Its input is the *rigging task id*, not a mesh or a URL — the animation runs
    against the skeleton the provider still holds for that task, which expires
    after 24 hours.

    Return dict keys (parallel to MoMaskModel):
        file_bytes (bytes)
        output_format (str)
        glb_bytes (bytes)   — the same bytes when out_format is "glb", else None
        model_url (str)     — provider-hosted result, short-lived
        fps (int)           — 30 (provider default)
        task_id (str)
        elapsed_sec (float)
    """

    MODEL_ID = MODEL_ANIMATION

    def infer(
        self,
        rig_task_id: str = "",
        animation: str = "",
        seed: int = 42,         # [C5] accepted, ignored
        *,
        out_format: str = "glb",
        animate_in_place: bool = False,
        export_with_geometry: bool = True,
        **_: Any,
    ) -> dict[str, Any]:
        """
        Args:
            rig_task_id:  Task id returned by TripoRiggingModel, from
                          ``last_call_info["task_id"]``. Valid for 24 hours.
            animation:    A `preset:` identifier; see `PRESET_ANIMATIONS`. Must
                          match the skeleton's topology — a biped preset on a
                          quadruped rig is rejected.
            out_format:   "glb" or "fbx".
            animate_in_place: Strip root translation, so the figure walks on the
                          spot. Useful when a game drives locomotion itself.
            export_with_geometry: Include the mesh; False exports the clip alone.
            seed:         [C5] Accepted for interface parity, ignored.
        """
        task = str(rig_task_id).strip()
        if not task:
            raise ValueError(
                "rig_task_id is required: this endpoint animates the skeleton "
                "held against a completed rigging task, not a mesh you supply. "
                "Pass TripoRiggingModel's last_call_info['task_id'] (valid 24h)."
            )
        preset = str(animation).strip()
        if not preset:
            raise ValueError(
                "animation is required and must be a preset identifier such as "
                "'preset:walk'. This endpoint retargets a fixed library of "
                "clips; it does not generate motion from a description.\n"
                f"Biped presets include: {', '.join(sorted(BIPED_PRESETS))}"
            )
        if not preset.startswith("preset:"):
            raise ValueError(
                f"animation={preset!r} is not a preset identifier. Names are "
                "prefixed, e.g. 'preset:walk' for a biped or "
                "'preset:quadruped:walk' for a quadruped."
            )
        out_format = _one_of(out_format, OUT_FORMATS, "out_format")

        cache_key = hashlib.sha256(
            f"anim:{task}:{preset}:{out_format}:{animate_in_place}"
            f":{export_with_geometry}".encode()
        ).hexdigest()
        body: dict[str, Any] = {
            "model": self.model_path,
            "input": task,
            "animation": preset,
            "out_format": out_format,
            "animate_in_place": bool(animate_in_place),
            "export_with_geometry": bool(export_with_geometry),
        }

        file_bytes, info = self._run_task(cache_key, body,
                                         result_ext=out_format)
        return {
            "file_bytes": file_bytes,
            "output_format": out_format,
            "glb_bytes": file_bytes if out_format == "glb" else None,
            "model_url": info.get("model_url"),
            "fps": 30,
            "task_id": info.get("task_id"),
            "elapsed_sec": info.get("elapsed_sec"),
        }


class TripoFormatModel(_TripoCloudBase):
    """
    Convert a mesh to another container on Tripo's servers.

    Return dict keys:
        file_bytes (bytes)
        output_format (str)
        task_id (str)
        elapsed_sec (float)
    """

    MODEL_ID = MODEL_FORMAT

    def infer(
        self,
        mesh: Optional[bytes] = None,
        mesh_format: str = ".glb",
        seed: int = 42,
        *,
        mesh_url: Optional[str] = None,
        output_format: str = "fbx",
        **_: Any,
    ) -> dict[str, Any]:
        """
        Args:
            mesh:          Optional source bytes, used only for the cache key.
            mesh_format:   Source extension; must be in `INPUT_FORMATS`.
            mesh_url:      Public direct link to the source mesh. Required.
            output_format: Target container; see `OUT_FORMATS`.
        """
        url = resolve_mesh_url(mesh_url, mesh)
        _check_format(mesh_format)
        out_fmt = _one_of(output_format, OUT_FORMATS, "output_format")

        cache_key = hashlib.sha256(
            b"fmt:" + _cache_seed(url, mesh) + out_fmt.encode()
        ).hexdigest()
        body = {
            "model": self.model_path,
            "input": url,
            "out_format": out_fmt,
        }
        file_bytes, info = self._run_task(cache_key, body, result_ext=out_fmt)
        return {
            "file_bytes": file_bytes,
            "output_format": out_fmt,
            "model_url": info.get("model_url"),
            "task_id": info.get("task_id"),
            "elapsed_sec": info.get("elapsed_sec"),
        }
