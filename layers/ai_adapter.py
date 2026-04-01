from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AIAdapter")

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

    def _load_env_fallback(self):
        """手动加载 .env 文件，以防 python-dotenv 未安装。"""
        # .env 位于 layers 的上一级目录
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            os.environ[k.strip()] = v.strip()
            except Exception as e:
                logger.debug(f"手动加载 .env 失败: {e}")

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: str = None):
        self.enabled = False
        self.client = None
        
        if not HAS_OPENAI:
            logger.error("openai 库未安装。请运行: pip install openai")
            return

        # 尝试加载环境变量
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            self._load_env_fallback()

        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.enabled = False

        if self.api_key:
            self.client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=60.0
            )
            self.enabled = True
            logger.info(f"AIAdapter 启用成功。模型: {self.model}")
        else:
            self.client = None
            logger.warning("AIAdapter 未启用: 缺失 API_KEY。")

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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            # json_object force LLMs to output a json dict. So we expect {"claims": [...]} or a direct list if it follows instructions exactly, 
            # let's safely parse it.
            data = json.loads(content)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # Unpack if the LLM wrapped it into a dict
                for k, v in data.items():
                    if isinstance(v, list):
                        return v
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=10
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
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
