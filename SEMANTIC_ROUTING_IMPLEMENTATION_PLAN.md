# 璇箟璺敱鍗囩骇鏂规 (鏂瑰悜 A) - Sprint 瀹炴柦璁″垝

**鐩爣**锛氬皢纭紪鐮佺殑 `GOAL_MAP` 鍗囩骇涓鸿嚜鍔ㄦ墿鍏?+ 鍚戦噺璇箟璺敱鐨勭郴缁? 
**宸ュ叿閾?*锛氱鍩烘祦鍔?BAAI/bge-m3 鍚戦噺 API + 澶фā鍨?API  
**棰勬湡鍛ㄦ湡**锛? 涓?Sprint锛?.5-2 鍛級  

---

## 馃搵 Sprint 鏋舵瀯鎬昏

```
鐜扮姸锛坴40.0锛?
鈹溾攢鈹€ 07_analysis_scoring_improved_v9.py
鈹?  鈹斺攢鈹€ GOAL_MAP (纭紪鐮?14 涓瘝)
鈹?      鈹斺攢鈹€ token_score() 鈫?瑙勫垯鍖归厤
鈹斺攢鈹€ layers/ (RAG 妗嗘灦楠ㄦ灦)

鍗囩骇鐩爣锛坴40.4锛?
鈹溾攢鈹€ Sprint 1: 绂荤嚎鍏虫敞鐐瑰簱鑷姩鎻愬彇
鈹?  鈹斺攢鈹€ focus_extractor.py 锛堟柊澧烇級
鈹?      鈹溾攢鈹€ 璇诲彇鎵€鏈?PDF/Markdown 鏂囩尞
鈹?      鈹溾攢鈹€ 鐢ㄥぇ妯″瀷鑷姩鎻愬彇涓撲笟鏍囩 (5-10/绡?
鈹?      鈹斺攢鈹€ 杈撳嚭 focus_points.json (鍑犲崈涓爣绛?
鈹?
鈹溾攢鈹€ Sprint 2: 鍚戦噺璇箟璺敱鏍稿績灞?
鈹?  鈹斺攢鈹€ semantic_router.py 锛堟柊澧烇級
鈹?      鈹溾攢鈹€ 璇诲彇 focus_points.json
鈹?      鈹溾攢鈹€ 璋冪敤纭呭熀娴佸姩 bge-m3 鍚戦噺鍖栨墍鏈夋爣绛?
鈹?      鈹溾攢鈹€ 缂撳瓨鍦ㄥ唴瀛樹腑
鈹?      鈹斺攢鈹€ route_query() 姣绾у尮閰?
鈹?
鈹溾攢鈹€ Sprint 3: 绯荤粺闆嗘垚涓庝紭鍖?
鈹?  鈹溾攢鈹€ main_rag_workflow.py 锛堟柊澧烇級 
鈹?  鈹?  鈹溾攢鈹€ 瀵煎叆 SemanticRouter
鈹?  鈹?  鈹溾攢鈹€ 鐢ㄦ埛杈撳叆 鈫?璇箟鏀舵潫 鈫?RAG-Anything 娣峰悎妫€绱?
鈹?  鈹?  鈹斺攢鈹€ 杩斿洖绮惧噯鐨勫啓浣滅偣
鈹?  鈹溾攢鈹€ app.py 锛堟柊澧?Streamlit UI锛?
鈹?  鈹?  鈹斺攢鈹€ 鍙鍖栨暣涓敹鏉熷拰妫€绱㈣繃绋?
鈹?  鈹斺攢鈹€ 闆嗘垚鍒?00_Integrated_Pipeline_.py
鈹?      鈹斺攢鈹€ 浣跨敤鏂扮殑璇箟璺敱浣滀负鍓嶇疆鎷︽埅鍣?
```

---

## 馃攧 Sprint 1锛氱绾垮叧娉ㄧ偣搴撹嚜鍔ㄦ彁鍙?(2-3 澶?

### 鏂囦欢锛歚layers/focus_extractor.py`

**鏍稿績鑱岃矗**锛?
- 閬嶅巻鏈湴鎵€鏈夋枃鐚紙PDF/Markdown锛?
- 鐢ㄥぇ妯″瀷鎵归噺鎻愬彇鍏抽敭姒傚康锛堝幓閲嶅悗鍑犲崈涓級
- 淇濆瓨涓?`focus_points.json`锛堝彧闇€杩愯涓€娆★級

**瀹炵幇瑕佺偣**锛?
1. **闃插崱姝荤綉缁?*锛氫娇鐢ㄥ睆钄戒唬鐞嗙殑 `httpx.Client`
2. **鎵瑰鐞?*锛氬噺灏?API 璋冪敤锛?-10 绡?鎵癸級
3. **鍘婚噸鍚堝苟**锛氬叧娉ㄧ偣 + 鍚屼箟璇嶆敹鏁?
4. **閲嶈瘯鏈哄埗**锛氬鐞?API 澶辫触

**浼唬鐮佺粨鏋?*锛?
```python
class FocusExtractor:
    def __init__(self, api_key, base_url):
        self.client = httpx.Client(proxies=None, timeout=60.0)
        self.api_key = api_key
        
    async def extract_from_document(self, doc_path: str) -> List[str]:
        """鎻愬彇鍗曠瘒鏂囩尞鐨?5-10 涓牳蹇冩爣绛?""
        # 璇诲彇鏂囦欢 鈫?鎴柇鑷冲墠 3000 tokens
        # 璋冪敤澶фā鍨嬫彁绀鸿瘝锛?
        #   "鍒楀嚭杩欑瘒鏂囩尞鐨?5 鍒?10 涓牳蹇冪爺绌舵爣绛撅紙鍚嶈瘝鐭锛?
        # 杩斿洖 ["鍙傛暟浼樺寲", "鐑緭鍏ユ帶鍒?, "鏅剁矑缁嗗寲", ...]
    
    async def batch_extract(self, doc_folder: str) -> Set[str]:
        """鎵归噺鎻愬彇鎵€鏈夋枃鐚苟鍘婚噸"""
        all_tags = set()
        for doc in os.listdir(doc_folder):
            tags = await self.extract_from_document(doc)
            all_tags.update(tags)
        return all_tags
    
    def save_focus_points(self, tags: Set[str], output_path: str):
        """淇濆瓨涓?JSON 渚涘悗缁ā鍧椾娇鐢?""
        with open(output_path, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'count': len(tags),
                'points': sorted(list(tags))
            }, f, ensure_ascii=False, indent=2)
```

**杩愯鏂瑰紡**锛?
```bash
python -m layers.focus_extractor \
  --doc-folder "./papers" \
  --output "focus_points.json" \
  --batch-size 5
```

**杈撳嚭鏂囦欢**锛坄focus_points.json`锛夛細
```json
{
  "timestamp": "2026-04-01T10:30:00",
  "count": 2847,
  "points": [
    "鍙傛暟浼樺寲",
    "鐑緭鍏ユ帶鍒?,
    "鏅剁矑缁嗗寲",
    "婵€鍏夊姛鐜囪皟鍒?,
    "鐔旀睜娴佸姩鍔ㄥ姏瀛?,
    ...
  ]
}
```

---

## 馃Л Sprint 2锛氬悜閲忚涔夎矾鐢辨牳蹇冨眰 (2-3 澶?

### 鏂囦欢锛歚layers/semantic_router.py`

**鏍稿績鑱岃矗**锛?
- 灏?`focus_points.json` 涓殑鎵€鏈夋爣绛惧悜閲忓寲
- 鍦ㄥ唴瀛樹腑缁存姢鍚戦噺缂撳瓨
- 鐢ㄦ埛鎻愰棶鏃讹紝姣绾у尮閰嶆渶鐩稿叧鐨?3-5 涓叧娉ㄧ偣

**瀹炵幇瑕佺偣**锛?
1. **鍚戦噺妯″瀷**锛氱鍩烘祦鍔?`BAAI/bge-m3`锛堜腑鏂囦紭鍖栵級
2. **鎵归噺鍚戦噺鍖?*锛氫竴娆¤皟鐢ㄥ涓爣绛撅紝鍑忓皯 API 娆℃暟
3. **缂撳瓨绛栫暐**锛氬惎鍔ㄦ椂鍔犺浇锛屽唴瀛橀┗鐣?
4. **鐩镐技搴﹁绠?*锛氫綑寮︾浉浼煎害锛堢函 numpy锛屾绉掔骇锛?

**浼唬鐮佺粨鏋?*锛?
```python
class SemanticRouter:
    def __init__(self, api_key, focus_points_path):
        """鍒濆鍖栨椂涓€娆℃€у悜閲忓寲鎵€鏈夊叧娉ㄧ偣"""
        self.api_key = api_key
        self.client = httpx.Client(proxies=None, timeout=60.0)
        
        # 1. 鍔犺浇鍏虫敞鐐瑰簱
        with open(focus_points_path) as f:
            data = json.load(f)
            self.focus_points = data['points']  # List[str]
        
        # 2. 鎵归噺鍚戦噺鍖栵紙璋冪敤纭呭熀娴佸姩 bge-m3锛?
        self.focus_vectors = self._batch_vectorize(self.focus_points)
        # shape: (len(focus_points), 1024)  # bge-m3 杈撳嚭 1024 缁?
        
    def _batch_vectorize(self, texts: List[str], batch_size=50):
        """鎵归噺璋冪敤鍚戦噺 API锛堝噺灏?API 娆℃暟锛?""
        vectors = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            # 璋冪敤纭呭熀娴佸姩 API锛?v1/embeddings
            embeddings = call_siliconflow_embedding_api(batch)
            vectors.extend(embeddings)
        return np.array(vectors)
    
    def route_query(self, user_query: str, top_k: int = 3) -> List[str]:
        """
        鐢ㄦ埛鎻愰棶 鈫?鏀舵潫鍒板叧娉ㄧ偣
        
        渚嬶細
        user_query = "杩欎釜瀹為獙閲岀殑娓╁害鍙傛暟鏄€庢牱褰卞搷鐨勶紵"
        杩斿洖 ["鐑緭鍏ユ帶鍒?, "鍐峰嵈閫熺巼", "娓╁害姊害"]
        """
        # 1. 鍚戦噺鍖栫敤鎴锋煡璇紙涓€娆?API 璋冪敤锛?
        query_vector = call_siliconflow_embedding_api([user_query])[0]
        
        # 2. 浣欏鸡鐩镐技搴﹁绠楋紙绾?numpy锛?1ms锛?
        similarities = cosine_similarity([query_vector], self.focus_vectors)[0]
        
        # 3. 鍙?top-k
        top_indices = np.argsort(similarities)[-top_k:][::-1]
        top_points = [self.focus_points[i] for i in top_indices]
        
        return top_points
    
    def get_point_hierarchy(self) -> Dict[str, List[str]]:
        """鍙€夛細鎸夊叧閿瘝鑱氱被褰㈡垚灞傜骇锛堢敤浜?Coarse-to-Fine锛?""
        # 瀵规墍鏈夊叧娉ㄧ偣鍚戦噺杩涜鑱氱被锛堝 KMeans k=50锛?
        # 杩斿洖灞傜骇缁撴瀯渚涘悗缁紭鍖栦娇鐢?
        pass
```

**杩愯鏂瑰紡**锛?
```bash
# 鍒濆鍖栨椂锛堝惎鍔ㄧ郴缁燂級
router = SemanticRouter(
    api_key=os.environ['SILICONFLOW_API_KEY'],
    focus_points_path='focus_points.json'
)

# 鏌ヨ鏃?
top_points = router.route_query("娓╁害濡備綍褰卞搷鏅剁矑褰㈡€侊紵")
# 鈫?["娓╁害姊害", "鍐峰嵈閫熺巼", "鍙傛暟浼樺寲"]
```

**鍏抽敭浼樺娍**锛?
- 鉁?姣绾у搷搴旓紙鍚戦噺宸茬紦瀛橈級
- 鉁?鏃犻渶鏈湴 GPU锛堣皟鐢ㄤ簯 API锛?
- 鉁?鑷姩閫傚簲鏂板鐨勫叧娉ㄧ偣锛堝彧闇€閲嶆柊杩愯 `focus_extractor.py`锛?
- 鉁?鏀寔鍚屼箟璇嶅拰鍙ｈ琛ㄨ揪锛堝悜閲忚涔夛級

---

## 馃敆 Sprint 3锛氱郴缁熼泦鎴愪笌浼樺寲 (3-4 澶?

### 3.1 鏂囦欢锛歚main_rag_workflow.py`锛堟牳蹇冮泦鎴愮偣锛?

**鑱岃矗**锛?
1. 鍒濆鍖?SemanticRouter
2. 鎺ユ敹鐢ㄦ埛闂 鈫?璋冪敤璺敱鍣?鈫?鑾峰緱绮惧噯鍏虫敞鐐?
3. 鎷兼帴鎴愬寮烘煡璇㈣瘝锛屽彂閫佺粰 RAG-Anything
4. 杩斿洖鏈€缁堢殑鍐欎綔鐐归泦鍚?

**浼唬鐮?*锛?
```python
class RAGWorkflow:
    def __init__(self, rag_instance, semantic_router):
        self.rag = rag_instance  # RAG-Anything 瀹炰緥
        self.router = semantic_router
    
    async def ask_my_literature(self, user_query: str):
        """瀹屾暣鐨勬煡璇㈡祦绋?""
        
        # 绗?1 姝ワ細璇箟鏀舵潫
        focused_points = self.router.route_query(user_query, top_k=3)
        
        # 绗?2 姝ワ細鏋勫缓澧炲己鏌ヨ璇?
        enhanced_query = (
            f"鍩轰簬鍏虫敞鐐?{focused_points}锛?
            f"璇蜂粠鏂囩尞涓绱㈠苟鍥炵瓟锛歿user_query}"
        )
        
        # 绗?3 姝ワ細璋冪敤 RAG-Anything 娣峰悎妫€绱?
        rag_results = await self.rag.aquery(
            enhanced_query,
            param=QueryParam(mode="hybrid", top_k=10)
        )
        
        # 绗?4 姝ワ細鐢ㄥぇ妯″瀷鐢熸垚鏈€缁堢瓟妗?
        final_answer = await self.generate_synthesis(
            user_query,
            focused_points,
            rag_results
        )
        
        return {
            'focused_points': focused_points,
            'rag_results': rag_results,
            'final_answer': final_answer,
            'trace': {  # 鍙鍖栬拷韪?
                'user_query': user_query,
                'enhanced_query': enhanced_query,
                'routing_confidence': self.router.get_confidence(focused_points)
            }
        }
    
    async def generate_synthesis(self, query, points, rag_results):
        """鍒╃敤澶фā鍨嬭繘琛屾渶缁堝悎鎴?""
        prompt = f"""
        鐢ㄦ埛闂锛歿query}
        绯荤粺璇嗗埆鐨勫叧娉ㄧ偣锛歿', '.join(points)}
        妫€绱㈠埌鐨勭浉鍏虫枃鐚钀斤細{rag_results[:500]}
        
        璇峰熀浜庝笂杩颁俊鎭紝鐢熸垚涓€涓鏈€х殑鍥炵瓟銆?
        """
        # 璋冪敤澶фā鍨?API
        response = await call_llm(prompt)
        return response
```

**浣跨敤绀轰緥**锛?
```python
# 鍦?00_Integrated_Pipeline_.py 涓泦鎴?
workflow = RAGWorkflow(rag_instance, semantic_router)

# 鐢ㄦ埛鎻愰棶
result = await workflow.ask_my_literature(
    "婵€鍏夊姛鐜囧浣曞奖鍝嶇啍姹犱腑鐨勬爱浼犺緭锛?
)

print(f"璇嗗埆鐨勫叧娉ㄧ偣: {result['focused_points']}")
print(f"鏈€缁堢瓟妗? {result['final_answer']}")
```

---

### 3.2 鏂囦欢锛歚app.py`锛圫treamlit UI锛?

**鑱岃矗**锛?
- 鍙鍖栨暣涓祦绋?
- 灞曠ず璇箟鏀舵潫鐨勪腑闂存楠?
- 鎻愪緵浜や簰寮忔煡璇㈢晫闈?

**鍏抽敭缁勪欢**锛?
```python
import streamlit as st

st.set_page_config(page_title="鏂囩尞璇箟妫€绱㈢郴缁?, layout="wide")

col1, col2 = st.columns([2, 1])

with col1:
    st.title("馃摎 鏂囩尞璇箟鏅鸿兘妫€绱?)
    user_query = st.text_area("杈撳叆鎮ㄧ殑闂", height=100)
    
    if st.button("馃攳 妫€绱?):
        with st.spinner("绯荤粺姝ｅ湪璇嗗埆鍏虫敞鐐?.."):
            # 璋冪敤璇箟璺敱鍣?
            focused_points = router.route_query(user_query)
            
            # 灞曠ず涓棿姝ラ
            st.info(f"**鉁?绯荤粺宸插皢鎮ㄧ殑鎻愰棶璇箟鏀舵潫涓?**\n{', '.join(focused_points)}")
            
            # 璋冪敤 RAG
            with st.spinner("姝ｅ湪浠庢枃鐚簱涓绱㈣瘉鎹?.."):
                rag_results = await workflow.ask_my_literature(user_query)
            
            # 娴佸紡杈撳嚭绛旀
            st.markdown("### 馃摉 鏂囩尞缁煎悎鍒嗘瀽缁撴灉")
            with st.spinner("澶фā鍨嬫鍦ㄧ敓鎴愬洖绛?.."):
                for chunk in stream_llm_response(rag_results):
                    st.write(chunk)

with col2:
    st.sidebar.markdown("### 鈿欙笍 绯荤粺鐘舵€?)
    st.sidebar.metric("鍏虫敞鐐瑰簱瑙勬ā", len(router.focus_points))
    st.sidebar.metric("鍚戦噺缁村害", 1024)
    st.sidebar.markdown("### 馃搳 璺敱淇℃伅")
    for point in focused_points:
        st.sidebar.write(f"鉁?{point}")
```

---

### 3.3 闆嗘垚鍒?`00_Integrated_Pipeline_.py`

**鏀瑰姩鐐?*锛?

```python
# 鍦ㄦ枃浠跺紑澶存坊鍔?
from layers.semantic_router import SemanticRouter
from main_rag_workflow import RAGWorkflow

# 鍦ㄥ垵濮嬪寲鍑芥暟涓?
async def init_system():
    # 鐜版湁鍒濆鍖?..
    rag = LightRAG(...)
    
    # 鏂板锛氬垵濮嬪寲璇箟璺敱鍣?
    semantic_router = SemanticRouter(
        api_key=os.environ['SILICONFLOW_API_KEY'],
        focus_points_path='focus_points.json'
    )
    
    # 鏂板锛氬垵濮嬪寲 RAG 宸ヤ綔娴?
    workflow = RAGWorkflow(rag, semantic_router)
    
    return workflow

# 鍦ㄤ富鏌ヨ鍑芥暟涓?
async def process_goal(user_input: str):
    # 鍘熸湁閫昏緫淇濈暀锛屼絾鍓嶇疆娣诲姞璇箟璺敱
    focused_points = workflow.router.route_query(user_input)
    
    # 娉ㄥ叆鍒板師鏈夌殑鍒嗘瀽娴佺▼
    goal_profile = infer_goal_profile(user_input)
    goal_profile['focused_points'] = focused_points  # 棰濆淇℃伅
    
    # 鍚庣画璋冪敤 analyze_bound() 绛夊嚱鏁版椂锛屽彲浠ュ埄鐢ㄨ繖涓俊鎭?
    ...
```

---

## 馃搳 Sprint 瀹炴柦鏃堕棿琛?

| Sprint | 浠诲姟 | 宸ヤ綔閲?| 浜や粯鐗?|
|--------|------|--------|--------|
| **1** | 绂荤嚎鍏虫敞鐐规彁鍙?| 2-3 澶?| `focus_extractor.py` + `focus_points.json` |
| **2** | 鍚戦噺璇箟璺敱 | 2-3 澶?| `semantic_router.py` + 缂撳瓨鏈哄埗 |
| **3a** | 绯荤粺闆嗘垚 | 1-2 澶?| `main_rag_workflow.py` + 鏀归€犱富娴佺▼ |
| **3b** | UI 涓庝紭鍖?| 1-2 澶?| `app.py` + 鎬ц兘璋冧紭 |

**鎬婚鏈?*锛?.5-2 鍛ㄥ唴瀹屾垚鏁翠釜鍗囩骇

---

## 馃敡 纭呭熀娴佸姩 API 闆嗘垚缁嗚妭

### 鍚戦噺 API 璋冪敤绀轰緥

```python
import httpx
import json

async def call_siliconflow_embedding(texts: List[str], api_key: str):
    """璋冪敤纭呭熀娴佸姩 bge-m3 鍚戦噺鍖栨帴鍙?""
    
    client = httpx.AsyncClient(proxies=None, timeout=60.0)
    
    response = await client.post(
        "https://api.siliconflow.cn/v1/embeddings",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "BAAI/bge-m3",
            "input": texts,
            "encoding_format": "float"
        }
    )
    
    result = response.json()
    embeddings = [item['embedding'] for item in result['data']]
    return embeddings
```

### 澶фā鍨?API 璋冪敤绀轰緥锛堜繚鐣欓槻鍗℃鏈哄埗锛?

```python
async def call_siliconflow_llm(prompt: str, api_key: str):
    """璋冪敤纭呭熀娴佸姩澶фā鍨嬶紙宸叉暣鍚堥槻鍗℃鏈哄埗锛?""
    
    client = httpx.AsyncClient(proxies=None, timeout=60.0)
    
    response = await client.post(
        "https://api.siliconflow.cn/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "deepseek-ai/DeepSeek-V3",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
    )
    
    result = response.json()
    return result['choices'][0]['message']['content']
```

---

## 鉁?楠岃瘉娓呭崟

鍦ㄥ惎鍔?Sprint 1 鍓嶏紝璇风‘璁わ細

- [ ] 纭呭熀娴佸姩璐︽埛宸插紑閫氾紝鏈?API key
- [ ] `focus_points.json` 鎵€鍦ㄦ枃浠跺す宸插噯澶?
- [ ] `.env` 涓缃簡 `SILICONFLOW_API_KEY`
- [ ] 鐞嗚В涓変釜鏂版枃浠剁殑鑱岃矗杈圭晫
- [ ] 鐜版湁鐨?`07_analysis_scoring_improved_v9.py` 鏆傛椂淇濈暀锛堜綔涓?Fallback锛?

---

## 馃幆 鍏抽敭閲岀▼纰?

- **Sprint 1 瀹屾垚**锛氱郴缁熷彲浠ヨ嚜鍔ㄦ墿鍏呭叧娉ㄧ偣搴擄紙涓嶅啀鎵嬪伐缁存姢锛?
- **Sprint 2 瀹屾垚**锛氱郴缁熷彲浠ユ绉掔骇璇箟鍖归厤鐢ㄦ埛闂锛堟浛浠ｈ鍒欏尮閰嶏級
- **Sprint 3 瀹屾垚**锛氱郴缁熷畬鍏ㄩ泦鎴愶紝鐢ㄦ埛鏃犳劅鐭ュ崌绾э紝璐ㄩ噺鏄捐憲鎻愬崌

---

**鍑嗗濂藉紑濮?Sprint 1 浜嗗悧锛熸垜鍙互鐩存帴缁欐偍 `focus_extractor.py` 鐨勫畬鏁翠唬鐮併€?*

