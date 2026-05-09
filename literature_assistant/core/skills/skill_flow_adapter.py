# -*- coding: utf-8 -*-
"""Skill Flow export adapter for repo-local SKILL.md catalogs."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from datetime_utils import utc_now_iso_z

try:
    from skills.models import SkillDescriptor
    from skills.user_manifest import parse_skill_md_frontmatter
except ImportError:  # pragma: no cover - package import fallback
    from .models import SkillDescriptor
    from .user_manifest import parse_skill_md_frontmatter


_SLUG_PART_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ExportedSkillRecord:
    """One exported skill entry in the catalog summary."""

    slug: str
    name: str
    origin: str
    source_locator: str
    output_path: str
    description: str = ""


@dataclass(frozen=True)
class SyncReport:
    """Result of one adapter sync run."""

    exported: list[ExportedSkillRecord]
    summary_path: str | None = None


def _normalize_slug(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    text = text.replace("_", "-")
    text = _SLUG_PART_RE.sub("-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        raise ValueError("Cannot derive skill slug from empty value")
    return text


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_scalar(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_metadata_block(descriptor: SkillDescriptor) -> str:
    scopes = ", ".join(descriptor.supported_scopes) or "none"
    tags = ", ".join(descriptor.tags) or "none"
    compatibility = descriptor.compatibility.fallback_action_id or "none"
    return "\n".join(
        [
            f"- Version: {descriptor.version}",
            f"- Kind: {descriptor.kind.value}",
            f"- Source: {descriptor.source.value}",
            f"- Entry mode: {descriptor.entry_mode}",
            f"- Supported scopes: {scopes}",
            f"- Tags: {tags}",
            f"- Trust level: {descriptor.trust_level.value}",
            f"- Compatibility fallback: {compatibility}",
        ]
    )


def _render_descriptor_markdown(template_text: str, descriptor: SkillDescriptor) -> tuple[str, str]:
    slug = _normalize_slug(descriptor.id or descriptor.name)
    replacements = {
        "{{frontmatter_name}}": _quoted(slug),
        "{{frontmatter_description}}": _quoted(descriptor.description),
        "{{frontmatter_version}}": _quoted(descriptor.version),
        "{{frontmatter_kind}}": _quoted(descriptor.kind.value),
        "{{frontmatter_source}}": _quoted(descriptor.source.value),
        "{{frontmatter_entry_mode}}": _quoted(descriptor.entry_mode),
        "{{frontmatter_ui_visibility}}": _quoted(descriptor.ui_visibility.value),
        "{{frontmatter_display_group}}": _quoted(descriptor.display_group),
        "{{frontmatter_tags}}": _json_scalar(descriptor.tags),
        "{{frontmatter_supported_scopes}}": _json_scalar(descriptor.supported_scopes),
        "{{frontmatter_requires_assets}}": _json_scalar(descriptor.requires_assets),
        "{{frontmatter_safe_to_execute}}": _json_scalar(descriptor.safe_to_execute),
        "{{frontmatter_experimental}}": _json_scalar(descriptor.experimental),
        "{{frontmatter_trust_level}}": _quoted(descriptor.trust_level.value),
        "{{title}}": descriptor.name,
        "{{description}}": descriptor.description,
        "{{summary_block}}": (
            f"{descriptor.summary_hint}\n\n" if descriptor.summary_hint else ""
        ),
        "{{metadata_block}}": _render_metadata_block(descriptor),
    }

    rendered = template_text
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return slug, rendered


class SkillFlowAdapter:
    """Export descriptors and mirror repo-local SKILL.md documents into a catalog."""

    def __init__(self, source_root: Path, output_root: Path, template_path: Path) -> None:
        self.source_root = Path(source_root)
        self.output_root = Path(output_root)
        self.template_path = Path(template_path)

    def _load_template(self) -> str:
        return self.template_path.read_text(encoding="utf-8")

    def _iter_existing_skill_docs(self) -> list[Path]:
        docs: list[Path] = []
        output_root_resolved = self.output_root.resolve()
        if not self.source_root.exists():
            return docs
        for skill_md in sorted(self.source_root.rglob("SKILL.md")):
            try:
                if skill_md.resolve().is_relative_to(output_root_resolved):
                    continue
            except ValueError:
                pass
            docs.append(skill_md)
        return docs

    def _write_summary(self, records: list[ExportedSkillRecord], summary_path: Path) -> None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": utc_now_iso_z(),
            "exported_count": len(records),
            "exported": [asdict(record) for record in records],
        }
        summary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def sync(
        self,
        descriptors: Iterable[SkillDescriptor],
        *,
        mirror_existing: bool = False,
        summary_path: Path | None = None,
        strict: bool = False,
    ) -> SyncReport:
        template_text = self._load_template()
        self.output_root.mkdir(parents=True, exist_ok=True)

        exported: list[ExportedSkillRecord] = []
        seen_slugs: set[str] = set()

        for descriptor in descriptors:
            slug, rendered = _render_descriptor_markdown(template_text, descriptor)
            if slug in seen_slugs:
                raise ValueError(f"Duplicate skill slug: {slug}")
            seen_slugs.add(slug)

            destination = self.output_root / slug / "SKILL.md"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
            exported.append(
                ExportedSkillRecord(
                    slug=slug,
                    name=slug,
                    origin="descriptor",
                    source_locator=descriptor.id,
                    output_path=str(destination),
                    description=descriptor.description,
                )
            )

        if mirror_existing:
            for skill_md in self._iter_existing_skill_docs():
                content = skill_md.read_text(encoding="utf-8")
                frontmatter = parse_skill_md_frontmatter(content)
                if strict and not frontmatter:
                    raise ValueError(f"Strict mode requires frontmatter in {skill_md}")

                source_name = str(frontmatter.get("name") or skill_md.parent.name)
                slug = _normalize_slug(source_name)
                if slug in seen_slugs:
                    raise ValueError(f"Duplicate skill slug: {slug}")
                seen_slugs.add(slug)

                destination = self.output_root / slug / "SKILL.md"
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(skill_md, destination)
                exported.append(
                    ExportedSkillRecord(
                        slug=slug,
                        name=str(frontmatter.get("name") or slug),
                        origin="existing",
                        source_locator=str(skill_md),
                        output_path=str(destination),
                        description=str(frontmatter.get("description") or ""),
                    )
                )

        if summary_path is not None:
            self._write_summary(exported, Path(summary_path))

        return SyncReport(
            exported=exported,
            summary_path=str(summary_path) if summary_path is not None else None,
        )


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def build_arg_parser() -> argparse.ArgumentParser:
    repo_root = _default_repo_root()
    parser = argparse.ArgumentParser(description="Export repo-local SKILL.md entries into a local skill-flow catalog.")
    parser.add_argument("--source-root", default=str(repo_root / ".github" / "skills"))
    parser.add_argument("--output-root", default=str(repo_root / "skills" / "catalog"))
    parser.add_argument(
        "--template-path",
        default=str(repo_root / "literature_assistant" / "core" / "skills" / "SKILL.md.template"),
    )
    parser.add_argument(
        "--summary-path",
        default=str(repo_root / "skills" / "catalog" / ".skill-flow-export.json"),
    )
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    adapter = SkillFlowAdapter(
        source_root=Path(args.source_root),
        output_root=Path(args.output_root),
        template_path=Path(args.template_path),
    )
    report = adapter.sync(
        [],
        mirror_existing=True,
        strict=bool(args.strict),
        summary_path=Path(args.summary_path),
    )
    print(f"Exported {len(report.exported)} skill(s) to {args.output_root}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())