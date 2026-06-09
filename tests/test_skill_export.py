"""Test J11: Skill export endpoint (2026-05-26).

Verify POST /skills/{skill_id}/export creates zip archive.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import zipfile

import pytest
from fastapi.testclient import TestClient

# Add literature_assistant/core to sys.path
core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

from python_adapter_server import app


@pytest.fixture
def client():
    """TestClient for API testing."""
    return TestClient(app)


@pytest.fixture
def mock_skill_service():
    """Mock WritingSkillService for testing."""
    with patch("routers.skills_router.get_skill_service") as mock_get:
        service = MagicMock()
        mock_get.return_value = service
        yield service


class TestSkillExport:
    """J11: Skill export endpoint."""

    def test_export_success(self, client, mock_skill_service, tmp_path):
        """Successful export returns export_path."""
        export_path = tmp_path / "test_skill.zip"
        mock_skill_service.export_user_skill.return_value = {
            "success": True,
            "skill_id": "test_skill",
            "export_path": str(export_path),
            "errors": [],
        }

        resp = client.post("/skills/test_skill/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["skill_id"] == "test_skill"
        assert data["export_path"] == str(export_path)
        assert data["errors"] == []

    def test_export_with_custom_output_path(self, client, mock_skill_service, tmp_path):
        """Export with custom output filename passes to service."""
        custom_path = "custom_export.zip"
        mock_skill_service.export_user_skill.return_value = {
            "success": True,
            "skill_id": "test_skill",
            "export_path": str(custom_path),
            "errors": [],
        }

        resp = client.post(f"/skills/test_skill/export?output_path={custom_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["export_path"] == str(custom_path)

        # Verify service was called with custom path
        mock_skill_service.export_user_skill.assert_called_once_with(
            "test_skill", output_path=custom_path
        )

    def test_export_skill_not_found(self, client, mock_skill_service):
        """Export non-existent skill returns 404."""
        mock_skill_service.export_user_skill.side_effect = ValueError("Skill not found: nonexistent")

        resp = client.post("/skills/nonexistent/export")
        assert resp.status_code == 404

    def test_export_builtin_skill_rejected(self, client, mock_skill_service):
        """Export builtin skill returns 400."""
        mock_skill_service.export_user_skill.side_effect = ValueError(
            "Cannot export builtin skill: builtin_skill"
        )

        resp = client.post("/skills/builtin_skill/export")
        assert resp.status_code == 400

    def test_export_service_failure_returns_500(self, client, mock_skill_service):
        """Export service failure returns 500."""
        mock_skill_service.export_user_skill.return_value = {
            "success": False,
            "skill_id": "test_skill",
            "export_path": "",
            "errors": ["Export failed: permission denied"],
        }

        resp = client.post("/skills/test_skill/export")
        assert resp.status_code == 500


class TestSkillExportService:
    """J11: WritingSkillService.export_user_skill method."""

    def test_export_creates_zip_archive(self, tmp_path):
        """export_user_skill creates valid zip archive."""
        from skills.service import WritingSkillService
        from skills.models import SkillDescriptor, SkillSource, SkillKind, UIVisibility

        # Create test skill directory
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill")
        (skill_dir / "script.py").write_text("print('test')")
        subdir = skill_dir / "subdir"
        subdir.mkdir()
        (subdir / "data.txt").write_text("test data")

        # Create service with mock registry
        service = WritingSkillService(managed_root=tmp_path)
        descriptor = SkillDescriptor(
            id="test_skill",
            name="Test Skill",
            description="Test skill for export",
            kind=SkillKind.TRANSFORM,
            source=SkillSource.IMPORTED,
            entry_mode="manual",
            supported_scopes=["selection"],
            ui_visibility=UIVisibility.BOTH,
            requires_assets=False,
            default_parameters={"installed_path": str(skill_dir)},
        )
        service._registry.register(descriptor)

        # Export
        export_root = tmp_path / "exports"
        export_path = export_root / "skill_exports" / "test_skill.zip"
        with patch("skills.service.WORKSPACE_ARTIFACTS_ROOT", export_root):
            result = service.export_user_skill("test_skill", output_path="test_skill.zip")

        assert result["success"] is True
        assert result["skill_id"] == "test_skill"
        assert result["export_path"] == str(export_path)
        assert result["errors"] == []

        # Verify zip contents
        assert export_path.exists()
        with zipfile.ZipFile(export_path, "r") as zf:
            names = zf.namelist()
            assert "SKILL.md" in names
            assert "script.py" in names
            assert "subdir/data.txt" in names

            # Verify content
            assert zf.read("SKILL.md").decode() == "# Test Skill"
            assert zf.read("script.py").decode() == "print('test')"
            assert zf.read("subdir/data.txt").decode() == "test data"

    def test_export_default_output_path(self, tmp_path):
        """export_user_skill defaults to workspace_artifacts/skill_exports/{skill_id}.zip."""
        from skills.service import WritingSkillService
        from skills.models import SkillDescriptor, SkillSource, SkillKind, UIVisibility

        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test")

        service = WritingSkillService(managed_root=tmp_path)
        descriptor = SkillDescriptor(
            id="test_skill",
            name="Test Skill",
            description="Test skill",
            kind=SkillKind.TRANSFORM,
            source=SkillSource.IMPORTED,
            entry_mode="manual",
            supported_scopes=["selection"],
            ui_visibility=UIVisibility.BOTH,
            requires_assets=False,
            default_parameters={"installed_path": str(skill_dir)},
        )
        service._registry.register(descriptor)

        with patch("skills.service.WORKSPACE_ARTIFACTS_ROOT", tmp_path):
            result = service.export_user_skill("test_skill")

        assert result["success"] is True
        export_path = Path(result["export_path"])
        assert export_path.name == "test_skill.zip"
        assert "skill_exports" in str(export_path)
        assert export_path.exists()

    def test_export_builtin_skill_raises_error(self, tmp_path):
        """export_user_skill raises ValueError for builtin skills."""
        from skills.service import WritingSkillService
        from skills.models import SkillDescriptor, SkillSource, SkillKind, UIVisibility

        service = WritingSkillService(managed_root=tmp_path)
        descriptor = SkillDescriptor(
            id="builtin_skill",
            name="Builtin Skill",
            description="Builtin skill",
            kind=SkillKind.TRANSFORM,
            source=SkillSource.BUILTIN,
            entry_mode="manual",
            supported_scopes=["selection"],
            ui_visibility=UIVisibility.BOTH,
            requires_assets=False,
            default_parameters={"installed_path": str(tmp_path / "builtin")},
        )
        service._registry.register(descriptor)

        with pytest.raises(ValueError, match="Cannot export builtin skill"):
            service.export_user_skill("builtin_skill")

    def test_export_nonexistent_skill_raises_error(self, tmp_path):
        """export_user_skill raises ValueError for non-existent skill."""
        from skills.service import WritingSkillService

        service = WritingSkillService(managed_root=tmp_path)

        with pytest.raises(ValueError, match="Skill not found"):
            service.export_user_skill("nonexistent")

    def test_export_rejects_path_traversal_output_path(self, tmp_path):
        """export_user_skill keeps custom output filenames under skill_exports."""
        from skills.service import WritingSkillService
        from skills.models import SkillDescriptor, SkillSource, SkillKind, UIVisibility

        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test", encoding="utf-8")

        service = WritingSkillService(managed_root=tmp_path)
        descriptor = SkillDescriptor(
            id="test_skill",
            name="Test Skill",
            description="Test skill",
            kind=SkillKind.TRANSFORM,
            source=SkillSource.IMPORTED,
            entry_mode="manual",
            supported_scopes=["selection"],
            ui_visibility=UIVisibility.BOTH,
            requires_assets=False,
            default_parameters={"installed_path": str(skill_dir)},
        )
        service._registry.register(descriptor)

        with patch("skills.service.WORKSPACE_ARTIFACTS_ROOT", tmp_path), pytest.raises(
            ValueError,
            match="filename under skill_exports",
        ):
            service.export_user_skill("test_skill", output_path="../escape.zip")
