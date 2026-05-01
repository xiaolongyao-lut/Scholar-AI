import fitz
import sys

sys.stdout.reconfigure(encoding='utf-8')

papers = [
    ("Financial Report Chunking", r"C:\Users\xiao\Downloads\切块算法\Financial Report Chunking for Effective Retrieval Augmented Generation.pdf"),
    ("Is Semantic Chunking Worth", r"C:\Users\xiao\Downloads\切块算法\Is Semantic Chunking Worth the Computational Cost.pdf"),
    ("Dense X Retrieval", r"C:\Users\xiao\Downloads\切块算法\Dense X Retrieval What Retrieval Granularity Should We Use.pdf"),
    ("Reconstructing Context", r"C:\Users\xiao\Downloads\切块算法\Reconstructing_Context_Evaluating_Advanced_Chunkin.pdf"),
    ("DMG-RAG pages 2-4", r"C:\Users\xiao\Downloads\切块算法\DMG-RAG Dynamic Multi-Grained Retrieval Augmented Generation for Multi-Hop QA.pdf"),
    ("Evaluating Modern RAG pages", r"C:\Users\xiao\Downloads\切块算法\Evaluating_Modern_RAG__Textual__Multimodal__Dense__and_Late_Interaction_Pipelines1.pdf"),
    ("ChunkRAG pages 3-5", r"C:\Users\xiao\Downloads\切块算法\ChunkRAG Novel LLM-Chunk Filtering Method for RAG Systems.pdf"),
    ("MAQ-retrieval pages 3-6", r"C:\Users\xiao\Downloads\切块算法\Xu 等 - 2026 - MAQ-retrieval multi-aspect queries retrieval for large language models.pdf"),
    ("SYNAPSE", r"C:\Users\xiao\Downloads\捕鱼算法\SYNAPSE Empowering LLM Agents with Episodic-Semantic Memory via Spreading Activation.pdf"),
    ("KET-RAG", r"C:\Users\xiao\Downloads\捕鱼算法\KET-RAG A Cost-Efficient Multi-Granular Indexing Framework for Graph-RAG.pdf"),
]

for name, path in papers:
    print(f"\n{'='*60}")
    print(f"PAPER: {name}")
    print('='*60)
    try:
        doc = fitz.open(path)
        total_pages = len(doc)
        print(f"Total pages: {total_pages}")
        # For each paper, read pages 1-5 and last page
        pages_to_read = list(range(min(5, total_pages)))
        for i in pages_to_read:
            try:
                text = doc[i].get_text()
                # Replace problematic chars
                text = text.encode('ascii', errors='replace').decode('ascii')
                print(f"\n--- Page {i+1} ---")
                print(text[:3000])
            except Exception as e:
                print(f"Page {i+1} error: {e}")
    except Exception as e:
        print(f"ERROR: {e}")
