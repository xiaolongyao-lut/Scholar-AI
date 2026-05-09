import pytest
import json
import tempfile
from pathlib import Path
from batch_controller import BatchProcessController

MINIMAL_PDF_CONTENT = b"""%PDF-1.4
1 0 obj
<</Type/Catalog/Pages 2 0 R>>
endobj
2 0 obj
<</Type/Pages/Count 1/Kids[3 0 R]>>
endobj
3 0 obj
<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>
endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000052 00000 n
0000000101 00000 n
trailer
<</Size 4/Root 1 0 R>>
startxref
178
%%EOF
"""

@pytest.fixture
def smoke_test_pdfs(tmp_path):
    """Provide 2-3 minimal PDF files for smoke testing."""
    fixture_dir = tmp_path / "smoke_pdfs"
    fixture_dir.mkdir()
    
    # PDF 1
    (fixture_dir / "test_doc_1.pdf").write_bytes(MINIMAL_PDF_CONTENT)
    # PDF 2 (special characters with trailing dot which was a bug)
    (fixture_dir / "test_doc_2_中文....pdf").write_bytes(MINIMAL_PDF_CONTENT)
    
    return fixture_dir

@pytest.fixture
def batch_output_dir(tmp_path):
    """Temp directory for batch output."""
    out_dir = tmp_path / "batch_output"
    out_dir.mkdir()
    return out_dir

def test_batch_controller_runs_without_error(smoke_test_pdfs, batch_output_dir):
    """Smoke test: BatchProcessController can process PDF smoke samples."""
    controller = BatchProcessController(str(smoke_test_pdfs), str(batch_output_dir), "Test Goal")
    result = controller.process_batch()
    
    assert result["status"] == "completed"
    assert result["successful_pdfs"] == result["total_pdfs"]
    assert result["failed_pdfs"] == 0

def test_material_pack_generated_for_each_pdf(smoke_test_pdfs, batch_output_dir):
    """Smoke test: Each PDF produces 02_writing_material_pack.json."""
    controller = BatchProcessController(str(smoke_test_pdfs), str(batch_output_dir), "Test Goal")
    controller.process_batch()
    
    batch_dirs = list(batch_output_dir.glob("batch_[0-9]*"))
    assert batch_dirs, "Batch output directory not created"
    
    batch_dir = batch_dirs[0]
    # We expect 2 output directories for the 2 pdfs
    pdf_dirs = [d for d in batch_dir.iterdir() if d.is_dir()]
    assert len(pdf_dirs) == 2
    
    for pdf_dir in pdf_dirs:
        material_pack = pdf_dir / "02_writing_material_pack.json"
        assert material_pack.exists(), f"Missing material pack in {pdf_dir}"
        
        with open(material_pack, 'r', encoding='utf-8') as f:
            pack = json.load(f)
            assert "writing_point_cards" in pack
            assert "llm_status" in pack

def test_volume_merge_succeeds(smoke_test_pdfs, batch_output_dir):
    """Smoke test: Volume merge (K-layer aggregation) completes."""
    # Force batch_size to 1 so that we get multiple volumes or at least one triggered
    controller = BatchProcessController(str(smoke_test_pdfs), str(batch_output_dir), "Test Goal", batch_size=1)
    result = controller.process_batch()
    
    assert result["volumes_created"] >= 1
    volume_dir = batch_output_dir / "volume_V01"
    assert volume_dir.exists(), "Volume V01 directory not correctly generated"
    assert (volume_dir / "volume_bundle_V01.json").exists(), "Volume bundle JSON missing"

def test_no_llm_mode_still_succeeds(smoke_test_pdfs, batch_output_dir):
    """Smoke test: Pipeline works even when enable_llm=False."""
    controller = BatchProcessController(str(smoke_test_pdfs), str(batch_output_dir), "Test Goal", enable_llm=False)
    result = controller.process_batch()
    
    assert result["status"] == "completed"
    assert result["successful_pdfs"] == result["total_pdfs"]
