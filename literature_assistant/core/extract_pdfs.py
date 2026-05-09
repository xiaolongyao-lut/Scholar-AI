import fitz
import os
from concurrent.futures import ThreadPoolExecutor

papers = [
    ("MAQ-retrieval", r"C:\Users\xiao\Downloads\切块算法\Xu 等 - 2026 - MAQ-retrieval multi-aspect queries retrieval for large language models.pdf"),
    ("Structure-Aware Chunking", r"C:\Users\xiao\Downloads\切块算法\Structure-Aware Chunking for Complex Tables in Retrieval-Augmented Generation Systems.pdf"),
    ("ChunkRAG", r"C:\Users\xiao\Downloads\切块算法\ChunkRAG Novel LLM-Chunk Filtering Method for RAG Systems.pdf"),
    ("Financial Report Chunking", r"C:\Users\xiao\Downloads\切块算法\Financial Report Chunking for Effective Retrieval Augmented Generation.pdf"),
    ("Evaluating Modern RAG", r"C:\Users\xiao\Downloads\切块算法\Evaluating_Modern_RAG__Textual__Multimodal__Dense__and_Late_Interaction_Pipelines1.pdf"),
    ("DMG-RAG", r"C:\Users\xiao\Downloads\切块算法\DMG-RAG Dynamic Multi-Grained Retrieval Augmented Generation for Multi-Hop QA.pdf"),
    ("Is Semantic Chunking Worth", r"C:\Users\xiao\Downloads\切块算法\Is Semantic Chunking Worth the Computational Cost.pdf"),
    ("Dense X Retrieval", r"C:\Users\xiao\Downloads\切块算法\Dense X Retrieval What Retrieval Granularity Should We Use.pdf"),
    ("Reconstructing Context", r"C:\Users\xiao\Downloads\切块算法\Reconstructing_Context_Evaluating_Advanced_Chunkin.pdf"),
    ("Benchmarking Legal RAG", r"C:\Users\xiao\Downloads\切块算法\Benchmarking Legal RAG The Promise and Limits of AI Statutory Surveys.pdf"),
    ("SYNAPSE", r"C:\Users\xiao\Downloads\捕鱼算法\SYNAPSE Empowering LLM Agents with Episodic-Semantic Memory via Spreading Activation.pdf"),
    ("KET-RAG", r"C:\Users\xiao\Downloads\捕鱼算法\KET-RAG A Cost-Efficient Multi-Granular Indexing Framework for Graph-RAG.pdf"),
]


def process_paper(name_and_path):
    """Process a single paper (extract text from key pages)."""
    name, path = name_and_path
    
    print(f"\n{'='*60}")
    print(f"PAPER: {name}")
    print('='*60)
    
    if not os.path.exists(path):
        print(f"FILE NOT FOUND: {path}")
        return
    
    try:
        doc = fitz.open(path)
        total_pages = len(doc)
        print(f"Total pages: {total_pages}")
        
        pages_to_read = list(range(min(4, total_pages)))
        if total_pages > 4:
            pages_to_read.append(total_pages - 1)
        
        for i in pages_to_read:
            text = doc[i].get_text()
            print(f"\n--- Page {i+1} ---")
            print(text[:2000])
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        executor.map(process_paper, papers)
