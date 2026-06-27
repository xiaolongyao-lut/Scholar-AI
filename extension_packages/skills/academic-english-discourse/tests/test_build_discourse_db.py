from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from literature_assistant.core import academic_english_resources


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "extension_packages" / "skills" / "academic-english-discourse"
SCRIPT_PATH = PACKAGE_ROOT / "scripts" / "build_discourse_db.py"


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("academic_english_discourse_builder", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_skill_manifest_validates_against_scholar_ai_contract() -> None:
    sys.path.insert(0, str(REPO_ROOT / "literature_assistant" / "core"))
    from skills.user_manifest import parse_skill_md_frontmatter, validate_manifest

    content = (PACKAGE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = parse_skill_md_frontmatter(content)
    manifest = validate_manifest(frontmatter)

    assert manifest.id == "academic-english-discourse"
    assert manifest.kind == "style"
    assert manifest.effective_permission("model.llm") is True
    assert manifest.script_policy["has_scripts"] is True


def test_builder_writes_jsonl_sqlite_and_manifest_from_synthetic_sources(tmp_path: Path) -> None:
    builder = _load_builder()
    text_source = tmp_path / "mini_review.txt"
    text_source.write_text(
        (
            "Research on retrieval-augmented writing has increasingly focused on "
            "evidence-grounded drafting. However, little is known about how bilingual "
            "writers preserve hedging during translation. This study examines sentence "
            "revision patterns and suggests that explicit discourse moves may improve "
            "literature review coherence."
        ),
        encoding="utf-8",
    )
    html_dir = tmp_path / "phrasebank"
    html_dir.mkdir()
    (html_dir / "introducing-work.html").write_text(
        """
        <html><head><title>Introducing work</title></head><body>
        <main>
          <h1>Introducing work</h1>
          <h2>Establishing a territory</h2>
          <p>Research on X has increasingly focused on Y.</p>
          <h2>Indicating a gap</h2>
          <ul><li>However, little is known about Z.</li></ul>
        </main>
        </body></html>
        """,
        encoding="utf-8",
    )
    output_dir = tmp_path / "english_discourse"

    exit_code = builder.main(
        [
            "--text",
            str(text_source),
            "--phrasebank-html-dir",
            str(html_dir),
            "--output-dir",
            str(output_dir),
            "--chunk-size",
            "220",
            "--chunk-overlap",
            "40",
        ]
    )

    assert exit_code == 0
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["chunks"] >= 2
    assert manifest["counts"]["phrases"] >= 2
    assert manifest["counts"]["habit_principles"] >= 6
    assert Path(manifest["outputs"]["sqlite"]).exists()
    assert Path(manifest["outputs"]["academic_english_habits_json"]).exists()
    assert manifest["write_counts"]["chunks"] == manifest["counts"]["chunks"]
    assert manifest["write_counts"]["phrases"] == manifest["counts"]["phrases"]

    knowledge_source = manifest["knowledge_sources"]["academic_english_habits"]
    assert knowledge_source["loaded"] is True
    assert knowledge_source["load_status"] == "loaded"
    assert knowledge_source["source_label"].endswith("english_discourse_habits.md")
    assert knowledge_source["source_path"].endswith("english_discourse_habits.md")
    assert len(knowledge_source["content_hash"]) == 64
    assert knowledge_source["char_count"] > 0

    output_artifacts = manifest["output_artifacts"]
    assert output_artifacts["chunks_jsonl"]["rows"] == manifest["counts"]["chunks"]
    assert output_artifacts["phrases_jsonl"]["rows"] == manifest["counts"]["phrases"]
    assert output_artifacts["chunks_jsonl"]["sha256"] == hashlib.sha256((output_dir / "chunks.jsonl").read_bytes()).hexdigest()
    assert output_artifacts["academic_english_habits_json"]["exists"] is True
    assert len(output_artifacts["academic_english_habits_json"]["sha256"]) == 64
    assert output_artifacts["sqlite"]["exists"] is True
    assert len(output_artifacts["report"]["sha256"]) == 64

    chunk_records = [
        json.loads(line)
        for line in (output_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    phrase_records = [
        json.loads(line)
        for line in (output_dir / "phrases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert any("gap" in record["rhetorical_moves"] for record in chunk_records)
    assert any(record["move"] in {"territory", "gap"} for record in phrase_records)
    assert all("chunk_id" in record and "summary" in record for record in chunk_records)
    review_source_ids = {record["source_id"] for record in chunk_records if record["source_path"] == "source:mini_review.txt"}
    assert len(review_source_ids) == 1
    review_source_id = review_source_ids.pop()
    review_chunks = [record for record in chunk_records if record["source_id"] == review_source_id]
    assert review_chunks
    assert all(record["source_path"] == "source:mini_review.txt" for record in review_chunks)
    assert all(len(record["source_hash"]) == 64 for record in chunk_records)
    assert all(len(record["content_hash"]) == 64 for record in chunk_records)
    assert all(record["span_end"] > record["span_start"] for record in chunk_records)
    review_phrases = [record for record in phrase_records if record["source_id"] == review_source_id]
    assert review_phrases
    assert all(record["source_path"] == "source:mini_review.txt" for record in review_phrases)
    assert all(len(record["source_hash"]) == 64 for record in phrase_records)
    assert all(len(record["content_hash"]) == 64 for record in phrase_records)
    assert all(record["span_end"] > record["span_start"] for record in phrase_records)
    assert len(manifest["sources"][0]["source_hash"]) == 64

    habits = json.loads((output_dir / "academic_english_habits.json").read_text(encoding="utf-8"))
    assert habits["knowledge_type"] == "academic_english_habits"
    assert habits["policy_loaded"] is True
    assert "Academic English Discourse Habits" in habits["policy_markdown"]
    assert habits["policy_source"].endswith("english_discourse_habits.md")
    assert habits["policy_source_path"].endswith("english_discourse_habits.md")
    assert habits["policy_load_status"] == "loaded"
    assert len(habits["policy_content_hash"]) == 64
    assert habits["policy_content_hash"] == hashlib.sha256(habits["policy_markdown"].encode("utf-8")).hexdigest()
    assert habits["policy_char_count"] == len(habits["policy_markdown"])
    assert any(item["name"] == "old_to_new_information" for item in habits["source_principles"])
    assert "literature_review_synthesis" in {item["name"] for item in habits["paragraph_protocols"]}


def test_habits_embeds_policy_markdown() -> None:
    builder = _load_builder()

    habits = builder.academic_english_habits()

    assert habits["policy_loaded"] is True
    assert "Academic English Discourse Habits" in habits["policy_markdown"]
    assert habits["policy_source"].endswith("english_discourse_habits.md")
    assert habits["policy_source_path"].endswith("english_discourse_habits.md")
    assert habits["policy_load_status"] == "loaded"
    assert len(habits["policy_content_hash"]) == 64
    assert habits["policy_char_count"] == len(habits["policy_markdown"])


def test_habits_degrades_when_policy_markdown_is_missing(monkeypatch, tmp_path: Path) -> None:
    builder = _load_builder()
    missing_policy = tmp_path / "missing" / "english_discourse_habits.md"

    monkeypatch.setattr(builder, "_habit_policy_path", lambda: missing_policy)

    habits = builder.academic_english_habits()

    assert habits["policy_loaded"] is False
    assert habits["policy_markdown"] == ""
    assert habits["policy_source"] == ""
    assert habits["policy_source_path"] == str(missing_policy)
    assert habits["policy_load_status"] == "missing"
    assert habits["policy_content_hash"] == ""
    assert habits["policy_char_count"] == 0


def test_builder_records_warning_when_policy_markdown_is_missing(monkeypatch, tmp_path: Path) -> None:
    builder = _load_builder()
    missing_policy = tmp_path / "missing" / "english_discourse_habits.md"
    text_source = tmp_path / "mini_review.txt"
    text_source.write_text(
        "Research on bilingual writing remains limited. This study examines translation revision.",
        encoding="utf-8",
    )
    output_dir = tmp_path / "english_discourse"

    monkeypatch.setattr(builder, "_habit_policy_path", lambda: missing_policy)

    manifest = builder.build_database(
        builder.parse_args(
            [
                "--text",
                str(text_source),
                "--output-dir",
                str(output_dir),
                "--chunk-size",
                "220",
                "--chunk-overlap",
                "40",
                "--no-sqlite",
            ]
        )
    )

    assert "english_discourse_habits.md missing; policy_markdown is empty" in manifest["warnings"]
    knowledge_source = manifest["knowledge_sources"]["academic_english_habits"]
    assert knowledge_source["loaded"] is False
    assert knowledge_source["load_status"] == "missing"
    assert knowledge_source["source_path"] == str(missing_policy)
    assert knowledge_source["content_hash"] == ""
    assert manifest["output_artifacts"]["sqlite"]["status"] == "disabled"
    assert manifest["output_artifacts"]["sqlite"]["exists"] is False
    habits = json.loads((output_dir / "academic_english_habits.json").read_text(encoding="utf-8"))
    assert habits["policy_loaded"] is False
    assert habits["policy_load_status"] == "missing"


def test_built_artifact_is_consumed_by_runtime_search_and_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    builder = _load_builder()
    text_source = tmp_path / "mini_review.txt"
    text_source.write_text(
        (
            "Research on retrieval-augmented writing has increasingly focused on evidence-grounded drafting. "
            "However, little is known about how bilingual writers preserve hedging during translation."
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "english_discourse"

    exit_code = builder.main(
        [
            "--text",
            str(text_source),
            "--output-dir",
            str(output_dir),
            "--chunk-size",
            "220",
            "--chunk-overlap",
            "40",
        ]
    )

    assert exit_code == 0
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))

    results = academic_english_resources.search_academic_english("hedging", top_k=3)
    assert results
    first = results[0]
    assert first["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-academic-english-knowledge-ref/v1"
    assert first["metadata"]["source"] == "academic_english"
    assert first["metadata"]["source_path"] == "source:mini_review.txt"
    assert len(first["metadata"]["source_hash"]) == 64
    assert len(first["metadata"]["content_hash"]) == 64
    assert first["metadata"]["span_end"] > first["metadata"]["span_start"]

    resource = academic_english_resources.read_academic_english_resource(first["ref_id"].split("academic_english:", 1)[1])
    assert resource["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-academic-english-knowledge-ref/v1"
    assert resource["metadata"]["source"] == "academic_english"
    assert resource["metadata"]["source_path"] == "source:mini_review.txt"
    assert resource["metadata"]["content_hash"] == first["metadata"]["content_hash"]
    assert resource["metadata"]["source_hash"] == first["metadata"]["source_hash"]
    assert resource["metadata"]["source_path"] == first["metadata"]["source_path"]
    assert resource["metadata"]["span_start"] == first["metadata"]["span_start"]
    assert resource["metadata"]["span_end"] == first["metadata"]["span_end"]
    assert "evidence-grounded drafting" in resource["content"]


def test_extract_pdf_runs_ocr_only_after_empty_text_layer(monkeypatch, tmp_path: Path) -> None:
    builder = _load_builder()
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% synthetic placeholder\n")
    ocr_doc = builder.SourceDocument(
        source_id="ocr_pdf_test",
        source_type="ocr_pdf",
        title="scan",
        locator="scan.pdf#ocr-page=1",
        section="ocr page 1",
        text="Writing science in plain English.",
        origin_path=str(pdf_path),
    )

    monkeypatch.setattr(builder, "_extract_pdf_with_pymupdf", lambda _path: [])
    monkeypatch.setattr(builder, "_extract_pdf_with_windows_ocr", lambda *args, **kwargs: [ocr_doc])

    extracted = builder.extract_pdf(
        pdf_path,
        ocr_engine="windows",
        ocr_output_dir=tmp_path / "ocr_pages",
        ocr_language="en-GB",
        ocr_scale=2.0,
    )

    assert extracted == [ocr_doc]


def test_extract_pdf_auto_uses_core_ocr_engine_selection(monkeypatch, tmp_path: Path) -> None:
    builder = _load_builder()
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% synthetic placeholder\n")
    ocr_doc = builder.SourceDocument(
        source_id="ocr_pdf_core",
        source_type="ocr_pdf",
        title="scan",
        locator="scan.pdf#ocr-page=1",
        section="ocr page 1",
        text="Shared OCR engine output.",
        origin_path=str(pdf_path),
    )
    calls: dict[str, object] = {}

    class _FakeEngine:
        name = "fake"
        display_name = "Fake OCR"
        engine_type = "local"
        requires_network = False

        def is_available(self) -> bool:
            return True

        def unavailable_reason(self) -> str | None:
            return None

        def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
            if not isinstance(image, (bytes, Path)):
                raise TypeError("image must be bytes or pathlib.Path")
            return f"fake text {language}"

    fake_engine = _FakeEngine()

    def _fake_select_ocr_engine(config):
        calls["policy"] = config.policy
        calls["language"] = config.language
        calls["engine"] = config.engine
        return fake_engine, None

    def _fake_extract_with_engine(path, *, ocr_output_dir, language_tag, scale, engine):
        calls["path"] = path
        calls["ocr_output_dir"] = ocr_output_dir
        calls["language_tag"] = language_tag
        calls["scale"] = scale
        calls["engine_object"] = engine
        return [ocr_doc]

    monkeypatch.setattr(builder, "_extract_pdf_with_pymupdf", lambda _path: [])
    monkeypatch.setattr(builder, "select_ocr_engine", _fake_select_ocr_engine)
    monkeypatch.setattr(builder, "_extract_pdf_with_ocr_engine", _fake_extract_with_engine)

    extracted = builder.extract_pdf(
        pdf_path,
        ocr_engine="auto",
        ocr_output_dir=tmp_path / "ocr_pages",
        ocr_language="en-GB",
        ocr_scale=2.0,
    )

    assert extracted == [ocr_doc]
    assert calls["policy"] == "auto"
    assert calls["language"] == "en-GB"
    assert calls["engine"] is None
    assert calls["path"] == pdf_path
    assert calls["engine_object"] is fake_engine
