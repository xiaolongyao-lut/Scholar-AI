# Modular 鏂囩尞鍔╂墜绯荤粺 - 鐪熷疄璇勪及涓庤繘鍖栬鍒?

**璇勪及鏃堕棿**: 2026-04-11  
**鍩虹绯荤粺**: 6灞傛灦鏋?(E/A/R/K/G/P) + WritingRuntime + RAG闆嗘垚  
**鐩爣婕旇繘**: 浠?瀛︽湳璁烘枃澶勭悊鍣? 鈫?"浜や簰寮忔枃鐚姪鎵?

---

## 馃幆 鐜版湁绯荤粺鐪熷疄璇勪及

### 鏍稿績鏋舵瀯鐜扮姸 (宸插畬鎴?

```
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?
鈹?        MODULAR ACADEMIC DOCUMENT PROCESSING (v40)          鈹?
鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?

E-Layer (Extraction)           鉁?瀹屾垚
鈹溾攢 PDF鏂囨湰+鍥惧儚鎻愬彇
鈹溾攢 澶氭ā鎬佽祫浜ц瘑鍒?
鈹斺攢 浣跨敤: e_layer_multimodal.py

A-Layer (Agent & Orchestration) 鉁?瀹屾垚
鈹溾攢 鎰忓浘瑙ｆ瀽
鈹溾攢 鍏虫敞鐐规彁鍙? 
鈹斺攢 浣跨敤: a_layer_agent_coordinator.py

R-Layer (Retrieval)            鉁?瀹屾垚
鈹溾攢 BM25鍏抽敭璇嶆帓搴?
鈹溾攢 璇箟鍏抽敭璇嶉噸鍙?
鈹斺攢 浣跨敤: r_layer_hybrid_retriever.py

K-Layer (Knowledge Index)       鉁?閮ㄥ垎瀹屾垚
鈹溾攢 鏁版嵁濂戠害缁戝畾
鈹溾攢 椤圭洰鐪嬫澘鏋勫缓
鈹斺攢 浣跨敤: k_layer_index_builder.py

G-Layer (Generation & Scoring) 鉁?瀹屾垚
鈹溾攢 瀛︽湳璇勫垎閫昏緫
鈹溾攢 浜嬪疄鎻愬彇
鈹溾攢 浣跨敤: g_layer_academic_generator.py + g_synthesis_graphrag_bridge.py
鈹斺攢 渚濊禆: modules/evidence_classifier.py (scoring_rules.json)

P-Layer (Presentation)          鉁?瀹屾垚
鈹溾攢 Word鏂囨。鐢熸垚
鈹溾攢 鍥捐〃鎺掔増
鈹斺攢 浣跨敤: p_layer_presentation_word.py

M-Layer (Memory)                鈿狅笍 閮ㄥ垎闆嗘垚
鈹溾攢 Mempalace闀挎湡璁板繂
鈹溾攢 浼氳瘽绠＄悊
鈹斺攢 浣跨敤: layers/m_layer_mempalace_memory.py + writing_runtime.py

RAG Integration                 鈿狅笍 鍩虹妗嗘灦瀹屾垚
鈹溾攢 GraphRAG妗ユ帴
鈹溾攢 AutoRAG鏀寔
鈹斺攢 浣跨敤: rag_integration_entry.py + main_rag_workflow.py
```

### 鐜版湁妯″潡璇勫垎

| 妯″潡 | 瀹屾垚搴?| 璐ㄩ噺 | 绋冲畾鎬?| 鍙墿灞曟€?|
|------|--------|------|--------|---------|
| **E-Layer** | 95% | 9/10 | 鉁?绋冲畾 | 涓?|
| **A-Layer** | 80% | 8/10 | 鈿狅笍 娴嬭瘯涓?| 楂?|
| **R-Layer** | 90% | 8.5/10 | 鉁?绋冲畾 | 楂?|
| **K-Layer** | 70% | 7/10 | 鈿狅笍 闇€浼樺寲 | 涓?|
| **G-Layer** | 85% | 8/10 | 鉁?绋冲畾 | 涓?|
| **P-Layer** | 90% | 8.5/10 | 鉁?绋冲畾 | 浣?|
| **M-Layer** | 50% | 6/10 | 鉂?璇曢獙 | 楂?|
| **RAG** | 60% | 7/10 | 鈿狅笍 璇曢獙 | 楂?|

---

## 馃攳 褰撳墠鐨勬牳蹇冮棶棰?

鍩轰簬浠ｇ爜鍒嗘瀽锛岀郴缁熷瓨鍦ㄧ殑瀹為檯闂锛?

### 1. **鐭ヨ瘑鎸佷箙鍖栦笌鏌ヨ** (鏈€澶х棝鐐?
```python
# 褰撳墠: 姣忔杩愯閮芥槸鐙珛鐨勬壒澶勭悊
00_Integrated_Pipeline_.py 鈫?output/paper_id/
  鈹溾攢 01_full_extract.json
  鈹溾攢 02_hybrid_retrieval.json
  鈹溾攢 03_academic_scoring.json
  鈹斺攢 paper_id_report.docx

闂:
  鉂?鏃犳硶璺ㄨ鏂囨煡璇?(K-Layer绱㈠紩涓嶅畬鏁?
  鉂?鏃犳硶璁板繂鍓嶆鍒嗘瀽 (铏芥湁WritingRuntime浣嗘湭闆嗘垚)
  鉂?鏃犳硶杩涜浜や簰寮忓璇?
  鉂?閲嶅璁＄畻娴垂璧勬簮
```

### 2. **瀵硅瘽浜や簰缂哄け**
```
褰撳墠: 鍗曞悜淇℃伅娴?
鐢ㄦ埛 鈫?PDF 鈫?澶勭悊 鈫?鎶ュ憡

闇€瑕佺殑: 鍙屽悜浜や簰
鐢ㄦ埛 鈫愨啋 绯荤粺(璁板繂涓婁笅鏂? 鈫愨啋 鏂囩尞搴?
  鈹溾攢 "杩欎釜鎬庝箞鐞嗚В锛?
  鈹溾攢 "鍜屼箣鍓嶇殑璁烘枃浠€涔堝叧绯伙紵"
  鈹斺攢 "缁欐垜鎬荤粨涓€涓嬫牳蹇冭鐐?
```

### 3. **澧為噺瀛︿範涓庡弽棣?*
```
褰撳墠: 瀹屽叏鏃犺蹇?
姣忎釜鏂拌姹?= 鍐峰惎鍔?

缂哄け: 
  鉂?鐢ㄦ埛鍙嶉 鈫?鏀硅繘璇勫垎瑙勫垯
  鉂?鏂拌鏂?鈫?鑷姩鏇存柊绱㈠紩
  鉂?鍏宠仈璁烘枃 鈫?鑷姩妫€娴嬪紩鐢ㄥ叧绯?
```

### 4. **鏌ヨ鐏垫椿鎬?*
```
褰撳墠鑳藉仛:
  鉁?鐩爣瀵煎悜鎻愬彇 (鎸塯oal鏌ヨ)
  鉁?娣峰悎妫€绱?(BM25+鍏抽敭璇?
  鉁?瀛︽湳璇勫垎 (鎸塻coring_rules)

鏃犳硶鍋?
  鉂?璺ㄥ煙澶氭潯浠舵煡璇?(娌℃湁unified query engine)
  鉂?璇箟鐩镐技璁烘枃鏌ヨ (K-Layer鍚戦噺绱㈠紩涓嶅畬鏁?
  鉂?鏃堕棿/褰卞搷鍔涙帓搴?(娌℃湁棰濆鐨勫厓鏁版嵁澶勭悊)
```

---

## 馃挕 "鏂囩尞鍔╂墜"鐨勭湡瀹炲畾涔?

鍩轰簬鐜版湁绯荤粺锛屾枃鐚姪鎵嬪簲璇ユ槸锛?

```
鈺斺晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晽
鈺?   Interactive Literature & Memory Hub     鈺?
鈺犫晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨暎
鈺?                                           鈺?
鈹? 鐢ㄦ埛(Q1)->| 涓婁笅鏂囪蹇?|<- 鐢ㄦ埛(Q2)       鈹?
鈹?            鈫?                              鈹?
鈹?         缁熶竴鏌ヨ寮曟搸                      鈹?
鈹?            鈫?鈫?鈫?                         鈹?
鈹?     鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹?        鈹?
鈹?     鈹?K灞傜储寮?鈹?鏂囨湰搴? 鈹?璇勫垎 鈹?        鈹?
鈹?     鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹粹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹粹攢鈹€鈹€鈹€鈹€鈹€鈹?        鈹?
鈹?            鈫?鈫?鈫?                         鈹?
鈹?         缁撴灉姹囪仛 + 鎺ㄧ悊                   鈹?
鈹?            鈫?                             鈹?
鈹?       鐢ㄦ埛鈫愮粨鏋?璁板繂鏇存柊                  鈹?
鈺?                                           鈺?
鈺氣晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨暆
```

**鏍稿績闇€瑕佺殑4涓兘鍔?*:

1. **鎸佷箙鍖栧瓨鍌?* - 涓嶅啀鏄竴娆℃€SON锛岄渶瑕佺湡鏁版嵁搴?
2. **涓婁笅鏂囪蹇?* - WritingRuntime + M-Layer 鐨勫畬鏁撮泦鎴?
3. **浜や簰寮忔煡璇?* - RESTful API + CLI宸ュ叿
4. **澧為噺婕旇繘** - 鏂板姛鑳芥棤闇€閲嶅啓锛屾彃浠跺紡鎵╁睍

---

## 馃殌 鐜板疄鐨勮繘鍖栨柟鍚?(鍒嗕紭鍏堢骇)

### 绗竴闃舵: 鐭ヨ瘑搴撴暟鎹寲 (2-3鍛?

**鐩爣**: 鎶妔tandalone JSON鑴氭湰鍙樻垚鎸佷箙鍖栫郴缁?

```python
# 鐜扮姸
output/paper_001/
鈹溾攢 01_full_extract.json     (2MB)
鈹溾攢 02_hybrid_retrieval.json (500KB)
鈹溾攢 03_academic_scoring.json (300KB)
鈹斺攢 report.docx

鈫?(闇€瑕佹敼杩?

# 鐩爣鏋舵瀯
./knowledge_base/
鈹溾攢 sqlite3: modular.db
鈹?  鈹溾攢 papers (paper_id, title, doi, source_pdf_hash)
鈹?  鈹溾攢 extracts (id, paper_id, chunks, metadata)
鈹?  鈹溾攢 analyses (id, paper_id, goal, score, claims)
鈹?  鈹溾攢 focus_points (id, canonical_name, aliases, freq)
鈹?  鈹斺攢 relationships (paper_a, paper_b, relation_type)
鈹?
鈹溾攢 vector_index/
鈹?  鈹斺攢 chunks_embeddings.faiss (鐢ㄤ簬璇箟妫€绱?
鈹?
鈹斺攢 llm_cache/
    鈹斺攢 query_cache.db (閬垮厤閲嶅璋冪敤)
```

**浠ｇ爜鏀瑰姩**:
- 鏂板缓 `layers/db_layer.py` - 鏁版嵁搴撴娊璞″眰
- 淇敼 `run_paper_scoring.py` - 淇濆瓨鍒癉B鑰岄潪JSON
- 鏂板缓 `knowledge_store/` - 鏁版嵁搴撹縼绉诲拰鏌ヨ鎺ュ彛

**宸ヤ綔閲?*: 150-200 琛屾牳蹇冧唬鐮?

---

### 绗簩闃舵: 浜や簰寮忔煡璇?(2鍛?

**鐩爣**: 浠?鎵瑰鐞嗚剼鏈?鍙樻垚"鏌ヨ绯荤粺"

```python
# 鏂板鎺ュ彛绀轰緥

class LiteratureAssistant:
    def ask(self, query: str) -> Dict[str, Any]:
        """
        杈撳叆: "婵€鍏夊姛鐜囧浣曞奖鍝嶆櫠绮掔粏鍖栵紵"
        杈撳嚭: 
        {
            "answer": "...",
            "source_papers": [...],
            "confidence": 0.85,
            "related_questions": ["...", "..."],
            "analysis_context": {...}  # 涓婃鐩稿叧鐨勫垎鏋愮粨鏋?
        }
        """
    
    def clarify(self, feedback: str) -> Dict[str, Any]:
        """鐢ㄦ埛鍙嶉锛屼紭鍖栦笅娆℃煡璇?""
        
    def get_relationships(self, paper_id: str) -> List[Dict]:
        """鑾峰彇鐩稿叧璁烘枃network"""
```

**鍩虹**:
- 鍒╃敤鐜版湁鐨?`semantic_router.py` (宸叉湁鍚戦噺鍖?
- 闆嗘垚 `main_rag_workflow.py` 鐨凴AG鑳藉姏
- 浣跨敤 `writing_runtime.py` 鐨勪細璇濈鐞?

**宸ヤ綔閲?*: 200-250 琛?

---

### 绗笁闃舵: 澧為噺瀛︿範鍜屾紨杩?(2鍛?

**鐩爣**: 绯荤粺鑷姩瀛︿範鍜屾敼杩?

```python
# 鏂板鑳藉姏

class EvolutiveAnalyzer:
    def on_user_feedback(self, analysis_id, feedback):
        """鐢ㄦ埛鏍囪"杩欎釜璇勫垎涓嶅"鈫?鏇存柊scoring_rules.json"""
        
    def detect_new_relationships(self):
        """鎵弿鏂拌鏂団啋 鑷姩妫€娴嬪紩鐢ㄥ叧绯?""
        
    def recommend_queries(self):
        """鍩轰簬鍓嶆鏌ヨ鈫?鎺ㄨ崘鐩稿叧闂"""
```

**闆嗘垚鐐?*:
- 淇敼 `scoring_rules.json` 鏈哄埗 (鐜板湪鏄潤鎬侀厤缃?
- 鍦?`WritingRuntime` 涓拷韪垎鏋愬巻鍙?
- 鏂板 `feedback_loop.py` 澶勭悊鐢ㄦ埛鍙嶉

**宸ヤ綔閲?*: 150-200 琛?

---

## 馃搳 涓庣幇鏈夌郴缁熺殑鏄犲皠

```
鏂板姛鑳?                   鈫?澶嶇敤鐜版湁妯″潡
鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
鏁版嵁搴撳瓨鍌?               鈫?E-Layer/G-Layer杈撳嚭
鎸佷箙鍖栫储寮?               鈫?K-Layer鏀硅繘
浜や簰寮忔煡璇?               鈫?R-Layer+RAG闆嗘垚
浼氳瘽璁板繂                  鈫?WritingRuntime+M-Layer
澧為噺瀛︿範                  鈫?鏂板鍙嶉鏈哄埗
```

---

## 鈿欙笍 瀹為檯鍙鐨勭涓€姝?

**绔嬪嵆鍙仛 (浠婂ぉ/鏄庡ぉ)**:

```bash
1. 閫夋嫨鏁版嵁搴撴柟妗?
   鈻?SQLite (绠€鍗? 鏈湴)
   鈻?PostgreSQL (鐢熶骇绾? 闇€閮ㄧ讲)
   鈫?寤鸿: SQLite,  鍚庨潰鍙縼绉?

2. 璁捐鏁版嵁schema
   鈻?papers table
   鈻?analyses table  
   鈻?relationships table
   鈻?user_feedback table

3. 鏂板 db_layer.py (100 琛?
   {
       def save_analysis(paper, result)
       def query_papers_by_goal(goal)
       def get_related_papers(paper_id)
   }
```

**鏃堕棿**: 1-2 澶? 
**宸ヤ綔閲?*: 300-400 琛屼唬鐮? 
**鏀剁泭**: 绯荤粺浠?涓€娆℃€? 鈫?"鍙煡璇?

---

## 馃搱 鏈潵鐨?鐪嬪埌鍟ュソ鐨勫氨鍔犲暐"

杩欎釜妗嗘灦鍏佽鎸佺画婕旇繘锛?

```
Week 1: 鏁版嵁搴?鏌ヨ
  鉁?API: GET /papers, POST /analyze

Week 2: 瀵硅瘽闆嗘垚  
  鉁?API: POST /ask, POST /feedback

Week 3: 鍙鍖栫湅鏉?
  鉁?Frontend: 璁烘枃network鍥? 鍒嗘瀽鍘嗗彶

Week 4: 楂樼骇鍔熻兘
  鉁?鑷姩鎬荤粨鐢熸垚
  鉁?瀵规爣鍒嗘瀽 (姣旇緝璁烘枃)
  鉁?瓒嬪娍鍒嗘瀽 (鎸夊勾浠?鏈熷垔)

Week 5+: 寮€婧愮ぞ鍖哄姛鑳?
  鉁?鐢ㄦ埛鏍囨敞
  鉁?绀惧尯鐭ヨ瘑鍥捐氨
  鉁?鎻掍欢绯荤粺
```

---

## 馃幆 寤鸿鐨凙ction List

- [ ] **纭畾鏁版嵁搴?* (1澶?
  - 閫夋嫨: SQLite vs PostgreSQL
  
- [ ] **璁捐Schema** (1澶?
  - 鍙傝€冪幇鏈塉SON缁撴瀯
  - 瀹氫箟tables鍜岀储寮?
  
- [ ] **瀹炵幇db_layer** (2澶?
  - 鎻愪緵ORM/Query鎺ュ彛
  - 闆嗘垚鍒扮幇鏈塸ipeline
  
- [ ] **鏂板Query API** (2澶?
  - Simple REST endpoints
  - 浣跨敤鐜版湁鐨凴-Layer妫€绱?
  
- [ ] **闆嗘垚WritingRuntime** (2澶?
  - 浼氳瘽鎸佷箙鍖?
  - 涓婁笅鏂囪蹇?

---

**鐜板疄璇勪及**: 涓婅堪绗竴闃舵 **5-7澶╁唴鍙畬鎴?*, 绯荤粺灏辫兘浠?鎵硅剼鏈?鍗囩骇鍒?鍙煡璇㈢殑鐭ヨ瘑绯荤粺"銆?

涓嬩竴姝ワ細**浣犳槸鍚︾‘璁よ繖涓柟鍚戯紵** 杩樻槸鎯冲厛鐪嬬湅鏈夋病鏈夌幇鎴愮殑杞婚噺绾у紩鎿庡彲浠ョ洿鎺ョ敤锛?

