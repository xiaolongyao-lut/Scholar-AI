# Quick Start v3

This guide covers the current duty-driven entrypoints for the classic pipeline path. For the RAG assistant path, start with [README.md](/C:/Users/xiao/Desktop/tools/Modular-Pipeline-Script/README.md) and use `rag_integration_entry.py`.

## Prerequisites

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe -m pip install -r requirements-ci.txt
```

Optional environment variables:

```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:ARK_API_KEY = "..."
```

## Scenario 1: Process One PDF

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\integrated_pipeline.py .\sample.pdf `
  --goal "提取工艺参数、关键证据和可复用结论" `
  --out .\output
```

Expected output under `output\sample\`:

- `01_full_extract.json`
- `02_hybrid_retrieval.json`
- `03_academic_scoring.json`
- `sample_report.docx`

## Scenario 2: Batch Processing

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\batch_controller.py .\test_pdfs `
  --goal "按研究问题整理证据并生成批处理卷" `
  --out .\batch_result `
  --batch-size 13 `
  --pipeline .\integrated_pipeline.py `
  --volume-script .\volume_merger.py
```

Expected output:

- `batch_result\batch_<timestamp>\paper_<n>\`
- `batch_result\volume_V01\volume_bundle_V01.json`
- `batch_result\volume_V01\volume_stats_V01.json`
- `batch_result\batch_logs\batch_report_<timestamp>.json`

## Scenario 3: Merge Existing Material Packs

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\volume_merger.py `
  --inputs .\batch_result\batch_20260412_100000\paper_a\02_writing_material_pack.json `
           .\batch_result\batch_20260412_100000\paper_b\02_writing_material_pack.json `
  --output-json .\batch_result\volume_V99\volume_bundle_V99.json `
  --volume-id V99
```

## Scenario 4: Generate a Word Document From a Material Pack

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\word_generator.py `
  .\batch_result\batch_20260412_100000\paper_a\02_writing_material_pack.json `
  .\output\paper_a.docx
```

## Scenario 5: Use the RAG Assistant

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\rag_integration_entry.py ask "总结这批文献关于激光功率的共同结论"
```

## Output Guide

- `01_full_extract.json`: multimodal extraction result for one PDF
- `02_hybrid_retrieval.json`: retrieval hits, focus points, and hybrid scores
- `03_academic_scoring.json`: evidence scoring result and project view
- `*_report.docx`: Word report generated from the presentation layer
- `volume_bundle_*.json`: merged writing material packs for a batch
- `volume_stats_*.json`: merged statistics for the current volume

## Validation

```powershell
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\integrated_pipeline.py --help
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\batch_controller.py --help
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\word_generator.py --help

c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe -m pytest -q `
  .\test_writing_resources.py `
  .\test_pipeline_router_association.py `
  .\test_ragflow_integration.py `
  .\test_workflow_analysis_integration.py `
  .\test_word_docx_smoke.py
```

## Troubleshooting

- If `integrated_pipeline.py` exits during import, verify the virtual environment is active and the `layers\` directory is intact.
- If Word generation fails, ensure `python-docx` is installed through `requirements-ci.txt`.
- If batch processing cannot find PDFs, make sure the input directory contains `.pdf` files directly rather than nested folders.
- If you only need the RAG assistant workflow, use `rag_integration_entry.py` and skip the classic pipeline entrypoints.
