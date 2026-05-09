import re
import json
import logging
from typing import Any, Dict, List, Optional, Union

# 配置日志
logger = logging.getLogger("RobustJSONParser")

class RobustJSONParser:
    """
    鲁棒的 JSON 解析器，专门用于处理 LLM (如 GPT, Claude, Qwen) 产生的不规范或截断的 JSON 文本。
    
    该解析器通过一系列分级修复策略，尽可能从损坏的文本中挽救结构化数据。
    
    修复策略包括：
    1. 剥离 Markdown 代码块 (```json ... ```)
    2. 修复 JSON 对象或数组末尾多余的逗号
    3. 将单引号转换为双引号（仅限非字符串内部）
    4. 对由于 LLM 截断导致的缺失括号进行自动补全
    """

    @staticmethod
    def parse(text: str, fallback: Optional[Dict] = None) -> Union[Dict[str, Any], Any]:
        """
        鲁棒解析 JSON 对象。
        
        Args:
            text: 原始文本字符串
            fallback: 解析失败时的回退值，默认为 {}
            
        Returns:
            解析后的 Python 字典或 fallback
        """
        if fallback is None:
            fallback = {}

        if not text or not isinstance(text, str):
            logger.warning("解析输入为空或非法类型")
            return fallback

        # 1. 尝试直接解析
        success, result = RobustJSONParser._try_parse(text)
        if success:
            logger.debug("JSON 直接解析成功")
            return result

        # 2. 剥离 Markdown 代码块
        cleaned = RobustJSONParser._strip_markdown(text)
        success, result = RobustJSONParser._try_parse(cleaned)
        if success:
            logger.info("JSON 解析成功 (通过剥离 Markdown)")
            return result

        # 3. 修复尾部逗号
        cleaned = RobustJSONParser._fix_trailing_commas(cleaned)
        success, result = RobustJSONParser._try_parse(cleaned)
        if success:
            logger.info("JSON 解析成功 (通过修复尾部逗号)")
            return result

        # 4. 修复引号问题
        cleaned = RobustJSONParser._fix_quotes(cleaned)
        success, result = RobustJSONParser._try_parse(cleaned)
        if success:
            logger.info("JSON 解析成功 (通过修复引号)")
            return result

        # 5. 修复截断 (补齐括号)
        cleaned = RobustJSONParser._repair_truncated(cleaned)
        success, result = RobustJSONParser._try_parse(cleaned)
        if success:
            logger.info("JSON 解析成功 (通过修复截断补齐)")
            return result

        logger.warning(f"JSON 解析全部策略均失败。输入片段: {text[:50]}...")
        return fallback

    @staticmethod
    def parse_list(text: str, fallback: Optional[List] = None) -> List[Any]:
        """
        鲁棒解析 JSON 列表。
        """
        if fallback is None:
            fallback = []
        result = RobustJSONParser.parse(text, fallback=fallback)
        return result if isinstance(result, list) else fallback

    @staticmethod
    def _try_parse(text: str) -> tuple[bool, Any]:
        """尝试进行一次 json.loads"""
        try:
            return True, json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return False, None

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """剥离 ```json ... ``` 或 ``` ... ```"""
        # 移除 json 标记包裹
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)
        return text.strip()

    @staticmethod
    def _fix_trailing_commas(text: str) -> str:
        """移除 JSON 中非法的尾部逗号 (如 {"a": 1,} -> {"a": 1})"""
        # 匹配逗号后紧跟闭合括号的情况
        return re.sub(r',(\s*[}\]])', r'\1', text)

    @staticmethod
    def _fix_quotes(text: str) -> str:
        """将对象键或字符串的单引号转换为双引号 (启发式修复)"""
        # 修复简单的 {'key': 'value'} 模式
        text = re.sub(r"(['])(\w+)(['])\s*:", r'"\2":', text)
        text = re.sub(r":\s*(['])(.*?[^\\])(['])", r': "\2"', text)
        return text

    @staticmethod
    def _repair_truncated(text: str) -> str:
        """补全截断产生的缺失括号，支持基础的结构闭合"""
        # 移除末尾可能的非闭合逗号
        text = text.strip()
        while text.endswith(','):
            text = text[:-1].strip()

        open_braces = text.count('{')
        close_braces = text.count('}')
        open_brackets = text.count('[')
        close_brackets = text.count(']')
        
        # 补充缺失的闭合符号
        if open_braces > close_braces:
            text += '}' * (open_braces - close_braces)
        if open_brackets > close_brackets:
            text += ']' * (open_brackets - close_brackets)
        
        return text
