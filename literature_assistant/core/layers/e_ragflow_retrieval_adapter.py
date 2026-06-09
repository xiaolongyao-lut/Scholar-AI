# -*- coding: utf-8 -*-
"""
RAGFlow Retrieval Adapter (v1.6 REST Implementation - Production Ready)
Role: Hybrid Retrieval Bridge using REST API (Vector + BM25)

Single Responsibility: This module is strictly scoped to executing RAGFlow
retrieval calls, parameter validation, response standardization, resource
teardown, and emitting failure fallback signals. It does NOT perform PDF
parsing, table extraction, or any downstream business logic.
Features: Connection pooling, credential validation, parameter validation, SSL verification,
          thread-safe, retry mechanism, resource management, timeout optimization,
          request telemetry, and standardized metadata mapping.

Required Dependencies:
    - requests: HTTP client library (core dependency)
    - urllib3: HTTP library for requests (core dependency)

Optional Dependencies:
    - numpy: For enhanced type detection (gracefully handled if missing)

Installation:
    pip install requests urllib3

Best Practices for Logging:
    This module emits logs to the "RAGFlowAdapter" logger. To configure logging
    in your application, do NOT attach handlers to this logger. Instead, configure
    logging at your application's entry point:

    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    This ensures consistent logging behavior across all modules.
"""

import logging
import os
import threading
import time
import uuid
import hashlib
from typing import Dict, Any, List, Optional, Type

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class RAGFlowAPIError(Exception):
    """Custom exception for RAGFlow API errors."""
    pass

class APIFields:
    """Namespace for API Response constants."""
    SUCCESS_CODE = "0"
    SUCCESS_CODE_FIELD = "code"
    MESSAGE = "message"
    DATA = "data"
    CHUNKS = "chunks"
    CONTENT = "content"
    VECTOR_SIMILARITY = "vector_similarity"
    TERM_SIMILARITY = "term_similarity"
    SIMILARITY = "similarity"
    ID = "id"
    DOCUMENT_ID = "document_id"
    DOCUMENT_KEYWORD = "document_keyword"
    CHUNK_INDEX = "chunk_index"

# Module level logger initialization
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logger.addHandler(logging.NullHandler())


class RAGFlowAdapter:
    """
    RAGFlow 检索适配器（Retrieval Adapter）：通过 REST API 对接 RAGFlow 的混合检索接口。
    支持向量相似度与 BM25 关键词匹配的混合检索。

    核心特性：
    - 连接池复用 (Session)
    - API Key 强化校验
    - 参数边界检查
    - 显式 SSL 验证
    - 标准异常处理
    - 异步响应兼容

    # 生产级特性：
    # - 依赖 requests.Session 内建的线程安全
    # - 重试机制 (指数退避)
    # - 显式资源管理 (支持与 with 语句集成的上下文处理器)
    - 细粒度超时控制 (连接超时 vs 读取超时)
    - 标准 User-Agent 头
    - 请求耗时遥测 (Telemetry)
    - 可选参数支持 (keyword、rerank_id、document_ids)

    使用示例：
        with RAGFlowAdapter(api_key="your_api_key") as adapter:
            results = adapter.retrieve(
                question="测试问题",
                dataset_ids=["dataset_1"],
                top_k=10,
                keyword="optional_keyword"
            )
    """

    # 默认配置（可由环境变量覆盖）
    DEFAULT_BASE_URL = os.getenv("RAGFLOW_BASE_URL", "https://localhost:9380")
    DEFAULT_TOP_K = 10
    DEFAULT_SIMILARITY_THRESHOLD = 0.2
    DEFAULT_VECTOR_WEIGHT = 0.5

    # 参数边界常量
    MIN_TOP_K = 1
    MAX_TOP_K = 1000
    MIN_THRESHOLD = 0.0
    MAX_THRESHOLD = 1.0
    MIN_WEIGHT = 0.0
    MAX_WEIGHT = 1.0

    # 超时配置（单位：秒）这里只保留默认值，由 __init__ 解析环境变量
    DEFAULT_CONNECT_TIMEOUT = 5
    DEFAULT_READ_TIMEOUT = 25

    # 重试策略参数
    MAX_RETRIES = 3
    BACKOFF_FACTOR = 0.3
    RETRY_STATUS_CODES = [429, 500, 502, 503, 504]

    # HTTP 状态码与终点
    HTTP_OK = 200
    API_ENDPOINT = "/api/v1/retrieval"
    USER_AGENT = "RAGFlowAdapter/1.6 (Production Ready)"

    # 响应元数据常量
    DEFAULT_METADATA_SOURCE_TYPE = "ragflow_integrated"
    logger = logger

    def __init__(
        self, 
        api_key: Optional[str] = None, 
        base_url: Optional[str] = None,
        verify_ssl: bool = True,
        connect_timeout: Optional[int] = None,
        read_timeout: Optional[int] = None,
        max_retries: int = MAX_RETRIES
    ) -> None:
        """
        初始化 RAGFlow REST 客户端。

        Args:
            api_key: RAGFlow API Key。如果未提供，优先从 RAGFLOW_API_KEY 环境变量获取。
            base_url: RAGFlow 服务地址。如果未提供，则使用 DEFAULT_BASE_URL。
            verify_ssl: 是否验证 SSL 证书。
            connect_timeout: 连接超时时间。
            read_timeout: 读取超时时间。
            max_retries: 最大重试次数。

        Raises:
            ValueError: 当 API Key 缺失或 base_url 格式无效时。
            RuntimeError: 当在生产环境检测到不安全配置时。
        """
        # Initialize attributes early to ensure they always exist
        self.session = None
        self._closed = False
        self._lock = threading.Lock()

        self.api_key = api_key or os.environ.get('RAGFLOW_API_KEY')
        if not self.api_key:
            raise ValueError(
                "API Key is required. Provide via api_key parameter or RAGFLOW_API_KEY environment variable."
            )

        target_base_url = (base_url or self.DEFAULT_BASE_URL).rstrip('/')
        if not (target_base_url.lower().startswith('http://') or target_base_url.lower().startswith('https://')):
            raise ValueError(f"base_url must start with http:// or https://, got: {target_base_url}")

        self.base_url = target_base_url
        self.verify_ssl = verify_ssl

        # Parse timeout environment variables using helper function
        self.connect_timeout = self._parse_timeout_env(
            "RAGFLOW_CONNECT_TIMEOUT", 
            connect_timeout, 
            self.DEFAULT_CONNECT_TIMEOUT
        )
        self.read_timeout = self._parse_timeout_env(
            "RAGFLOW_READ_TIMEOUT", 
            read_timeout, 
            self.DEFAULT_READ_TIMEOUT
        )
        self.max_retries = max_retries

        # Validate HTTP security and SSL settings
        self._validate_http_security()

        # Pre-calculate API URL to avoid repeated concatenation
        self.api_url = f"{self.base_url}{self.API_ENDPOINT}"

        # Create session (already initialized to None above)
        self.session = self._create_session(max_retries)

    @staticmethod
    def _parse_timeout_env(env_var: str, param_value: Optional[int], default_value: int) -> int:
        """
        解析并验证超时配置。

        Args:
            env_var: 环境变量名称
            param_value: 参数值（具有最高优先级）
            default_value: 默认值

        Returns:
            有效的超时值（秒）

        Raises:
            ValueError: 当超时值为负数时
        """
        if param_value is not None:
            if param_value <= 0:
                raise ValueError(f"Timeout value must be positive, got {param_value}")
            return param_value

        try:
            env_value = int(os.getenv(env_var, str(default_value)))
            if env_value <= 0:
                logger.warning(
                    f"Invalid timeout from {env_var}: {env_value}. Using default: {default_value}"
                )
                return default_value
            return env_value
        except (ValueError, TypeError):
            logger.warning(
                f"Failed to parse {env_var} as integer. Using default: {default_value}"
            )
            return default_value

    @staticmethod
    def parse_bool_env(env_var: str, default_value: bool = True) -> bool:
        """从环境变量解析严格的布尔值。"""
        return os.getenv(env_var, str(default_value)).lower().strip() in ("true", "1", "yes")

    def _validate_http_security(self) -> None:
        """
        验证 HTTP 和 SSL 设置的安全性。

        此方法分别处理传输层安全（HTTP vs HTTPS）和证书验证（SSL verify）。
        注意：verify_ssl 仅对 HTTPS 有意义；HTTP 总是未加密的。

        允许在以下情况下使用 HTTP:
        1. 用户显式设置 RAGFLOW_ALLOW_INSECURE_HTTP=1（明确接受风险）
        2. 用户显式设置 verify_ssl=False（接受风险）
        3. 使用本地回环地址 (localhost, 127.0.0.1, ::1)

        推荐：在生产环境中使用 HTTPS。在信任的内部网络中，可以通过
        RAGFLOW_ALLOW_INSECURE_HTTP 环境变量明确授权 HTTP 访问。

        Raises:
            RuntimeError: 当检测到不安全的生产环境配置时
        """
        is_http = self.base_url.lower().startswith('http://')
        if not is_http:
            return

        allow_insecure = self.parse_bool_env("RAGFLOW_ALLOW_INSECURE_HTTP", False)
        if allow_insecure:
            logger.warning(
                f"SECURITY WARNING: Using unencrypted HTTP with RAGFLOW_ALLOW_INSECURE_HTTP=1. "
                f"API Key will be transmitted in plaintext. Use HTTPS in production. base_url: {self.base_url}"
            )
            return

        error_msg = (
            f"SECURITY ERROR: Using unencrypted HTTP is not permitted. "
            f"Please use HTTPS, or explicitly permit insecure HTTP by setting "
            f"RAGFLOW_ALLOW_INSECURE_HTTP=1 (only for trusted internal networks). "
            f"base_url: {self.base_url}"
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    def _create_session(self, max_retries: int) -> requests.Session:
        """
        创建并配置带有重试机制的请求会话。

        注意：重试策略仅在幂等方法（如 GET）上自动生效。
        由于 POST 操作可能触发非幂等的副作用（如计费），当前实现默认不重试 POST 请求。
        """
        session = requests.Session()
        session.verify = self.verify_ssl
        session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT
        })

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=self.BACKOFF_FACTOR,
            status_forcelist=self.RETRY_STATUS_CODES,
            # Removed allowed_methods=["POST"] to prevent non-idempotent retries by default
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def close(self) -> None:
        """
        Explicitly close session and release resources.

        Notes:
        - Once closed, this instance cannot be automatically recovered
        - Session credentials references are removed to minimize exposure
        - Create a new instance if reconnection is needed
        """
        with self._lock:
            if self._closed:
                return

            self._closed = True

            if self.session:
                try:
                    self.session.close()
                    logger.debug("RAGFlow Session closed successfully.")
                except Exception as e:
                    logger.warning(f"Exception during session closure: {type(e).__name__}: {e}")
                finally:
                    self.session = None

            if getattr(self, 'api_key', None):
                self.api_key = None


    @staticmethod
    def _is_boolean_type(value: Any) -> bool:
        """Check if value is a boolean (prevents bool bypass of int validation)."""
        return type(value) is bool

    @staticmethod
    def _validate_numeric(value: Any, field_name: str, min_val: float, max_val: float) -> float:
        """Validate numeric parameter within bounds.

        Args:
            value: Value to validate
            field_name: Field name for error messages
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)

        Returns:
            Validated numeric value

        Raises:
            ValueError: If validation fails
        """
        if type(value) is bool:
            raise ValueError(f"{field_name} must be a number, not a boolean.")

        if not isinstance(value, (int, float)):
            raise ValueError(f"{field_name} must be numeric, got {type(value).__name__}.")

        if not (min_val <= value <= max_val):
            raise ValueError(f"{field_name} must be between {min_val} and {max_val}, got {value}.")

        return float(value)

    @staticmethod
    def _validate_string(value: Any, field_name: str, required: bool = True) -> Optional[str]:
        """Validate and normalize string parameter.

        Args:
            value: Value to validate
            field_name: Field name for error messages
            required: If True, raise on None; if False, return None

        Returns:
            Normalized string or None if not required and value is None
        """
        if value is None:
            if required:
                raise ValueError(f"{field_name} is required.")
            return None

        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string, got {type(value).__name__}.")

        stripped = value.strip()
        if not stripped:
            if required:
                raise ValueError(f"{field_name} must be a non-empty string.")
            return None
        return stripped

    @staticmethod
    def _validate_string_param(value: Any, field_name: str) -> Optional[str]:
        """Validate optional string parameter and normalize blank values to None."""
        return RAGFlowAdapter._validate_string(value, field_name, required=False)

    def _validate_parameters(
        self, 
        question: str, 
        dataset_ids: List[str],
        top_k: int,
        similarity_threshold: float,
        vector_similarity_weight: float
    ) -> None:
        """Validate required parameters."""
        # Validate required strings
        self._validate_string(question, "question", required=True)

        if not dataset_ids or not isinstance(dataset_ids, list):
            raise ValueError("dataset_ids must be a non-empty list.")

        for dataset_id in dataset_ids:
            self._validate_string(dataset_id, "dataset_id", required=True)

        # Validate numeric parameters using consolidated validator
        self._validate_numeric(top_k, "top_k", self.MIN_TOP_K, self.MAX_TOP_K)
        self._validate_numeric(similarity_threshold, "similarity_threshold", self.MIN_THRESHOLD, self.MAX_THRESHOLD)
        self._validate_numeric(vector_similarity_weight, "vector_similarity_weight", self.MIN_WEIGHT, self.MAX_WEIGHT)

    @classmethod
    def _validate_document_ids(cls, document_ids: Any) -> Optional[List[str]]:
        """Validate document_ids parameter."""
        if document_ids is None:
            return None

        if not isinstance(document_ids, list):
            raise TypeError(f"document_ids must be a list or None, got {type(document_ids).__name__}.")

        valid_ids: List[str] = []
        for idx, doc_id in enumerate(document_ids):
            if not isinstance(doc_id, str):
                raise ValueError(
                    f"document_ids[{idx}] must be a string, got {type(doc_id).__name__}."
                )
            validated_id = doc_id.strip()
            if not validated_id:
                raise ValueError(
                    f"document_ids[{idx}] must be a non-empty string."
                )
            valid_ids.append(validated_id)

        return valid_ids if valid_ids else None

    def retrieve(
        self, 
        question: str, 
        dataset_ids: List[str], 
        top_k: int = DEFAULT_TOP_K,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        vector_similarity_weight: float = DEFAULT_VECTOR_WEIGHT,
        keyword: Optional[str] = None,
        rerank_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        调用 RAGFlow REST API 进行混合检索。

        Args:
            question: 检索问题
            dataset_ids: 数据集 ID 列表
            top_k: 返回结果数
            similarity_threshold: 相似度阈值
            vector_similarity_weight: 向量权重 [0, 1]
            keyword: 可选的关键词过滤
            rerank_id: 可选的重排模型 ID
            document_ids: 可选的文档 ID 范围限制

        返回结果将自动映射为符合文献处理器综述层 (G-Layer) 要求的结构。

        Raises:
            ValueError: 参数验证失败时
            TypeError: 可选参数类型错误时
            requests.RequestException: API 调用失败时
        """
        # Generate unique request ID for tracing in distributed environments
        request_id = str(uuid.uuid4())[:8]  # Must convert UUID to string first

        try:
            self._validate_parameters(
                question, dataset_ids, top_k, similarity_threshold, vector_similarity_weight
            )
        except (TypeError, ValueError) as e:
            logger.error(f"[{request_id}] Parameter validation failed: {e}")
            raise ValueError(str(e)) from e

        try:
            validated_keyword = self._validate_string(keyword, "keyword", required=False)
            validated_rerank_id = self._validate_string(rerank_id, "rerank_id", required=False)
            validated_document_ids = self._validate_document_ids(document_ids)
        except (TypeError, ValueError) as e:
            logger.error(f"[{request_id}] Optional parameter validation failed: {e}")
            raise ValueError(str(e)) from e

        # Check state and acquire session reference under lock
        with self._lock:
            if self._closed or not self.session:
                error_msg = "RAGFlow adapter is closed."
                logger.error(f"[{request_id}] {error_msg}")
                raise RuntimeError(error_msg)
            session = self.session

        # Build payload outside lock (no shared state access)
        payload: Dict[str, Any] = {
            "question": question,
            "dataset_ids": dataset_ids,
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": vector_similarity_weight
        }

        # Add optional parameters only if they have valid values
        if validated_keyword is not None:
            payload["keyword"] = validated_keyword
        if validated_rerank_id is not None:
            payload["rerank_id"] = validated_rerank_id
        if validated_document_ids is not None:
            payload["document_ids"] = validated_document_ids

        # Execute network I/O outside lock (allows concurrency)
        start_time = time.perf_counter()
        response = None  # Initialize response to prevent UnboundLocalError
        try:
            logger.info(f"[{request_id}] RAGFlow retrieval initiated (top_k={top_k})")
            timeout = (self.connect_timeout, self.read_timeout)
            response = session.post(self.api_url, json=payload, timeout=timeout)
            elapsed = time.perf_counter() - start_time

            if response.status_code != self.HTTP_OK:
                error_msg = f"RAGFlow API HTTP error {response.status_code} in {elapsed:.2f}s: {response.text[:200]}"
                logger.error(f"[{request_id}] {error_msg}")
                raise RAGFlowAPIError(error_msg)

            data = response.json()
            if str(data.get(APIFields.SUCCESS_CODE_FIELD)) != APIFields.SUCCESS_CODE:
                error_msg = f"RAGFlow logical error: {data.get(APIFields.MESSAGE)}"
                logger.error(f"[{request_id}] {error_msg}")
                raise RAGFlowAPIError(error_msg)

            logger.info(f"[{request_id}] RAGFlow retrieval success in {elapsed:.2f}s")
            return self._parse_retrieval_response(data)

        except requests.exceptions.ConnectionError as e:
            logger.error(f"[{request_id}] RAGFlow connection error: {e}")
            raise RAGFlowAPIError(f"Connection error: {e}") from e
        except requests.RequestException as e:
            logger.error(f"[{request_id}] RAGFlow API request failed: {e}")
            raise RAGFlowAPIError(f"Request failed: {e}") from e
        except (ValueError, KeyError) as e:
            response_text = response.text[:500] if response is not None else "No response"
            logger.error(
                f"[{request_id}] Failed to parse RAGFlow response: {e}. "
                f"Response (first 500 chars): {response_text}"
            )
            raise RAGFlowAPIError(f"Parse error: {e}") from e

    @staticmethod
    def _convert_score_to_float(value: Any, field_name: str, chunk_idx: int) -> float:
        """
        将分数值转换为浮点数，处理各种类型的输入。

        Args:
            value: 分数值
            field_name: 字段名称（用于日志）
            chunk_idx: 分块索引（用于日志）

        Returns:
            转换后的浮点数，或 0.0 如果转换失败
        """
        if value is None:
            return 0.0

        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(
                f"Failed to convert {field_name} to float in chunk {chunk_idx}: "
                f"value={value} (type={type(value).__name__}). Using 0.0 as fallback."
            )
            return 0.0

    @staticmethod
    def _generate_deterministic_id(content: str, chunk_idx: int) -> str:
        """Generate deterministic fallback chunk ID using content hash.

        Uses hashlib for true cross-process determinism (not subject to Python's
        hash() randomization). This ensures the same content always produces the
        same ID across process restarts, enabling caching and deduplication.
        """
        hash_input = f"{content}{chunk_idx}"
        hash_val = hashlib.sha256(hash_input.encode()).hexdigest()[:8]
        return f"chunk_{hash_val}"

    def _parse_single_chunk(self, chunk: Dict[str, Any], idx: int) -> Dict[str, Any]:
        """Parse a single chunk dictionary."""
        vector_score_raw = chunk.get(APIFields.VECTOR_SIMILARITY)
        bm25_score_raw = chunk.get(APIFields.TERM_SIMILARITY)
        hybrid_score_raw = chunk.get(APIFields.SIMILARITY, 0.0)

        vector_score = self._convert_score_to_float(vector_score_raw, APIFields.VECTOR_SIMILARITY, idx)
        bm25_score = self._convert_score_to_float(bm25_score_raw, APIFields.TERM_SIMILARITY, idx)
        hybrid_score = self._convert_score_to_float(hybrid_score_raw, APIFields.SIMILARITY, idx)

        content = chunk.get(APIFields.CONTENT, "")
        if not isinstance(content, str):
            content = str(content)

        chunk_id = chunk.get(APIFields.ID) or self._generate_deterministic_id(content, idx)

        return {
            "text": content,
            "source": chunk.get(APIFields.DOCUMENT_KEYWORD, "RAGFlow"),
            "score": hybrid_score,
            "id": chunk_id,
            "metadata": {
                "doc_id": chunk.get(APIFields.DOCUMENT_ID),
                "vector_score": vector_score,
                "bm25_score": bm25_score,
                "chunk_index": chunk.get(APIFields.CHUNK_INDEX),
                "source_type": self.DEFAULT_METADATA_SOURCE_TYPE
            }
        }

    def _parse_retrieval_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse and normalize RAGFlow API response."""
        results = []
        chunks = data.get(APIFields.DATA, {}).get(APIFields.CHUNKS, [])

        if not isinstance(chunks, list):
            logger.warning("Response chunks field is missing or not a list")
            return []

        skipped_count = 0
        for idx, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                skipped_count += 1
                continue

            try:
                results.append(self._parse_single_chunk(chunk, idx))
            except (KeyError, TypeError, ValueError) as e:
                if skipped_count == 0:
                    logger.warning(f"First chunk parsing failure: {type(e).__name__}: {e}. Raw chunk: {chunk}")
                skipped_count += 1
                continue

        if skipped_count > 0:
            logger.warning(f"Parsed {len(results)} chunks, skipped {skipped_count} due to errors")
        return results

    def __enter__(self) -> 'RAGFlowAdapter':
        """上下文处理器支持。"""
        return self

    def __exit__(
        self, 
        exc_type: Optional[Type[BaseException]], 
        exc_val: Optional[BaseException], 
        exc_tb: Optional[Any]
    ) -> bool:
        """自动关闭资源。"""
        self.close()
        return False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    test_key = os.getenv("RAGFLOW_API_KEY", "test_key")
    test_base_url = os.getenv("RAGFLOW_BASE_URL", "https://localhost:9380")

    # Parse environment variable using unified logic
    test_verify_ssl = RAGFlowAdapter.parse_bool_env("RAGFLOW_VERIFY_SSL", True)

    try:
        with RAGFlowAdapter(api_key=test_key, base_url=test_base_url, verify_ssl=test_verify_ssl) as adapter:
            print("✓ RAGFlow v1.5 Adapter Initialized (UTF-8 Clean).")
    except Exception as e:
        print(f"Initialization check failed: {e}")
