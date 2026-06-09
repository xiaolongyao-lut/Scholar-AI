from __future__ import annotations

import json
import logging
import os
import re
import time
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from llm_cost_logger import log_llm_call
from llm_defaults import resolve_llm_params
from llm_pricing import usage_from_response
from llm.gateway import invoke as invoke_llm_gateway
from runtime_env import env_value
from layers.robust_parser import RobustJSONParser

logger = logging.getLogger("AIAdapter")


def _hash_text(value: str) -> str:
    return sha256(str(value).encode("utf-8")).hexdigest()


def _hash_payload(payload: dict[str, Any]) -> str:
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(material.encode("utf-8")).hexdigest()


# --- Phase A2: generation key pool integration --------------------------------
# Background: prior to A2 the AIAdapter walked _PROVIDER_REGISTRY once at __init__
# and pinned a single OpenAI client. On 429 / auth / network failures gated_call
# would retry the SAME credential — no failover. KeyPool already parses .env
# multi-credential generation candidates and exposes try_call() with cooldown,
# so we just dispatch chat completions through it when a pool is available.

_GENERATION_CATEGORY = "generation"


def _resolve_generation_pool() -> Any:
    """Return a KeyPool instance with generation credentials, or None.

    Tolerates: missing key_pool import, missing .env, empty pool, parse errors.
    Honours RUNTIME_ENV_DISABLE_DOTENV=1 and LITERATURE_DISABLE_KEY_POOL=1.
    Never raises — pool is opt-in failover, single-client path is the default.
    """
    if os.environ.get("RUNTIME_ENV_DISABLE_DOTENV") == "1":
        return None
    if os.environ.get("LITERATURE_DISABLE_KEY_POOL") == "1":
        return None
    try:
        from key_pool import get_pool  # noqa: PLC0415
    except ImportError:
        return None
    try:
        pool = get_pool()
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        if not pool.list(_GENERATION_CATEGORY):
            return None
    except (AttributeError, TypeError):
        return None
    return pool

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class AIAdapter:
    """
    LLM 语义引擎适配器。
    支持所有提供 OpenAI 兼容 API 接口的模型 (如 OpenAI, DeepSeek, 阿里通义, 智谱等)。
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: str = None):
        self.enabled = False
        self.client = None
        self.parser = RobustJSONParser()
        self.llm_status = "disabled_uninitialized"
        self.provider_name = "none"
        self.model = model or "gpt-4o-mini"
        self.base_url = base_url
        self.api_key = None

        if not HAS_OPENAI:
            logger.warning("openai 库未安装，AI 增强将自动降级到无 LLM 模式。")
            self.llm_status = "disabled_missing_dependency"
            return

        def _valid_env_value(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            normalized = value.strip()
            if not normalized:
                return None
            placeholders = {
                "your_openai_api_key_here",
                "your_ark_api_key_here",
                "your_siliconflow_api_key_here",
                "__YOUR_API_KEY__",
                "__YOUR_ARK_API_KEY__",
                "__YOUR_SILICONFLOW_API_KEY__",
            }
            if normalized in placeholders:
                return None
            return normalized

        def _env(name: str) -> Optional[str]:
            return _valid_env_value(env_value(name))

        # Provider registry — priority order: ARK → OpenAI-compatible → SiliconFlow generic
        # Each tuple: (display_name, key_env, url_env, default_url, model_env, default_model)
        # Resolving api_key / base_url / model from the SAME provider keeps the client coherent.
        _PROVIDER_REGISTRY = [
            (
                "ARK",
                "ARK_API_KEY",
                "ARK_BASE_URL",
                "https://ark.cn-beijing.volces.com/api/v3",
                "ARK_MODEL",
                None,  # model is mandatory for ARK — no safe default
            ),
            (
                "OpenAI",
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                None,  # official OpenAI endpoint (SDK default)
                "OPENAI_MODEL",
                "gpt-4o-mini",
            ),
            (
                "SiliconFlow",
                "SILICONFLOW_API_KEY",
                "SILICONFLOW_EMBEDDING_BASE_URL",
                "https://api.siliconflow.cn/v1",
                "SILICONFLOW_EMBEDDING_MODEL",
                "BAAI/bge-m3",
            ),
        ]

        self.provider_name = "none"
        self.api_key = None
        self.base_url = base_url  # honour explicit arg regardless of provider
        self.model = model

        # 1) Explicit key arg takes absolute priority
        _explicit_key = _valid_env_value(api_key)
        if _explicit_key:
            self.provider_name = "custom"
            self.api_key = _explicit_key
            self.base_url = base_url
            self.model = model or "gpt-4o-mini"
        else:
            # 2) Walk registry; stop at first provider whose key is present
            for prov_name, key_env, url_env, default_url, model_env, default_model in _PROVIDER_REGISTRY:
                resolved_key = _env(key_env)
                if resolved_key:
                    self.provider_name = prov_name
                    self.api_key = resolved_key
                    self.base_url = base_url or _env(url_env) or default_url
                    self.model = model or _env(model_env) or default_model
                    break

        self.enabled = False

        if self.api_key:
            self.client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=60.0,
            )
            self.enabled = True
            self.llm_status = "enabled"
            logger.info(
                "AIAdapter 启用成功。提供商: %s, 模型: %s, base_url: %s",
                self.provider_name,
                self.model,
                self.base_url or "(SDK默认)",
            )
        else:
            self.client = None
            self.llm_status = "disabled_missing_api_key"
            logger.warning("AIAdapter 未启用: 未找到有效的 API_KEY (已尝试 ARK / OpenAI / SiliconFlow)。")

        # Generation pool (Phase A2): non-fatal failover for 429/auth/network.
        # When present, _invoke_chat walks pool credentials with cooldown.
        self._pool = _resolve_generation_pool() if self.enabled else None
        self._client_cache: dict[Any, Any] = {}

    def _build_client_for_cred(self, cred: Any) -> Any:
        """Return a cached openai.OpenAI client bound to a pool credential."""
        cache_key = getattr(cred, "cred_id", None) or (
            getattr(cred, "api_key", "")[:12],
            getattr(cred, "base_url", ""),
            getattr(cred, "model", ""),
        )
        cached = self._client_cache.get(cache_key)
        if cached is None:
            cached = openai.OpenAI(
                api_key=cred.api_key,
                base_url=cred.base_url,
                timeout=60.0,
            )
            self._client_cache[cache_key] = cached
        return cached

    def _invoke_chat(self, kwargs: dict[str, Any]) -> Any:
        """Dispatch chat completion. Walks generation pool when available; otherwise
        falls back to the single client built from the env-resolved provider.

        Pool members are expected to serve semantically equivalent models so the
        gateway cache key (self.model) stays meaningful. If pool members
        diverge widely, set LLM_GENERATION_CACHE_ENABLED=0 to bypass cache.

        Internal dispatcher migration.
        By default this walks the pool via ``model_dispatcher.invoke_failover``
        + ``generation_dispatch_adapter`` (same pattern as
        ``with_generation_pool_failover``). Behaviour is byte-equivalent —
        attempt order, cooldown state, return value, and (last) exception
        class are preserved per ``tests/test_ai_adapter_dispatcher_migration.py``.

        Set ``LIT_DISPATCHER_FOR_AI_ADAPTER=0`` to force the legacy
        ``pool.try_call`` path for emergency rollback. No code change required.
        """
        pool = getattr(self, "_pool", None)
        if pool is None:
            return self.client.chat.completions.create(**kwargs)

        def _invoke_with_cred(cred: Any) -> Any:
            client = self._build_client_for_cred(cred)
            cred_kwargs = dict(kwargs)
            if getattr(cred, "model", None):
                cred_kwargs["model"] = cred.model
            return client.chat.completions.create(**cred_kwargs)

        use_dispatcher = os.environ.get("LIT_DISPATCHER_FOR_AI_ADAPTER", "1") == "1"
        if not use_dispatcher:
            return pool.try_call(_GENERATION_CATEGORY, _invoke_with_cred)

        # Default: dispatcher + adapter path
        try:
            from generation_dispatch_adapter import (  # noqa: PLC0415
                build_candidates_from_pool,
                make_pool_invoke_wrapper,
            )
            from model_dispatcher import invoke_failover  # noqa: PLC0415
        except ImportError:
            # Defensive fallback: legacy path if adapter import fails
            return pool.try_call(_GENERATION_CATEGORY, _invoke_with_cred)

        candidates = build_candidates_from_pool(pool, _GENERATION_CATEGORY)
        if not candidates:
            return self.client.chat.completions.create(**kwargs)

        # Capture the actual underlying exception object so we can re-raise it
        # with its original class on all-fail (preserves caller ``isinstance``
        # checks). Same pattern as ``with_generation_pool_failover``.
        last_exc_box: list[BaseException] = []

        def _fn(cred: Any) -> Any:
            try:
                return _invoke_with_cred(cred)
            except BaseException as exc:  # noqa: BLE001 — capture for re-raise
                last_exc_box.append(exc)
                raise

        wrapper = make_pool_invoke_wrapper(pool, _GENERATION_CATEGORY, _fn)
        batch = invoke_failover(candidates, wrapper, raise_on_all_fail=False)

        if batch.first_success is not None:
            return batch.first_success.output

        # All candidates failed — preserve legacy semantics
        if last_exc_box:
            raise last_exc_box[-1]
        raise RuntimeError(
            f"key_pool[{_GENERATION_CATEGORY}]: no credentials available "
            "(all in cooldown or pool empty)"
        )

    def provider_info(self) -> Dict[str, Any]:
        """返回当前激活的提供商信息（用于诊断日志，不包含 key 值）。"""
        return {
            "provider": self.provider_name,
            "model": self.model,
            "base_url": self.base_url or "(SDK默认)",
            "enabled": self.enabled,
            "status": self.llm_status,
        }

    def _chat(
        self,
        prompt: str,
        *,
        task: str,
        overrides: dict | None = None,
        response_format: dict | None = None,
    ):
        """统一 LLM 调用入口：解析 sampling + 埋点。"""
        params = resolve_llm_params(task, user_overrides=overrides)
        sampling_payload: dict[str, Any] = {
            "temperature": params["temperature"],
            "top_p": params["top_p"],
            "max_tokens": params["max_tokens"],
            "top_k": params["top_k"],
        }
        if response_format:
            sampling_payload["response_format"] = response_format
        kwargs = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": params["temperature"],
            "top_p": params["top_p"],
        }
        if params.get("max_tokens"):
            kwargs["max_tokens"] = params["max_tokens"]
        if params.get("top_k") is not None:
            kwargs["extra_body"] = {"top_k": params["top_k"]}
        if response_format:
            kwargs["response_format"] = response_format
        t0 = time.perf_counter()
        status = "ok"
        response = None
        cache_status = "miss"
        decision = "invoke"
        try:
            def _record_decision(next_cache_status: str, next_decision: str) -> None:
                nonlocal cache_status, decision
                cache_status = next_cache_status
                decision = next_decision

            response = invoke_llm_gateway(
                kind="llm",
                cache_key_parts={
                    "model": self.model,
                    "prompt_hash": _hash_text(prompt),
                    "sampling_params_hash": _hash_payload(sampling_payload),
                    "task": task,
                },
                payload=kwargs,
                invoke_fn=lambda: self._invoke_chat(kwargs),
                on_decision=_record_decision,
                stage="query",
            )
            return response
        except Exception:
            status = "error"
            raise
        finally:
            try:
                latency_ms = (time.perf_counter() - t0) * 1000
                usage = usage_from_response(response) if response is not None else {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                }
                log_llm_call(
                    model=self.model,
                    task=task,
                    prompt_tokens=usage["prompt_tokens"],
                    completion_tokens=usage["completion_tokens"],
                    latency_ms=latency_ms,
                    status=status,
                    cache_status=cache_status,
                    decision=decision,
                )
            except Exception:
                logger.debug("LLM telemetry logging failed", exc_info=True)

    def extract_claims(self, text: str, goal: str) -> List[Dict[str, Any]]:
        """
        利用 LLM 从文本片段中提取高价值的学术主张(Claim)。
        取代了原先利用正则判断 `RESULT_CUES` 等启发式逻辑。
        """
        if not self.enabled:
            return []

        prompt = f"""你是一个顶级的材料科学与制造领域专家。
目标(Goal): {goal}

请阅读以下文本片段，提取其中最具代表性的学术结论或机制发现。
每个结论必须是独立的、完整的陈述句。如果文本中没有实质性结论，请返回空列表。

文本:
{text}

请以 JSON 格式输出，使用以下结构：
[
    {{
        "claim": "这里是提取的核心主张或结论",
        "point_type": "[result|mechanism|method|background|discussion]",
        "confidence": 0.95,
        "boundary_type": "[result_fact|explanation|inference]",
        "boundary_note": "对证据边界的简短说明"
    }}
]
        """
        try:
            response = self._chat(
                prompt,
                task="extraction",
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            # 使用鲁棒的解析器代替 json.loads
            data = self.parser.parse(content, fallback=[])
            
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # 如果模型将结果包裹在字典中 (例如 {"claims": [...]}), 进行解包
                for k, v in data.items():
                    if isinstance(v, list):
                        return v
                # 如果字典本身就是一个 claim (不推荐但兼容)
                if "claim" in data:
                    return [data]
            return []
        except Exception as e:
            logger.error(f"提取 Claim 失败: {e}")
            return []

    def verify_multimodal_support(self, claim: str, caption: str) -> float:
        """
        多模态增强校验：判断图题/表题是否真的构成了对该结论的支撑证据。
        返回 0.0 到 1.0 的支撑度置信分。
        """
        if not self.enabled:
            # 回退到基础正则重叠计分
            return 0.5

        prompt = f"""
你需要判断一篇学术论文中的图表是否能够支撑特定的文本结论。

【文本结论】:
{claim}

【图表标题(Caption)】:
{caption}

请分析两者之间的逻辑和语义关联度。只输出一个介于 0.0 到 1.0 之间的数字。
(例如: 0.9 代表强支撑，0.5 代表弱关联或同主题，0.1 代表无关)
        """
        try:
            response = self._chat(
                prompt,
                task="extraction",
                overrides={"temperature": 0.1, "max_tokens": 10},
            )
            score_str = response.choices[0].message.content.strip()
            # 简单提取出第一个浮点数
            import re
            match = re.search(r'0\.\d+|1\.0', score_str)
            if match:
                return float(match.group())
            return 0.5
        except Exception as e:
            logger.error(f"验证 Multimodal Support 失败: {e}")
            return 0.5

    def extract_mechanisms(self, text: str, goal: str) -> List[Dict[str, Any]]:
        """
        从文本中提取机制解释和因果关系。
        返回结构化的因果链和机制描述。
        """
        if not self.enabled:
            return []

        prompt = f"""你是一个材料科学与制造领域的专家。
目标(Goal): {goal}

请从以下文本中提取所有的机制解释、因果关系或物理模型。
每个机制应该包含：原因、过程、结果三部分。

文本:
{text}

请以 JSON 列表格式输出：
[
    {{
        "mechanism": "完整的机制描述（通常包含'因为...导致...'结构）",
        "cause": "原因或驱动因素",
        "process": "中间过程或转化过程",
        "effect": "最终结果或效应",
        "mechanism_type": "[thermodynamic|kinetic|nucleation|growth|precipitation|transformation|stress]",
        "confidence": 0.9,
        "reference_entities": ["工艺参数、化学成分等关键实体"]
    }}
]
        """
        try:
            response = self._chat(
                prompt,
                task="extraction",
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            data = self.parser.parse(content, fallback=[])
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, list):
                        return v
            return []
        except Exception as e:
            logger.error(f"提取机制失败: {e}")
            return []

    def verify_evidence_chain(self, claim: str, supporting_texts: List[str]) -> Dict[str, Any]:
        """
        证据链核验：验证一个 Claim 是否由足够的证据支撑。
        返回置信度、证据强度和缺失证据的说明。
        """
        if not self.enabled:
            return {
                "claim": claim,
                "evidence_strength": 0.5,
                "confidence": 0.5,
                "evidence_gaps": ["LLM disabled - using baseline fallback"],
                "boundary_type": "unverified"
            }

        evidence_text = "\n".join(supporting_texts)
        prompt = f"""你是一个学术论文评审专家。
你需要评估以下学术主张是否由充分的证据支撑。

【学术主张】:
{claim}

【支持证据】:
{evidence_text}

请进行以下分析：
1. 这个主张在证据中是否有明确支持？
2. 证据的强度如何？(强/中等/弱)
3. 是否存在缺失的关键证据？

请以 JSON 格式输出：
{{
    "is_supported": true,
    "evidence_strength": "strong",
    "confidence": 0.85,
    "evidence_gaps": ["缺失的证据要素"],
    "boundary_type": "[result_fact|explanation|inference]",
    "supporting_evidence": ["最关键的支持证据片段"],
    "explanation": "简要说明为什么这个主张成立或不成立"
}}
        """
        try:
            response = self._chat(
                prompt,
                task="extraction",
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            result = json.loads(content)
            result["claim"] = claim
            return result
        except Exception as e:
            logger.error(f"证据链核验失败: {e}")
            return {
                "claim": claim,
                "is_supported": False,
                "evidence_strength": "unknown",
                "confidence": 0.0,
                "evidence_gaps": [str(e)],
                "boundary_type": "error"
            }

    def extract_innovation_points(self, text: str, goal: str, background_context: str = "") -> List[Dict[str, Any]]:
        """
        创新点提取：识别文献中相对于背景文献和已知技术的创新之处。
        """
        if not self.enabled:
            return []

        prompt = f"""你是顶级的材料科学与制造研究员。
目标(Goal): {goal}

背景/现状:
{background_context if background_context else '（无背景信息）'}

原文内容:
{text}

请从上述原文中识别出所有的创新之处或突破。创新可能包括：
- 新的工艺参数组合
- 新的材料系统或成分设计
- 新的分析方法或验证手段
- 对已知机制的新理解或推进
- 性能上的新突破

请以 JSON 列表格式输出：
[
    {{
        "innovation": "创新的完整描述",
        "innovation_type": "[process|material|mechanism|characterization|performance]",
        "novelty_level": "[incremental|moderate|breakthrough]",
        "confidence": 0.85,
        "prior_art": "该创新相对于已知技术的改进说明（如果有的话）"
    }}
]
        """
        try:
            response = self._chat(
                prompt,
                task="extraction",
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, list):
                        return v
            return []
        except Exception as e:
            logger.error(f"提取创新点失败: {e}")
            return []

    def classify_claim_boundary(self, claim: str, source_text: str) -> Dict[str, Any]:
        """
        边界分类：判断一个 Claim 是直接的实验/观察结果、推导解释还是推断。
        """
        if not self.enabled:
            return {
                "claim": claim,
                "boundary_type": "unknown",
                "confidence": 0.5,
                "justification": "LLM disabled"
            }

        prompt = f"""你是学术论文评审专家。
你需要对以下学术主张进行"证据边界"分类。

【学术主张】:
{claim}

【源文本】:
{source_text}

请判断这个主张属于以下哪一类：
1. 'result_fact': 直接的实验观察或测量结果 (例如："钛合金硬度为 350HV")
2. 'explanation': 对实验结果的机制解释 (例如："硬度提高是由于析出强化")
3. 'inference': 推导性结论或假设 (例如："推测该机制可能导致...")
4. 'review_statement': 综述性或公认观点 (例如："众所周知...")

请输出 JSON：
{{
    "boundary_type": "[result_fact|explanation|inference|review_statement]",
    "confidence": 0.85,
    "justification": "你的判断理由",
    "evidence_indicators": ["支持该分类的关键词或短语"]
}}
        """
        try:
            response = self._chat(
                prompt,
                task="extraction",
                overrides={"temperature": 0.2},
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            result = json.loads(content)
            result["claim"] = claim
            return result
        except Exception as e:
            logger.error(f"边界分类失败: {e}")
            return {
                "claim": claim,
                "boundary_type": "unknown",
                "confidence": 0.0,
                "justification": str(e)
            }

    def enhance_writing_association(
        self,
        query: str,
        focus_terms: List[str],
        related_signals: List[Dict[str, Any]],
        association_angles: List[Dict[str, Any]],
        continuation_prompts: List[str],
        evidence_gaps: List[Dict[str, Any]],
        recommended_memory_queries: List[str],
        angle_limit: int = 3,
    ) -> Dict[str, Any]:
        """
        使用 LLM 在已有证据约束下增强联想写作输出。

        Why:
            AI 模式应该建立在可追溯证据之上，而不是替换掉无 AI 的稳定规则基线。
            该接口只增强“角度/续写/缺口/后续检索”，不重排底层证据来源。
        """
        if not self.enabled:
            return {}
        if not isinstance(query, str) or not query.strip():
            return {}

        signal_payload: List[Dict[str, Any]] = []
        for raw_signal in related_signals[:6]:
            if not isinstance(raw_signal, dict):
                continue
            signal_payload.append(
                {
                    "source_id": str(raw_signal.get("source_id", "")).strip(),
                    "source_type": str(raw_signal.get("source_type", "")).strip(),
                    "title": str(raw_signal.get("title", "")).strip(),
                    "excerpt": str(raw_signal.get("excerpt", "")).strip()[:220],
                    "shared_terms": list(raw_signal.get("shared_terms", []))[:4],
                    "rationale": str(raw_signal.get("rationale", "")).strip(),
                    "score": raw_signal.get("score", 0.0),
                }
            )

        baseline_payload = {
            "focus_terms": list(focus_terms[:8]),
            "association_angles": list(association_angles[:angle_limit]),
            "continuation_prompts": list(continuation_prompts[:4]),
            "evidence_gaps": list(evidence_gaps[:4]),
            "recommended_memory_queries": list(recommended_memory_queries[:4]),
        }

        prompt = f"""你是“联想写作助手”的 AI 增强模式。
你的任务是：在不脱离证据的前提下，增强当前写作查询的联想角度、续写提示、证据缺口和后续检索词。

必须严格遵守：
1. 只能基于提供的 related_signals 组织建议，不允许引入新的事实来源。
2. association_angles 中的 supporting_source_ids 只能来自 related_signals 的 source_id。
3. continuation_prompts 必须直接服务于下一段写作，而不是泛泛建议。
4. evidence_gaps 只能指出“当前证据还缺什么”，不要虚构文献。
5. 推荐输出要比 baseline 更贴近写作动作，但保持简洁、可执行。

当前 query:
{query}

related_signals:
{json.dumps(signal_payload, ensure_ascii=False)}

baseline:
{json.dumps(baseline_payload, ensure_ascii=False)}

请只输出 JSON 对象，结构如下：
{{
  "association_angles": [
    {{
      "title": "string",
      "prompt": "string",
      "supporting_source_ids": ["source_id"],
      "shared_terms": ["term"],
      "confidence": 0.0
    }}
  ],
  "continuation_prompts": ["string"],
  "evidence_gaps": [
    {{
      "gap": "string",
      "severity": "low|medium|high",
      "recommendation": "string"
    }}
  ],
  "recommended_memory_queries": ["string"]
}}
        """
        try:
            response = self._chat(
                prompt,
                task="rewrite",
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            data = self.parser.parse(content, fallback={})
            if not isinstance(data, dict):
                return {}

            known_source_ids = {
                str(item.get("source_id", "")).strip()
                for item in signal_payload
                if str(item.get("source_id", "")).strip()
            }

            normalized_angles: List[Dict[str, Any]] = []
            for index, raw_angle in enumerate(data.get("association_angles", []), start=1):
                if not isinstance(raw_angle, dict):
                    continue
                prompt_text = str(raw_angle.get("prompt", "")).strip()
                if not prompt_text:
                    continue
                supporting_source_ids = [
                    source_id
                    for source_id in (
                        str(source_id).strip()
                        for source_id in raw_angle.get("supporting_source_ids", [])
                    )
                    if source_id in known_source_ids
                ]
                shared_terms = [
                    str(term).strip()
                    for term in raw_angle.get("shared_terms", [])
                    if str(term).strip()
                ]
                try:
                    confidence = float(raw_angle.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                normalized_angles.append(
                    {
                        "title": str(raw_angle.get("title", "")).strip() or f"AI Angle {index}",
                        "prompt": prompt_text,
                        "supporting_source_ids": supporting_source_ids,
                        "shared_terms": shared_terms,
                        "confidence": max(0.0, min(1.0, confidence)),
                    }
                )

            normalized_prompts = [
                str(item).strip()
                for item in data.get("continuation_prompts", [])
                if str(item).strip()
            ]
            normalized_gaps: List[Dict[str, str]] = []
            for raw_gap in data.get("evidence_gaps", []):
                if not isinstance(raw_gap, dict):
                    continue
                gap_text = str(raw_gap.get("gap", "")).strip()
                recommendation = str(raw_gap.get("recommendation", "")).strip()
                if not gap_text or not recommendation:
                    continue
                severity = str(raw_gap.get("severity", "medium")).strip().lower()
                if severity not in {"low", "medium", "high"}:
                    severity = "medium"
                normalized_gaps.append(
                    {
                        "gap": gap_text,
                        "severity": severity,
                        "recommendation": recommendation,
                    }
                )

            normalized_queries = [
                str(item).strip()
                for item in data.get("recommended_memory_queries", [])
                if str(item).strip()
            ]

            return {
                "association_angles": normalized_angles[:angle_limit],
                "continuation_prompts": normalized_prompts[:4],
                "evidence_gaps": normalized_gaps[:4],
                "recommended_memory_queries": normalized_queries[:4],
            }
        except Exception as e:
            logger.error(f"联想写作 AI 增强失败: {e}")
            return {}
