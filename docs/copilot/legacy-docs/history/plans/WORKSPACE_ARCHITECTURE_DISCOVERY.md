# Modular-Pipeline-Script 宸ヤ綔鍖烘灦鏋勬帰绱㈡姤鍛?

**鐢熸垚鏃堕棿**: 2026骞?鏈?1鏃? 
**鎶ュ憡鑼冨洿**: 瀹屾暣浠ｇ爜缁撴瀯鍒嗘瀽鍙婇泦鎴愮偣璇嗗埆

---

## 鎵ц鎽樿

璇ュ伐浣滃尯鏄竴涓灞傛鐨勫鏈枃鐚鐞嗙郴缁燂紝鏍稿績鐢变袱涓灦鏋勮酱绾跨粍鎴愶細
1. **鎭㈠/鍙娴嬫€ц酱绾?*: FastAPI 閫傞厤鍣ㄦ湇鍔″櫒 + 鎭㈠鎺у埗骞抽潰 + 浜嬩欢-浜嬪疄瀛樺偍浣撶郴
2. **鍐呭澶勭悊杞寸嚎**: 涓枃瀛︽湳鏂囩尞鎻愬彇銆佸垎鏋愯瘎鍒嗐€佺敓鎴愬拰浜や粯鐨勬ā鍧楀寲绠￠亾

---

## 1. Python FastAPI 搴旂敤缁撴瀯

### 1.1 Main Adapter Server 缁撴瀯

**鏂囦欢**: [python_adapter_server.py](python_adapter_server.py)

**鏍稿績鏋舵瀯**:
```
FastAPI App (line 108)
  鈹溾攢鈹€ HTTP Middleware锛堢110-189琛岋級
  鈹?  鈹斺攢鈹€ recovery_observability_middleware
  鈹?      鈹溾攢鈹€ 璁板綍 HTTP 鎸囨爣锛坮oute, method, status, duration锛?
  鈹?      鈹溾攢鈹€ 杩借釜闆嗘垚锛坱race_id, span_id锛?
  鈹?      鈹斺攢鈹€ telemetry & metrics 璁板綍
  鈹?
  鈹溾攢鈹€ Integrated Routers锛堢192-195琛岋級
  鈹?  鈹斺攢鈹€ app.include_router(autopilot_router)
  鈹?      鈹斺攢鈹€ from recovery_autopilot_router.py
  鈹?
  鈹斺攢鈹€ Optional Feature Modules锛堢34-85琛岋級
      鈹溾攢鈹€ HAS_PIPELINE 鈫?integrated_pipeline.run_pipeline
      鈹溾攢鈹€ HAS_SKILLS 鈫?skills.service.get_writing_skill_service
      鈹溾攢鈹€ HAS_RUNTIME 鈫?writing_runtime.get_writing_runtime
      鈹溾攢鈹€ HAS_HARNESS 鈫?harness_protocols.JobStatus
      鈹溾攢鈹€ HAS_RESOURCES 鈫?writing_resources.*
      鈹斺攢鈹€ HAS_MEMPALACE 鈫?layers.m_layer_mempalace_memory.MempalaceMemoryAdapter
```

**Route 缁勭粐**:
- **鎭㈠鍫嗘爤璺敱** (via `autopilot_router`):
  - `GET /recovery/autopilot/status` - 鑷姩椹鹃┒鐘舵€?
  - `POST /recovery/autopilot/enable|disable|emergency-stop|policy/set`
  - `GET /recovery/events` - 浜嬩欢鍘嗗彶
  - `GET /recovery/metrics` - Prometheus 鍏煎鎸囨爣瀵煎嚭
  - `GET /recovery/health` - 鍋ュ悍妫€鏌?

### 1.2 Recovery Autopilot Router 妯″潡缁撴瀯

**鏂囦欢**: [recovery_autopilot_router.py](recovery_autopilot_router.py)

**Pydantic 妯″瀷**锛堣姹?鍝嶅簲锛?
```python
AutopilotStatusResponse          # 鑷姩椹鹃┒鎺у埗骞抽潰鐘舵€?
AutopilotEnableRequest           # 鍚敤璇锋眰锛坧olicy 閫夊瀷锛?
AutopilotPolicySetRequest        # 鏀跨瓥鍒囨崲璇锋眰
AutopilotEmergencyActionRequest  # 绱ф€ユ搷浣滆姹?
PolicyInfo                       # 鏀跨瓥淇℃伅锛坣ame, policy_id, confidence_threshold, max_concurrent_actions锛?
EventLogEntry                    # 瑙勮寖浜嬩欢鏃ュ織鏉＄洰
ExecutionStatusResponse          # 鎵ц鐘舵€佸搷搴?
```

**鍏抽敭鐗规€?*:
- 璺敱鍓嶇紑: `/recovery`
- 鏀寔涓変釜鍐呯疆鏀跨瓥: `conservative`, `standard`, `permissive`
- 浠?`recovery_store_provider` 鑾峰彇浜嬩欢瀛樺偍鍜屼簨瀹炲瓨鍌?
- 闆嗘垚 `recovery_metrics_exporter` 杩涜鎸囨爣鏀堕泦

### 1.3 Pydantic 妯″瀷鍒嗗竷寮忓畾涔?

**Models 灞傜骇**:

| 浣嶇疆 | 妯″瀷绫?| 鐢ㄩ€?|
|------|--------|------|
| `python_adapter_server.py` | SkillDescriptorPayload | 鎶€鑳藉厓鏁版嵁 |
| `python_adapter_server.py` | WritingActionPayload | 浼犵粺鍐欎綔鍔ㄤ綔 |
| `python_adapter_server.py` | RunActionRequest | 鍔ㄤ綔鎵ц璇锋眰 |
| `python_adapter_server.py` | CreateSessionRequest | 浼氳瘽鍒涘缓 |
| `python_adapter_server.py` | CreateJobRequest | 浠诲姟鍒涘缓 |
| `python_adapter_server.py` | JobPayload | 浠诲姟鍝嶅簲 |
| `python_adapter_server.py` | PipelineRequest | 绠￠亾鎵ц璇锋眰 |
| `python_adapter_server.py` | MemoryStatusPayload | 璁板繂搴撶姸鎬佽瘖鏂?|
| `recovery_autopilot_router.py` | AutopilotStatusResponse | 鑷姩椹鹃┒鐘舵€?|
| `recovery_autopilot_router.py` | AutopilotEnableRequest | 鍚敤/绛栫暐璇锋眰 |
| `recovery_autopilot_router.py` | EventLogEntry | 瑙勮寖浜嬩欢 |
| `skills/models.py` | SkillDescriptor | 鎶€鑳戒笉鍙彉鍏冩暟鎹?|
| `skills/models.py` | SkillKind | 鎶€鑳藉垎绫绘灇涓?|
| `skills/models.py` | SkillCompatibility | 浼犵粺鍔ㄤ綔鍏煎鏄犲皠 |
| `skills/models.py` | ScriptPolicy | 鑴氭湰瀹夊叏鏀跨瓥 |

**妯″瀷璁捐妯″紡**:
- 鉁?浣跨敤 `Field(default_factory=...)` 澶勭悊闆嗗悎绫诲瀷
- 鉁?浣跨敤 dataclass 鍖呰鍣ㄧ敤浜庝笉鍙彉鎬э紙`@dataclass(frozen=True)`锛?
- 鉁?宓屽妯″瀷杩涜澶嶆潅璐熻浇缁撴瀯

---

## 2. 鏁版嵁搴撲娇鐢ㄧ幇鐘?

### 2.1 SQLite 鏁版嵁搴撴枃浠舵竻鍗?

**涓や釜涓昏鏁版嵁搴撴枃浠?*锛堝伐浣滃尯鏍圭洰褰曪級:

| 鏂囦欢 | 鐢ㄩ€?| 鍒濆鍖栦綅缃?| 琛ㄦ暟 |
|------|------|----------|------|
| `harness_state.db` | 瑙勮寖浜嬩欢瀛樺偍 + 闃舵 A 鐘舵€?| `canonical_event_store.py` | N+ (浜嬩欢琛?+ 澶栭敭) |
| `harness_facts.db` | 鏃舵€佷簨瀹炲瓨鍌紙绗?D 闃舵锛?| `memory_fact_store.py` | N+ (浜嬪疄琛?+ 绱㈠紩) |

### 2.2 CanonicalEventStore锛堜簨浠跺瓨鍌級

**鏂囦欢**: [canonical_event_store.py](canonical_event_store.py)

**DB 琛ㄧ粨鏋?*:
```sql
canonical_events (
  id INT AUTO_INCREMENT PRIMARY KEY,
  event_id TEXT UNIQUE NOT NULL,
  correlation_id TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  session_id TEXT,
  job_id TEXT,
  user_id TEXT,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload JSON NOT NULL,
  actor_id TEXT,
  actor_type TEXT DEFAULT 'system',
  severity TEXT DEFAULT 'info',
  previous_state JSON,
  new_state JSON,
  error_code TEXT,
  error_message TEXT,
  source TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  
  FOREIGN KEY(session_id) REFERENCES sessions,
  FOREIGN KEY(job_id) REFERENCES jobs
)
```

**绱㈠紩绛栫暐**:
- `idx_canonical_job_id` 鈫?鎸?job_id 鏌ヨ
- `idx_canonical_session_id` 鈫?鎸?session_id 鏌ヨ
- `idx_canonical_event_type` 鈫?鎸変簨浠剁被鍨嬭繃婊?
- `idx_canonical_timestamp` 鈫?鏃堕棿杞存煡璇?
- `idx_canonical_aggregate` 鈫?鎸夎仛鍚堜綋鏌ヨ
- `idx_canonical_correlation` 鈫?鍏宠仈 ID 杩借釜

**璁块棶妯″紡**:
- 杩藉姞浜嬩欢: `append_event(event: CanonicalEvent)`
- 鏌ヨ浜嬩欢: `find_events_by_job(job_id)`, `find_by_timestamp_range(from, to)`
- 瀵煎嚭浜嬩欢: `export_as_csv()`, `export_as_jsonl()`

### 2.3 MemoryFactStore锛堜簨瀹炲瓨鍌級

**鏂囦欢**: [memory_fact_store.py](memory_fact_store.py)

**鏍稿績鏁版嵁妯″瀷**:
```python
@dataclass(frozen=True)
class TemporalFact:
    fact_id: str                        # 鍞竴鏍囪瘑
    namespace: str                      # 鍩?(execution, skills, resources, approvals, pipeline)
    subject: str                        # 瀹炰綋涓讳綋 (job_id, skill_name)
    predicate: str                      # 灞炴€у悕 (status, enabled, decision)
    object: str                         # 灞炴€у€?(JSON 瀛楃涓?
    object_type: str                    # 绫诲瀷鎻愮ず (string, int, float, bool, json)
    valid_from: datetime                # 鏈夋晥鏈熷紑濮?(鍖呭惈)
    valid_to: datetime | None           # 鏈夋晥鏈熺粨鏉?(鎺掗櫎)锛孨one = 褰撳墠鏈夋晥
    source_event_id: str                # 鍒涘缓姝や簨瀹炵殑瑙勮寖浜嬩欢 ID
    created_at: datetime                # 浜嬪疄鍒涘缓鏃跺埢
```

**浜嬪疄鎻愬彇瑙勫垯浣撶郴**:
```python
FactExtractionRule (ABC)
  鈹溾攢鈹€ ExecutionFactRule          # 鎻愬彇浠诲姟鐘舵€佷簨瀹?
  鈹溾攢鈹€ SkillActivationRule        # 鎻愬彇鎶€鑳藉惎鐢ㄤ簨瀹?
  鈹溾攢鈹€ ResourceAllocationRule     # 鎻愬彇璧勬簮鍒嗛厤浜嬪疄
  鈹斺攢鈹€ ApprovalDecisionRule       # 鎻愬彇瀹℃壒鍐冲畾浜嬪疄
```

**鍏抽敭鍔熻兘**:
- `is_current()` - 妫€鏌ヤ簨瀹炲綋鍓嶆槸鍚︽湁鏁?
- `was_valid_at(timestamp)` - 妫€鏌ヤ簨瀹炲湪鐗瑰畾鏃跺埢鏄惁鏈夋晥
- 鏃舵€佹煡璇? 褰撳墠浜嬪疄銆佸巻鍙蹭簨瀹炪€佹椂闂磋酱浜嬪疄

### 2.4 鏁版嵁搴撳垵濮嬪寲涓庤幏鍙?

**鏂囦欢**: [recovery_store_provider.py](recovery_store_provider.py)锛堟帹鏂級

```python
def get_event_store() -> CanonicalEventStore:
    # 鍏ㄥ眬鍗曚緥锛宒b_path = "harness_canonical_events.db"
    # or 鏄犲皠鍒?harness_state.db锛堝疄闄呬娇鐢級

def get_fact_store() -> MemoryFactStore:
    # 鍏ㄥ眬鍗曚緥锛宒b_path = "harness_facts.db"

def get_recovery_console() -> RecoveryConsole:
    # 渚濊禆涓や釜鏁版嵁搴撳疄渚?
```

---

## 3. 瑙勮寖 Pydantic 妯″瀷鍒嗗竷鍒嗘瀽

### 3.1 妯″瀷缁勭粐鐜扮姸

**褰撳墠鐘舵€?*: 妯″瀷**鍒嗘暎瀹氫箟**浜庡涓枃浠讹紝鏈泦涓鐞?

**闂**:
- `python_adapter_server.py` 涓畾涔変簡 20+ 涓?Pydantic 妯″瀷锛堢 200-450 琛岋級
- `recovery_autopilot_router.py` 涓嫭绔嬪畾涔変簡 6 涓ā鍨?
- `skills/models.py` 涓畾涔変簡 skill 鐗瑰畾妯″瀷锛坉ataclass 鏂瑰紡锛?
- 鏃犱笓鐢?`models/` 鐩綍鎴栫粺涓€鐨?schema 妯″潡

### 3.2 寤鸿鐨勯噸缁勭粨鏋?

**鍙綔鍦ㄨ縼绉荤殑鐩爣缁撴瀯**:
```
models/
  鈹溾攢鈹€ __init__.py
  鈹溾攢鈹€ common.py
  鈹?  鈹斺攢鈹€ TaskState, MemoryStatusPayload
  鈹溾攢鈹€ writing.py
  鈹?  鈹斺攢鈹€ CreateSessionRequest, CreateJobRequest, JobPayload, SessionPayload
  鈹溾攢鈹€ pipeline.py
  鈹?  鈹斺攢鈹€ PipelineRequest, PipelineTaskSubmitResponse, PipelineTaskStatusResponse
  鈹溾攢鈹€ recovery.py
  鈹?  鈹斺攢鈹€ AutopilotStatusResponse, EventLogEntry, PolicyInfo
  鈹溾攢鈹€ skills.py
  鈹?  鈹斺攢鈹€ SkillDescriptorPayload, SkillPackPayload, CapabilityPayload
  鈹斺攢鈹€ artifacts.py
      鈹斺攢鈹€ ArtifactPayload, SkillRunResultPayload
```

### 3.3 鍏抽敭 Enum 鍜屽熀纭€绫诲瀷

鍦?`python_adapter_server.py` 涓畾涔?
```python
TaskState (str, Enum):
  - queued
  - running
  - succeeded
  - failed
```

鍦?`skills/models.py` 涓畾涔?
```python
SkillKind(str, Enum):
  - TRANSFORM, VALIDATOR, WORKFLOW, DOMAIN, STYLE

SkillSource(str, Enum):
  - BUILTIN, IMPORTED, EXPERIMENTAL

SkillTrustLevel(str, Enum):
  - TRUSTED, LIMITED, UNTRUSTED

UIVisibility(str, Enum):
  - SIMPLE_PROMPT, SKILL_ASSISTED, BOTH, HIDDEN
```

---

## 4. 07_analysis_scoring 妯″潡娣卞害鍒嗘瀽

### 4.1 妯″潡姒傚喌

**鏂囦欢**: [07_analysis_scoring_improved_v9.py](07_analysis_scoring_improved_v9.py)

**鐢ㄩ€?*: 閽堝**瀛︽湳鏂囩尞鐗囨**鐨勮瘉鎹川閲忚瘎鍒嗙郴缁?
- 杈撳叆: 浠?PDF 鎻愬彇鐨勬枃鏈钀姐€佸浘琛ㄣ€佽〃鏍?
- 杈撳嚭: 璇佹嵁寰楀垎銆佺被鍨嬪垎绫汇€佽竟鐣岀‘瀹?

**浠ｇ爜琛屾暟**: ~1000 琛岋紙姝ｅ垯琛ㄨ揪寮忋€佸惎鍙戝紡璇勫垎銆佸垎绫昏鍒欙級

### 4.2 鍏抽敭鏁版嵁缁撴瀯

**杈撳叆/杈撳嚭鏁版嵁**:
```python
# 杈撳叆
Goal: str                    # 鐮旂┒鐩爣鎴栨煡璇?(e.g., "鐑緭鍏ュ寰缁勭粐鐨勫奖鍝?)
BoundEvidenceContract:       # 瑙勮寖浜嬪疄鍜屽叧鑱斿绾?
  鈹溾攢鈹€ chunks: list           # 鏂囨湰鐗囨 (chunk_id, page, text, section_title)
  鈹溾攢鈹€ figures: list          # 鍥捐〃 (figure_id, page, caption, bbox)
  鈹斺攢鈹€ tables: list           # 琛ㄦ牸 (table_id, page, caption)

# 杈撳嚭  
ScoredClaim: dict
  鈹溾攢鈹€ claim_id: str
  鈹溾攢鈹€ raw_text: str
  鈹溾攢鈹€ goal_relevance_score: float (0-1)
  鈹溾攢鈹€ evidence_boundary: str (result|explanation|inference|background_reference|unclear)
  鈹溾攢鈹€ point_type: str (result|mechanism|method|background|summary|meta|discussion)
  鈹溾攢鈹€ links: {figures: [...], tables: [...], citations: [...]}
  鈹斺攢鈹€ metadata: {page, section_title, ...}
```

### 4.3 璇勫垎绠楁硶鏋舵瀯

**鏍稿績璇勫垎鍑芥暟** (绗?700-850 琛屼吉浠ｇ爜):

```python
def score_claim(claim_text, goal_terms, phrase_terms, goal_profile):
    """缁煎悎璇勫垎 = 鐩爣鐩稿叧鎬?+ 缁撴灉璇佹嵁 + 鏈哄埗璇佹嵁 - 鍏冩暟鎹儵缃?""
    
    # 1. 鍩虹鍒嗘暟
    goal_raw, hits = token_score(claim_text, goal_terms)
    
    # 2. 鍔犲垎椤?
    result_hit = RESULT_CUES.search(claim_text)         # +0.8-1.2
    mech_hit = MECH_CUES.search(claim_text)             # +0.9-1.4
    current_bonus = CURRENT_WORK_CUES.search(claim_text) # +0.9锛堟湰宸ヤ綔锛?
    direct_bonus = fmt_and_num_bonus(claim_text)        # +0.8锛堝浘琛?鏁板€硷級
    process_bonus = process_focus_bonus(...)            # +0.08
    
    # 3. 鎵ｅ垎椤?
    meta_penalty = sentence_meta_penalty(claim_text)    # -0.8 ~ -2.0
    method_pen = method_over_emphasis(...)              # -1.0
    literature_pen = literature_background_coverage()   # -1.4
    formula_pen = formula_exposition_penalty()          # -1.5
    background_penalty = -0.34 * background_load
    
    # 4. 绫诲瀷鍒嗙被鎯╃綒
    if point_type == 'background':
        penalty -= 0.2
    
    # 鏈€缁堝緱鍒?
    final_score = (goal_raw + result_hit + mech_hit + 
                   current_bonus + direct_bonus + process_bonus
                   - meta_penalty - method_pen - literature_pen 
                   - formula_pen - background_penalty)
    return max(0.0, final_score)
```

**鐩爣鏄犲皠浣撶郴** (GOAL_MAP):
```python
{
    '宸ヨ壓鍙傛暟': ['parameter', 'power', 'speed', 'frequency', 'heat input', ...],
    '鐔旀睜娴佸姩': ['molten pool', 'flow', 'convection', 'dynamics', ...],
    '姘紶杈?: ['nitrogen', 'nitriding', 'nitride', ...],
    '缁勭粐': ['microstructure', 'grain', 'phase', 'precipitate', ...],
    '搴斿姏': ['stress', 'residual stress', ...],
    '鎬ц兘': ['hardness', 'wear', 'corrosion', 'tensile', ...],
    '瑁傜汗': ['crack', 'cracks', 'cracking', ...],
    '鍥惧儚': ['image', 'cnn', 'deep learning', ...],
    # ... 13 涓洰鏍囩被鍒?
}
```

### 4.4 鍒嗙被瑙勫垯锛堟鍒欒〃杈惧紡搴擄級

**璁捐妯″紡**: 瑙勫垯绋嬪簭鍖?+ 鍚彂寮忓姞鏉?

| 瑙勫垯 | 鍙橀噺鍚?| 鍖归厤鍐呭 | 璇勫垎褰卞搷 |
|------|--------|---------|---------|
| 鏂规硶绾跨储 | `METHOD_CUES` | method, procedure, measured | 纭鏂规硶閮ㄥ垎 |
| 缁撴灉绾跨储 | `RESULT_CUES` | increase, decrease, achieve, hardness | 缁撴灉鏍囪 |
| 鏈哄埗绾跨储 | `MECH_CUES` | because, due to, lead to, mechanism | 瑙ｉ噴鎸囩ず |
| 鑳屾櫙绾跨储 | `BACKGROUND_CUES` | challenge, however, review | 鑳屾櫙涓婁笅鏂?|
| 鍏冩暟鎹嚎绱?| `META_CUES` | fig., table, shown in | 鍏冩暟鎹儵缃?|
| 纭欢绾跨储 | `HARDWARE_CUES` | GPU, CPU, MATLAB, software | 鎶€鏈儗鏅?|
| 鍏紡灞曠ず | `FORMULA_EXPOSITION_CUES` | rosenthal, equation, where A is | 鍏紡璇存槑 |

### 4.5 I/O 瀵嗛泦鎿嶄綔璇嗗埆

**鏂囦欢 I/O**:
- 鍗曚竴杈撳叆: `Path(args.input_json).read_text()` (JSON 鍔犺浇)
- 鍒嗛樁娈佃緭鍑? `write_jsonl()` 閫愯鍐欏嚭缁撴灉

**璁＄畻鐗规€?*:
- **姝ｅ垯琛ㄨ揪寮忓瘑闆?*: 姣忎釜鍙ュ瓙 ~20-30 娆℃鍒欏尮閰?
- **鏂囨湰澶勭悊**:
  - 鍒嗗彞: `split_sentences()` 浣跨敤姝ｅ垯琛ㄨ揪寮?
  - 鍒嗚瘝: `en_tokens()`, `cn_tokens()` 澶氭璋冪敤
  - Jaccard 鐩镐技搴﹁绠? O(n log n)

**褰撳墠骞惰鎬?*:
- 鉁?鏃犲杩涚▼澶勭悊
- 鉁?鏃犲紓姝?I/O
- 鉁?鏃?ThreadPool(Builder 妯″紡)
- 鉁?鍗曠嚎绋嬮『搴忓鐞嗘墍鏈夊０鏄?

**鎵╁睍鐐?*:
```python
# 鍙兘鐨勫苟琛屽寲
- 浣跨敤 multiprocessing.Pool 杩涜澹版槑璇勫垎鎵瑰鐞?
- 浣跨敤 asyncio 杩涜澶栭儴 API 璋冪敤锛堝鏋滈渶瑕侊級
- 浣跨敤 concurrent.futures 杩涜 I/O 鍔犻€?
```

---

## 5. 鐜版湁閰嶇疆绠＄悊

### 5.1 閰嶇疆鏂囦欢浣嶇疆涓庡唴瀹?

**涓昏閰嶇疆鏂囦欢**: [config/rag_integration_config.yaml](config/rag_integration_config.yaml)

**閰嶇疆缁勭粐**:
```yaml
ragflow:
  enabled: false
  base_url: "https://localhost:9380"
  dataset_ids: []
  verify_ssl: true

graphrag:
  enabled: false
  index_path: "C:/Users/xiao/Desktop/wenxianku"

autorag:
  enabled: true
  data_path: "C:/Users/xiao/Desktop/wenxianku"
  output_dir: "./autorag_out"

embedding:
  provider: "siliconflow"
  api_key_env: "SILICONFLOW_API_KEY"
  model: "BAAI/bge-m3"
  batch_size: 50

workflow:
  llm_api_key_env: "ARK_API_KEY"
  llm_model: "ep-your-ark-endpoint"

mempalace:
  enabled: true
  vendor_repo_path: "./github/mempalace-3.0.0"
  palace_path: "./output/mempalace/palace"
  search_limit: 3
```

### 5.2 浠ｇ爜涓殑纭紪鐮佸弬鏁?

**07_analysis_scoring**锛堟潈閲嶅拰闃堝€硷級:
```python
# 姝ｅ垯琛ㄨ揪寮忓畾涔夛紙琛?2-25锛?
# 鍋滅敤璇嶉泦鍚堬紙琛?29-31锛?
STOPWORDS = {
    'the', 'and', 'for', 'with', 'that', 'this', ... # 120+ 璇嶆眹
}

# 鐩爣鏄犲皠锛堣 33-48锛?
GOAL_MAP = { # 13 涓绉戠被鍒紝姣忎釜 3-8 涓叧閿瘝

# 璇勫垎鏉冮噸锛堥殣鍚級
- 缁撴灉鍛戒腑濂栧姳: +0.8 ~ +1.2
- 鏈哄埗鍛戒腑濂栧姳: +0.9 ~ +1.4
- 褰撳墠浣滃搧濂栧姳: +0.9
- 鍏冩暟鎹儵缃? -0.8 ~ -2.0
- 鑳屾櫙鎯╃綒: -0.34 * background_load
```

**MemPalace 閰嶇疆**锛堢 30-45 琛岋級:
```python
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "rag_integration_config.yaml"
DEFAULT_VENDOR_REPO_PATH = PROJECT_ROOT / "github" / "mempalace-3.0.0"
DEFAULT_PALACE_PATH = PROJECT_ROOT / "output" / "mempalace" / "palace"
DEFAULT_COLLECTION_NAME = "mempalace_drawers"
DEFAULT_WING = "wing_modular_pipeline"
DEFAULT_ROOM = "runtime-jobs"
DEFAULT_SEARCH_LIMIT = 3
DEFAULT_MAX_CONTENT_CHARS = 4000
```

### 5.3 鍙傛暟绠＄悊鐜扮姸璇勪及

| 鏂归潰 | 鐘舵€?| 浣嶇疆 |
|------|------|------|
| 澶栭儴鍖栭厤缃?| 鉁?閮ㄥ垎 | `config/rag_integration_config.yaml` |
| YAML 瑙ｆ瀽 | 鉁?| `layers/m_layer_mempalace_memory.py` (yaml 瀵煎叆) |
| 鐜鍙橀噺娉ㄥ叆 | 鉁?| RAG API 瀵嗛挜 (SILICONFLOW_API_KEY, ARK_API_KEY) |
| 杩愯鏃跺垏鎹?| 鉁?| 鏃犵儹閰嶇疆閲嶅姞杞?|
| 绠楁硶鏉冮噸 | 鉁?纭紪鐮?| `07_analysis_scoring_improved_v9.py` |
| 闃堝€煎弬鏁?| 鉁?纭紪鐮?| 鍚勬ā鍧楀垎鏁ｅ畾涔?|
| 閰嶇疆楠岃瘉 | 鉁?閮ㄥ垎 | Pydantic `MempalaceSettings` 鏁版嵁绫?|

### 5.4 寤鸿鐨勯厤缃閮ㄥ寲

**鏂板缓鏂囦欢** `config/algorithm_params.yaml`:
```yaml
scoring:
  weights:
    result_hit_reward: 1.0
    mechanism_hit_reward: 1.2
    current_work_bonus: 0.9
    process_bonus: 0.08
    meta_penalty: -1.5
    method_over_emphasis_penalty: -1.0
    literature_background_penalty: -1.4
    formula_exposition_penalty: -1.5
    background_penalty_factor: -0.34
  
  thresholds:
    confidence_min: 0.3
    evidence_relevance_min: 0.5
    
  stopwords: ./config/stopwords.txt
  goal_mappings: ./config/goal_mappings.yaml
```

---

## 6. 閾捐矾杩借釜鐜扮姸

### 6.1 HTTP 涓棿浠跺疄鐜?

**鏂囦欢**: [python_adapter_server.py](python_adapter_server.py) (绗?110-189 琛?

**涓棿浠跺姛鑳?*:

```python
@app.middleware("http")
async def recovery_observability_middleware(request: Request, call_next):
    """Record real HTTP metrics for all recovery endpoints."""
    
    # 1. 璇锋眰鍏冩暟鎹彁鍙?
    path = request.url.path
    method = request.method
    job_id = request.query_params.get("job_id")
    session_id = request.query_params.get("session_id")
    
    # 2. 璺敱妯″紡瑙勮寖鍖?(鐢ㄤ簬鎸囨爣鍒嗙粍)
    route_pattern = normalize_route(path)  # e.g., "/recovery/autopilot/enable"
    
    # 3. 璺ㄥ害鍒涘缓
    with telemetry.start_span("recovery.http.request", {
        "http.method": method,
        "http.route": route_pattern,
        "http.job_id": job_id,
        "http.session_id": session_id,
    }) as span:
        
        # 4. 璇锋眰鎵ц锛堣鏃讹級
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        
        # 5. 鎸囨爣璁板綍
        metrics.record_http_request(route_pattern, method, status_code, duration_ms)
        metrics.record_recovery_outcome(success=status_code < 400)
        
        # 6. 杩借釜灞炴€ц缃?
        span.set_attribute("http.status_code", response.status_code)
        span.set_attribute("http.duration_ms", duration_ms)
        
        # 7. 鍝嶅簲澶存敞鍏?
        response.headers["X-Recovery-Trace-Id"] = span.trace_id
        response.headers["X-Recovery-Span-Id"] = span.span_id
        response.headers["X-Recovery-Duration-Ms"] = duration_ms
        
        return response
```

**涓棿浠惰鐩栬寖鍥?*:
- 鍙鐞?`/recovery/` 璺敱锛堝叾浠栬矾鐢卞垯閫忚繃閫氳繃锛?
- 璁＄畻寤惰繜銆佺姸鎬佺爜銆佽姹傚ぇ灏忥紙鍙€夛級

### 6.2 Recovery Telemetry 妯″潡

**鏂囦欢**: [recovery_telemetry.py](recovery_telemetry.py)

**鏍稿績绫?*:

```python
@dataclass
class RecoveryTraceSpan:
    """Context manager that records a recovery trace span."""
    
    name: str                    # 璺ㄥ害鍚嶇О (e.g., "recovery.http.request")
    trace_id: str                # 杩借釜 ID (鑷姩鐢熸垚 UUID)
    span_id: str                 # 璺ㄥ害 ID (鑷姩鐢熸垚 16 瀛楄妭鍗佸叚杩涘埗)
    attributes: dict             # 闄勫姞灞炴€?
    duration_ms: float           # 璁＄畻鐨勬寔缁椂闂?
    error: str | None            # 寮傚父淇℃伅
    
    def __enter__(self):         # 璁板綍璺ㄥ害寮€濮?
    def __exit__(self, ...):     # 璁板綍璺ㄥ害缁撴潫 + 璁＄畻鎸佺画鏃堕棿
    def set_attribute(key, value)  # 鍔ㄦ€侀檮鍔犲睘鎬?
    def record_exception(exc)      # 璁板綍寮傚父鑰屼笉鍚炲捊

class RecoveryTelemetry:
    """Tracing facade for recovery operations."""
    
    def __init__(self, service_name="modular.recovery", enable_opentelemetry=True):
        self._otel_tracer = None
        if enable_opentelemetry and OTEL_AVAILABLE:
            self._otel_tracer = otel_trace.get_tracer(service_name)
    
    def start_span(name: str, attributes: dict | None) -> RecoveryTraceSpan:
        """Create context manager for tracing."""
    
    def trace(name: str, **attributes) -> RecoveryTraceSpan:
        """Convenience alias."""

_TELEMETRY_STATE = {"telemetry": None}

def get_recovery_telemetry() -> RecoveryTelemetry:
    """Singleton getter."""
```

**鏃ュ織闆嗘垚** (绗?41-48 琛?:
```python
logger.info(
    "trace.start name=%s trace_id=%s span_id=%s attributes=%s",
    self.name, self.trace_id, self.span_id, self.attributes,
)

logger.info(
    "trace.end name=%s trace_id=%s span_id=%s status=%s duration_ms=%.3f",
    self.name, self.trace_id, self.span_id, telemetry_status, self.duration_ms,
)
```

### 6.3 Recovery Metrics Exporter

**鏂囦欢**: [recovery_metrics_exporter.py](recovery_metrics_exporter.py)

**搴﹂噺闆嗗悎** (RecoveryMetricsSnapshot):
```python
@dataclass(frozen=True)
class RecoveryMetricsSnapshot:
    snapshot_at: str                    # ISO 鏃堕棿鎴?
    
    # HTTP 鎸囨爣
    http_requests_total: int            # 鎬昏姹傛暟
    http_request_duration_ms_sum: float # 鎬绘寔缁椂闂达紙姣锛?
    http_request_counts: dict[str, int] # 鎸夎矾鐢卞垎瑙ｇ殑璇锋眰璁℃暟
    
    # 寤鸿鐢熸垚鎸囨爣
    recommendation_generations_total: int
    recommendation_success_total: int
    recommendation_confidence_sum: float
    recommendation_confidence_avg: float  # 灞炴€?
    
    # 鎭㈠缁撴灉
    recovery_success_total: int
    recovery_failure_total: int
    
    # 杩借釜
    trace_spans_total: int
    trace_errors_total: int
    
    # 璇佹嵁澶勭悊
    total_evidence_considered: int
    evidence_totals: dict[str, int]     # 鎸夌被鍨嬪垎瑙?
    
    # 鎿嶄綔鍛樹氦浜?
    operator_overrides_total: int
    operator_acceptances_total: int
    operator_rejections_total: int
```

**Prometheus 瀵煎嚭** (鎺ㄦ柇):
```python
def to_prometheus_text() -> str:
    """Export metrics in Prometheus text format."""
    # 杈撳嚭鏍煎紡:
    # recovery_http_requests_total{route="/recovery/autopilot/status"} 42
    # recovery_recommendations_confidence_avg 0.87
    # ...
```

### 6.4 OpenTelemetry 闆嗘垚鐜扮姸

**褰撳墠瀹炵幇**:
```python
# 鍙€変緷璧?
try:
    from opentelemetry import trace as otel_trace
except ImportError:
    otel_trace = None  # 浼橀泤闄嶇骇鍒扮粨鏋勫寲鏃ュ織
```

**闆嗘垚鐐?*:
- 濡傛灉 OpenTelemetry 鍙敤锛岃法搴﹀睘鎬ц嚜鍔ㄥ鍑哄埌 OTEL 杩借釜鍣?
- `RecoveryTraceSpan.__enter__` 妫€鏌?`self.telemetry._otel_tracer`:
  ```python
  if self.telemetry._otel_tracer is not None:
      self._otel_scope = self.telemetry._otel_tracer.start_as_current_span(self.name)
      self._otel_span = self._otel_scope.__enter__()
      for key, value in self.attributes.items():
          self._otel_span.set_attribute(key, value)
  ```

**缂哄け閮ㄥ垎**:
- 鉁?鏃?OTEL Metrics API 闆嗘垚锛堜粎浣跨敤鍐呭瓨搴﹂噺鏀堕泦鍣級
- 鉁?鏃?baggage锛堣法鏈嶅姟涓婁笅鏂囦紶鎾級
- 鉁?鏃?OTEL Logs API 闆嗘垚
- 鉁?鍩虹 OTEL Trace 鎻掓々浼氳嚜鍔ㄥ伐浣滐紙濡傛灉鍙戠幇渚濊禆锛?

---

## 7. 涓昏鍔熻兘妯″潡鍦板浘

### 7.1 椤剁骇妯″潡娉ㄥ唽琛?

| 妯″潡 | 绫诲瀷 | 涓绘枃浠?| 鐩殑 |
|------|------|--------|------|
| **鎭㈠鎺у埗骞抽潰** | 鏍稿績 | `recovery_autopilot_control_plane.py` | 鑷姩椹鹃┒绛栫暐绠＄悊 |
| **鎭㈠鎵ц寮曟搸** | 鎵ц | `recovery_execution_engine.py` | 鎺ㄨ崘鎵ц鍗忚皟 |
| **鎭㈠寤鸿寮曟搸** | 浠撳簱 | `recovery_recommendation_engine.py` | 鎭㈠寤鸿鐢熸垚 |
| **瑙勮寖浜嬩欢** | 鏁版嵁 | `harness_canonical_events.py` | 浜嬩欢妯″瀷瀹氫箟 |
| **浜嬩欢瀛樺偍** | 瀛樺偍 | `canonical_event_store.py` | SQLite 浜嬩欢鎸佷箙鎬?|
| **浜嬪疄瀛樺偍** | 瀛樺偍 | `memory_fact_store.py` | 鏃舵€佷簨瀹炲簱 |
| **鎭㈠鎺у埗鍙?* | UI | `recovery_console.py` | 妫€鏌ョ偣鍜屾仮澶?UI |
| **宸ヤ綔娴?* | 涓氬姟閫昏緫 | `recovery_workflows.py` | 鎭㈠涓氬姟娴佺▼ |
| **MemPalace 閫傞厤鍣?* | 闆嗘垚 | `layers/m_layer_mempalace_memory.py` | 闀挎湡椤圭洰璁板繂 |
| **鎶€鑳芥湇鍔?* | 鎵ц | `skills/service.py` | 鎶€鑳芥敞鍐屽簱鍜屾墽琛?|
| **鍐欎綔杩愭椂** | 鎵ц | `writing_runtime.py` | 浼氳瘽鍜屼换鍔＄鐞?|
| **鍐欎綔璧勬簮** | 瀛樺偍 | `writing_resources.py` | 椤圭洰銆佽崏绋垮拰宸ヤ欢瀛樺偍 |
| **绠￠亾** | 鎵ц | `00_Integrated_Pipeline_.py` `01_瀹屾暣鎻愬彇鑴氭湰.py` | 瀛︽湳鏂囩尞澶勭悊绠￠亾 |

### 7.2 Layers 鐩綍锛堜腑闂翠欢鍜岄€傞厤鍣級

| 灞傜骇 | 鏂囦欢 | 鐢ㄩ€?|
|------|------|------|
| A | `a_layer_agent_coordinator.py` | 鏅鸿兘浣撳崗璋?|
| E | `e_layer_multimodal.py` | 澶氭ā鎬佸鐞?|
| E | `e_ragflow_retrieval_adapter.py` | RAGFlow 妫€绱㈤泦鎴?|
| G | `g_layer_academic_generator.py` | 瀛︽湳鏂囨湰鐢熸垚 |
| G | `g_synthesis_graphrag_bridge.py` | GraphRAG 绀惧尯鍥捐氨 |
| K | `k_layer_index_builder.py` | 绱㈠紩鏋勫缓 |
| M | `m_layer_mempalace_memory.py` | MemPalace 闀挎湡璁板繂 |
| P | `p_layer_presentation_word.py` | Word 婕旂ず灞?|
| R | `r_layer_hybrid_retriever.py` | 娣峰悎妫€绱紙璇嶆眹 + 璇箟锛?|
| V | `v_layer_volume_bundle.py` | 鍗风骇鎹嗙粦 |
| V | `v_eval_autorag_runner.py` | AutoRAG 璇勬祴杩愯鍣?|
| W | `w_layer_cross_paper_analysis.py` | 璺ㄨ鏂囧垎鏋?|
| 杈呭姪 | `focus_registry.py` | 鐒︾偣娉ㄥ唽琛紙鍏抽敭姒傚康杩借釜锛?|
| 杈呭姪 | `focus_extractor.py` | 鐒︾偣鎻愬彇鍣?|
| 杈呭姪 | `semantic_router.py` | 璇箟璺敱锛堟煡璇㈠垎绫伙級 |

### 7.3 鍓嶇闆嗘垚锛堝彲閫夛級

**鐩綍**: `frontend/`锛圴ue.js 鎴栫被浼煎墠绔簲鐢級

**鍏抽敭妯″瀷鏄犲皠**:
- `WritingActionPayload` 鈫?UI 鍔ㄤ綔/鎶€鑳芥寜閽?
- `SkillDescriptorPayload` 鈫?鍔ㄤ綔鍏冩暟鎹紙鎻忚堪銆佺被鍒€佸吋瀹规€э級
- `SkillPackPayload` 鈫?楂樼骇 UI 鍒嗙粍锛堝姩浣滃寘锛?

---

## 8. 闆嗘垚鐐逛笌鐥涚偣鍒嗘瀽

### 8.1 鏋舵瀯闆嗘垚鐐?

| 闆嗘垚鐐?| 杩炴帴鏂瑰紡 | 椋庨櫓 |
|--------|---------|------|
| **FastAPI 鈫?鎭㈠鎺у埗骞抽潰** | Direct import (`recovery_autopilot_cli`) | 纭緷璧栵紝鍗曠偣鏁呴殰 |
| **HTTP 涓棿浠?鈫?閬ユ祴** | Singleton 妯″紡 (`get_recovery_telemetry()`) | 鏃犻殧绂伙紝绾跨▼骞跺彂闂 |
| **浜嬩欢瀛樺偍 鈫?浜嬪疄瀛樺偍** | 澶栭敭鍏宠仈 (event_id 鈫?fact.source_event_id) | 鏁版嵁涓€鑷存€ч渶瑕佷簨鍔?|
| **浼氳瘽 鈫?浠诲姟 鈫?宸ヤ欢** | 寮曠敤閾?(session_id 鈫?job_id 鈫?artifact_id) | 绾ц仈鍒犻櫎闇€瑕佸皬蹇冨鐞?|
| **鎶€鑳?鈫?鎶€鑳借繍鏃?* | 娉ㄥ唽琛ㄦ煡璇?+ 鍔ㄦ€佹墽琛?| 瀹夊叏娌欑鍖栦笉瓒?|
| **MemPalace 閫傞厤鍣?鈫?璁板繂鏌ヨ** | 寮傛缂栧叆+鎻愪緵绋嬪簭妯″紡 | 缃戠粶寤惰繜銆佺紦瀛樺け鏁?|
| **璇勫垎寮曟搸 鈫?鏁版嵁搴?* | 鏃犵洿鎺ヤ緷璧栵紙绾绠楋級 | 缁撴灉鎸佷箙鍖栭渶瑕佹墜鍔?|

### 8.2 宸茶瘑鍒殑鐥涚偣

#### 闂 1: 妯″瀷瀹氫箟鍒嗘暎
- **鐥囩姸**: Pydantic 妯″瀷鍦?4+ 涓枃浠朵腑瀹氫箟
- **褰卞搷**: 闅句互缁存姢銆佸彂鐜板洶闅俱€侀噸澶嶅畾涔夐闄?
- **寤鸿**: 鍒涘缓 `models/` 鍖咃紝闆嗕腑瀹氫箟鎵€鏈?API Schema

#### 闂 2: 閰嶇疆纭紪鐮?
- **鐥囩姸**: 璇勫垎鏉冮噸銆侀槇鍊笺€佸仠鐢ㄨ瘝鍦ㄦ簮浠ｇ爜涓?
- **褰卞搷**: 淇敼鍙傛暟闇€瑕佷唬鐮佸彉鏇?+ 閲嶆柊閮ㄧ讲
- **寤鸿**: 灏?`07_analysis_scoring` 鏉冮噸杩佺Щ鍒?`config/algorithm_params.yaml`

#### 闂 3: 骞惰澶勭悊缂哄け
- **鐥囩姸**: `07_analysis_scoring` 鍗曠嚎绋嬮『搴忓鐞嗘墍鏈夊０鏄?
- **褰卞搷**: 澶勭悊澶ф壒閲忚鏂囨枃妗ｆ椂閫熷害寰堟參
- **寤鸿**: 浣跨敤 `multiprocessing.Pool` 鎴?`concurrent.futures` 骞惰鍖栬瘎鍒?

#### 闂 4: 鏃犲叡浜?UTC 宸ュ叿
- **鐥囩姸**: `_iso_utc_now()` 鍦ㄥ涓枃浠朵腑閲嶅瀹炵幇
- **褰卞搷**: 鏃堕棿鎴虫牸寮忎笉涓€鑷淬€佺淮鎶よ礋鎷?
- **寤鸿**: 浣跨敤 `datetime_utils.utc_now_iso_z()`锛堝凡闆嗕腑瀹炵幇锛?

#### 闂 5: OpenTelemetry 閮ㄥ垎闆嗘垚
- **鐥囩姸**: 浠呮湁 Trace API锛岀己灏?Metrics 鍜?Logs API
- **褰卞搷**: 搴﹂噺瀵煎嚭鍥伴毦銆佹棩蹇楄仛鍚堜笉瀹屾暣
- **寤鸿**: 
  - 闆嗘垚 OTEL Metrics API (PrometheusExporter)
  - 闆嗘垚 OTEL Logs API
  - 閰嶇疆 Jaeger/Honey Comb 鍚庣

#### 闂 6: 浜嬪姟瀹夊叏鎬т笉瓒?
- **鐥囩姸**: SQLite 澶氳〃鎿嶄綔鏃犳樉寮忎簨鍔?
- **褰卞搷**: 骞跺彂浜嬩欢鎻掑叆鍙兘瀵艰嚧鏁版嵁涓嶄竴鑷?
- **寤鸿**: 鍖呰 CanonicalEventStore 鍜?MemoryFactStore 鐨勫啓鍏ユ搷浣滀娇鐢?`BEGIN TRANSACTION; COMMIT`

### 8.3 鍙兘鐨勯泦鎴愭敼杩?

```
浼樺厛绾?1锛堥珮锛?
  鉁?闆嗕腑 Pydantic 妯″瀷瀹氫箟
  鉁?灏嗙畻娉曞弬鏁板閮ㄥ寲涓洪厤缃枃浠?
  鉁?娣诲姞鏄惧紡鏁版嵁搴撲簨鍔?

浼樺厛绾?2锛堜腑锛?
  鉁?涓?07_analysis_scoring 娣诲姞澶氳繘绋嬭瘎鍒?
  鉁?瀹屾暣鐨?OpenTelemetry 闆嗘垚锛圡etrics + Logs锛?
  鉁?MemPalace 缂撳瓨绛栫暐浼樺寲

浼樺厛绾?3锛堜綆锛?
  鉁?鍓嶇妯″瀷鑷姩浠ｇ爜鐢熸垚锛堜粠 Pydantic 鈫?TypeScript锛?
  鉁?鎶€鑳芥矙绠卞寲锛坰eccomp + capabilities锛?
  鉁?鍒嗗竷寮忎簨浠舵祦锛圞afka 鎴栨湰鍦?SQLite 澶囦唤锛?
```

---

## 9. 鍏抽敭鏂囦欢蹇€熷弬鑰?

### 搴旂敤绋嬪簭鍏ュ彛
- [python_adapter_server.py](python_adapter_server.py) - FastAPI 涓诲簲鐢?
- [recovery_autopilot_router.py](recovery_autopilot_router.py) - 鎭㈠绔偣

### 鏁版嵁灞?
- [canonical_event_store.py](canonical_event_store.py) - 浜嬩欢鎸佷箙鍖?
- [memory_fact_store.py](memory_fact_store.py) - 浜嬪疄鎸佷箙鍖?
- [harness_protocols.py](harness_protocols.py) - 妯″瀷瀹氫箟锛堟帹鏂級
- [recovery_store_provider.py](recovery_store_provider.py) - 鍗曚緥鑾峰彇鍣?

### 涓氬姟閫昏緫
- [recovery_autopilot_control_plane.py](recovery_autopilot_control_plane.py) - 绛栫暐绠＄悊
- [recovery_recommendation_engine.py](recovery_recommendation_engine.py) - 寤鸿鐢熸垚
- [07_analysis_scoring_improved_v9.py](07_analysis_scoring_improved_v9.py) - 璇佹嵁璇勫垎

### 鍙娴嬫€?
- [recovery_telemetry.py](recovery_telemetry.py) - 杩借釜澶栬
- [recovery_metrics_exporter.py](recovery_metrics_exporter.py) - 搴﹂噺鏀堕泦
- [datetime_utils.py](datetime_utils.py) - UTC 鏃堕棿鎴冲伐鍏?

### 闆嗘垚
- [layers/m_layer_mempalace_memory.py](layers/m_layer_mempalace_memory.py) - MemPalace 閫傞厤鍣?
- [skills/models.py](skills/models.py) - 鎶€鑳藉厓鏁版嵁妯″瀷
- [config/rag_integration_config.yaml](config/rag_integration_config.yaml) - RAG 閰嶇疆

### 閰嶇疆
- [config/rag_integration_config.yaml](config/rag_integration_config.yaml) - 缁熶竴 RAG/MemPalace 閰嶇疆

---

## 10. 鎬荤粨涓庡悗缁楠?

### 褰撳墠鏋舵瀯鐗圭偣
鉁?**浜嬩欢婧簮鏋舵瀯**: 鎵€鏈夐噸澶ф搷浣滈兘璁板綍涓鸿鑼冧簨浠讹紝鍙噸鏀? 
鉁?**鏃舵€佷簨瀹炲簱**: 鏀寔"鏃跺埢 T 鐨勭姸鎬?鏌ヨ  
鉁?**鍙娴嬫€т紭鍏?*: 杩借釜涓棿浠躲€佸害閲忓鍑哄櫒銆丱penTelemetry 闆嗘垚  
鉁?**妯″潡鍖栫閬?*: 12+ 涓『搴忓鐞嗛樁娈碉紝鏀寔涓枃瀛︽湳鏂囩尞  
鉁?**鎭㈠闊ф€?*: 鑷姩椹鹃┒鏀跨瓥銆佸簲鎬ュ仠姝€佸缓璁紩鎿? 

### 涓昏鏀硅繘鏈轰細
1. **Schema 缁勭粐**: 鍒涘缓 `models/` 鍖呴泦涓墍鏈?Pydantic 瀹氫箟
2. **鍙傛暟澶栭儴鍖?*: 杩佺Щ `07_analysis_scoring` 鏉冮噸鍒?YAML
3. **骞惰澶勭悊**: 涓哄ぇ鎵归噺璇勫垎娣诲姞 multiprocessing
4. **OTEL 瀹屾暣鎬?*: 娣诲姞 Metrics 鍜?Logs API 闆嗘垚
5. **浜嬪姟瀹夊叏**: 鍖呰澶氳〃鎿嶄綔浣跨敤浜嬪姟

### 寤鸿鐨勮繘涓€姝ユ帰绱?
- 妫€鏌?`recovery_autopilot_control_plane.py` 鍜?`recovery_execution_engine.py` 鐨勫畬鏁村疄鐜?
- 楠岃瘉鎶€鑳芥墽琛屾矙绠卞寲绛栫暐
- 鍒嗘瀽 MemPalace 涓庢湰鍦板唴瀛樼殑娣锋潅绛栫暐
- 娴嬭瘯骞跺彂鎭㈠鎿嶄綔鐨勭珵鎬佹潯浠?


