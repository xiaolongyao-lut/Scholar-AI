from __future__ import annotations

import io
import re
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz
try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


logger = logging.getLogger("E_Layer_Multimodal")


MARGIN_PX = 18


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def rect_to_list(rect: fitz.Rect | tuple[float, float, float, float] | list[float]) -> list[float]:
    r = fitz.Rect(rect)
    return [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)]


def x_overlap_ratio(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    denom = max(1.0, min(a.width, b.width))
    return inter / denom


def bbox_score(img_rect: fitz.Rect, caption_rect: fitz.Rect, page_rect: fitz.Rect) -> float:
    gap_above = caption_rect.y0 - img_rect.y1
    gap_below = img_rect.y0 - caption_rect.y1
    vertical = 0.0
    if img_rect.y1 <= caption_rect.y0:
        vertical += 3.0
        vertical += max(0.0, 2.2 - min(abs(gap_above), 220.0) / 100.0)
    elif img_rect.y0 >= caption_rect.y1:
        vertical -= 1.8
        vertical += max(0.0, 1.0 - min(abs(gap_below), 220.0) / 140.0)
    else:
        vertical -= 2.5

    overlap = 1.2 * x_overlap_ratio(img_rect, caption_rect)
    area_ratio = (img_rect.width * img_rect.height) / max(1.0, page_rect.width * page_rect.height)
    area_bonus = min(area_ratio * 8.0, 2.0)
    center_dist = abs(img_rect.tl.y + img_rect.height / 2 - caption_rect.y0)
    center_bonus = max(0.0, 1.1 - min(center_dist, 300.0) / 220.0)
    return round(vertical + overlap + area_bonus + center_bonus, 4)


def extract_raw_image(doc: fitz.Document, xref: int, out_path: Path) -> dict[str, Any]:
    base = doc.extract_image(int(xref))
    ext = base.get('ext', 'png')
    img_bytes = base['image']
    out_path = out_path.with_suffix('.' + ext)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(img_bytes)
    return {'image_path': str(out_path), 'ext': ext, 'size_bytes': len(img_bytes)}


def render_page_crop(page: fitz.Page, rect: fitz.Rect, dpi: int, out_path: Path) -> dict[str, Any]:
    if Image is None:
        raise RuntimeError("Pillow is required for page crop rendering.")
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes('png')))
    crop = (
        int(rect.x0 * zoom),
        int(rect.y0 * zoom),
        int(rect.x1 * zoom),
        int(rect.y1 * zoom),
    )
    crop = (
        max(0, crop[0]),
        max(0, crop[1]),
        min(img.width, crop[2]),
        min(img.height, crop[3]),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.crop(crop).save(out_path)
    return {'image_path': str(out_path), 'dpi': dpi, 'crop_box_px': list(crop)}


def collect_page_image_occurrences(page: fitz.Page) -> dict[int, list[fitz.Rect]]:
    out: dict[int, list[fitz.Rect]] = defaultdict(list)
    for info in page.get_image_info(xrefs=True):
        xref = int(info.get('xref') or 0)
        bbox = info.get('bbox')
        if xref > 0 and bbox is not None:
            out[xref].append(fitz.Rect(bbox))
    return out



FIGURE_PREFIX_RE = re.compile(r'^(Fig(?:ure)?\.?\s*\d+[A-Za-z]?[\.:]?)', re.I)
TABLE_PREFIX_RE = re.compile(r'^(Table\s*\d+[A-Za-z]?[\.:]?)', re.I)
FIGURE_MENTION_RE = re.compile(r'\b(?:Fig(?:ure)?\.?)[\s\u00A0]*(\d+)\b', re.I)
TABLE_MENTION_RE = re.compile(r'\bTable[\s\u00A0]*(\d+)\b', re.I)

# ── Section header detection ───────────────────────────────────────────────────
# Matches common academic section names (with optional leading number)
SECTION_HEADER_RE = re.compile(
    r'^(?:\d+(?:\.\d+)*\.?\s+)?'
    r'(?:abstract|introduction|background|'
    r'related\s+work|literature\s+review|state\s+of\s+the\s+art|'
    r'materials?\s+and\s+methods?|methods?|methodology|experimental\s+(?:section|procedure|setup)?|'
    r'experimental|results?\s+(?:and\s+discussion)?|findings?|'
    r'discussion|conclusions?|summary|'
    r'acknowledgem?ents?|references?|bibliography|appendix|'
    r'theoretical\s+(?:framework|background)|data\s+and\s+methods?|'
    r'study\s+(?:area|design)|limitations?|implications?|'
    r'future\s+(?:work|research|directions?)|'
    r'supplementary|supporting\s+information|'
    r'conflict\s+of\s+interest|funding|'
    r'statistical\s+analysis|data\s+analysis|'
    r'sample\s+(?:preparation|collection)|participants?|subjects?)\s*[:.]?\s*$',
    re.I,
)

# Matches numbered sections like "2. Methods" or "3.1 Data collection"
NUMBERED_SECTION_RE = re.compile(
    r'^(\d+(?:\.\d+)*)\s+([A-Z][A-Za-z\s\-]{2,60})\s*$'
)

# ── Noise block patterns ───────────────────────────────────────────────────────
_NOISE_PATTERNS: list[re.Pattern] = [
    re.compile(r'contents?\s+lists?\s+available', re.I),
    re.compile(r'journal\s+homepage\s*:', re.I),
    re.compile(r'www\.[a-z0-9\-]+\.(com|org|net|edu|ac)\b', re.I),
    re.compile(r'^\s*(?:https?|ftp)://', re.I),
    re.compile(r'available\s+online\s+\d', re.I),
    re.compile(r'\breceived\s*:\s*\d', re.I),
    re.compile(r'\baccepted\s*:\s*\d', re.I),
    re.compile(r'\brevised\s*:\s*\d', re.I),
    re.compile(r'^\s*©\s*20\d\d', re.I),
    re.compile(r'\ball\s+rights?\s+reserved\b', re.I),
    re.compile(r'\belsevier\s+(?:b\.v\.|ltd|inc|science)\b', re.I),
    re.compile(r'\bspringer\s+(?:nature|verlag|science)\b', re.I),
    re.compile(r'\bwiley\s+(?:periodicals?|online|blackwell)\b', re.I),
    re.compile(r'\btaylor\s+&\s+francis\b', re.I),
    re.compile(r'\bsciencedirect\b', re.I),
    re.compile(r'^\s*keywords?\s*:', re.I),
    re.compile(r'^\s*(?:a\s+r\s+t\s+i\s+c\s+l\s+e|i\s+n\s+f\s+o)\s*$', re.I),
    re.compile(r'^\s*\d{1,3}\s*$'),  # Standalone page numbers
    re.compile(r'^\s*[-–—]{3,}\s*$'),  # Divider lines
    re.compile(r'doi\s*:\s*10\.\d{4,}', re.I),
    re.compile(r'\bpublished\s+by\s+elsevier\b', re.I),
    re.compile(r'\bopen\s+access\b.*\bcc\s+by\b', re.I),
    re.compile(r'\bpeer\s+review\b.*\bunder\s+responsibility\b', re.I),
]


def _is_noise_block(text: str) -> bool:
    """Return True if the text block is likely non-content noise."""
    stripped = text.strip()
    if not stripped:
        return True
    for pat in _NOISE_PATTERNS:
        if pat.search(stripped):
            return True
    # Mostly non-alphabetic short blocks (separators, page refs, etc.)
    alpha_ratio = sum(1 for c in stripped if c.isalpha()) / max(1, len(stripped))
    if alpha_ratio < 0.35 and len(stripped) < 60:
        return True
    return False


def _detect_section_header(text: str, max_font: float, body_font: float) -> str | None:
    """Return section name if *text* looks like a section header, else None."""
    stripped = text.strip()
    # Section headers are short
    if not stripped or len(stripped) > 120:
        return None
    # Exact keyword match
    if SECTION_HEADER_RE.match(stripped):
        # Normalise to title-case for readability
        return stripped.split('\n')[0].strip().title()
    # Numbered section pattern: "2. Methods", "3.1 Data collection"
    m = NUMBERED_SECTION_RE.match(stripped)
    if m:
        return m.group(2).strip().title()
    # Font-size heuristic: noticeably larger than body text AND short
    if body_font > 0 and max_font >= body_font * 1.18 and len(stripped) <= 80:
        # Only if it reads like a title (first word capitalised, no verb endings typical of sentences)
        first_word = stripped.split()[0] if stripped.split() else ""
        if first_word and first_word[0].isupper() and not stripped.endswith(('.', '?', '!')):
            return stripped.title()
    return None

def normalize_ws(text: str) -> str:
    text = text.replace('\xa0', ' ').replace('-\n', '')
    return re.sub(r'\s+', ' ', text).strip()

def parse_blocks(page: fitz.Page) -> list[dict[str, Any]]:
    data = page.get_text('dict', sort=True)
    blocks = []
    for bi, b in enumerate(data.get('blocks', [])):
        if b.get('type') != 0: continue
        lines = []
        max_font = 0.0
        for line in b.get('lines', []):
            spans = line.get('spans', [])
            lines.append(''.join(span.get('text', '') for span in spans))
            for span in spans: max_font = max(max_font, float(span.get('size', 0) or 0))
        text = '\n'.join(lines).strip()
        if text:
            blocks.append({
                'block_index': bi, 'text': text, 'max_font': round(max_font, 2),
                'bbox': [round(float(v), 2) for v in b.get('bbox', [0,0,0,0])]
            })
    return blocks

def collect_captions(blocks: list[dict[str, Any]], kind: str) -> tuple[list[dict[str, Any]], set[int]]:
    prefix_re = FIGURE_PREFIX_RE if kind == 'figure' else TABLE_PREFIX_RE
    items, used = [], set()
    for i, b in enumerate(blocks):
        text = normalize_ws(b['text'])
        m = prefix_re.match(text)
        if m:
            num_m = re.search(r'(\d+)', m.group(1))
            if num_m:
                number = int(num_m.group(1))
                items.append({
                    f'{kind}_id': f"{'f' if kind=='figure' else 't'}{number}",
                    f'{kind}_number': number, 'caption': text, 'bbox': b['bbox'], 'block_index': b['block_index']
                })
                used.add(b['block_index'])
    return items, used

def attach_nearby_chunks(items: list[dict[str, Any]], chunks: list[dict[str, Any]], kind: str) -> None:
    chunks_by_page = defaultdict(list)
    for c in chunks: chunks_by_page[c['page']].append(c)
    key_num = f'{kind}_number'
    for item in items:
        page, related = item['page'], []
        for c in chunks_by_page.get(page, []):
            if item[key_num] in c.get(f'mentioned_{kind}s', []):
                related.append((0.0, c['chunk_id']))
            elif abs(c['bbox'][1] - item['bbox'][1]) <= 250:
                related.append((abs(c['bbox'][1] - item['bbox'][1]), c['chunk_id']))
        item['nearby_chunk_ids'] = [cid for _, cid in sorted(related)[:3]]

def full_extract(pdf_path: str) -> dict[str, Any]:
    """E-Layer entry point: Extracts text and images with full metadata."""
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    chunks, figures, tables = [], [], []
    all_blocks = [parse_blocks(doc[i]) for i in range(len(doc))]

    # Pre-compute body font size: median non-zero font size across all blocks
    all_fonts = [b['max_font'] for page_blocks in all_blocks for b in page_blocks if b['max_font'] > 0]
    all_fonts.sort()
    body_font = all_fonts[len(all_fonts) // 2] if all_fonts else 11.0

    # 1. 提取图注/表注
    used_indices = {}
    for i in range(len(doc)):
        figs, used_f = collect_captions(all_blocks[i], 'figure')
        tabs, used_t = collect_captions(all_blocks[i], 'table')
        used_indices[i+1] = used_f | used_t
        for f in figs: f['page'] = i+1; figures.append(f)
        for t in tabs: t['page'] = i+1; tables.append(t)

    # 2. 提取正文块，检测章节，过滤噪声
    current_section = "Introduction"  # default before any header is found
    for i in range(len(doc)):
        page_idx = i + 1
        for b in all_blocks[i]:
            if b['block_index'] in used_indices.get(page_idx, set()): continue
            text = normalize_ws(b['text'])
            if not text or len(text) < 15: continue

            # --- Section header detection ---
            detected = _detect_section_header(text, b['max_font'], body_font)
            if detected:
                current_section = detected
                continue  # Don't create a chunk for the header itself

            # --- Noise filter ---
            if _is_noise_block(text):
                continue

            # Skip very short chunks (< 40 chars) — too little semantic content
            if len(text) < 40:
                continue

            chunks.append({
                "chunk_id": f"c{len(chunks)+1:04d}",
                "text": text, "page": page_idx, "bbox": b['bbox'],
                "mentioned_figures": sorted({int(n) for n in FIGURE_MENTION_RE.findall(text)}),
                "mentioned_tables": sorted({int(n) for n in TABLE_MENTION_RE.findall(text)}),
                "section_title": current_section
            })

    # 3. 建立空间邻近关系
    attach_nearby_chunks(figures, chunks, 'figure')
    attach_nearby_chunks(tables, chunks, 'table')

    return {
        "source_pdf": str(pdf_path.resolve()),
        "chunks": chunks,
        "figures": figures,
        "tables": tables,
        "relation_edges": []
    }


def refine_single_figures(material_pack: dict[str, Any], out_dir: Path, dpi: int = 220) -> dict[str, Any]:
    """
    针对材料包中的图卡进行视觉校准与像素级裁切。
    实现了“只保留图片、避开图注”的主核心逻辑。
    """
    source_pdf = material_pack.get('source_pdf')
    if not source_pdf:
        return {'status': 'error', 'message': 'material pack missing source_pdf'}
    
    pdf_path = Path(source_pdf)
    if not pdf_path.exists():
        return {'status': 'error', 'message': f'source_pdf not found: {pdf_path}'}

    doc = fitz.open(str(pdf_path))
    figure_cards = material_pack.get('single_figure_cards', []) or []
    if not figure_cards:
        # Fallback to writing_point_cards linked figures if any
        pass

    page_occ_cache: dict[int, dict[int, list[fitz.Rect]]] = {}
    refined_cards: list[dict[str, Any]] = []
    
    stats = {
        'total_figure_cards': len(figure_cards),
        'with_primary_image': 0,
        'with_page_crop': 0,
    }

    base_name = pdf_path.stem
    figure_root = out_dir / "figures"
    figure_root.mkdir(parents=True, exist_ok=True)

    for fig in figure_cards:
        fig_id = fig.get('figure_id')
        page_num = int(fig.get('page') or 0)
        
        # 验证页码
        if not fig_id or page_num < 1 or page_num > len(doc):
            refined_cards.append(fig)
            continue
            
        page = doc[page_num - 1]
        page_rect = page.rect
        
        # 确定图注区域（用于避碰评分）
        # 如果没有 bbox，默认占据整页宽度但高度为 0
        caption_rect = fitz.Rect(fig.get('bbox') or [0, 0, page_rect.width, 0])
        
        # [v40.2] 扫描该页所有文本块，寻找可能的冲突文字
        forbidden_zones = []
        blocks = page.get_text("blocks")
        for b in blocks:
            b_rect = fitz.Rect(b[:4])
            b_text = b[4].strip()
            # 如果是题注前缀或包含显著题注特征
            if FIGURE_PREFIX_RE.match(b_text) or TABLE_PREFIX_RE.match(b_text):
                forbidden_zones.append(b_rect)
            elif len(b_text) < 15 and ("Fig" in b_text or "Table" in b_text):
                forbidden_zones.append(b_rect)

        
        if page_num not in page_occ_cache:
            page_occ_cache[page_num] = collect_page_image_occurrences(page)
        occ_map = page_occ_cache[page_num]

        # 查找该页上的所有图像 xref
        candidate_xrefs = [int(x) for x in fig.get('candidate_image_xrefs_on_page', []) if str(x).isdigit()]
        if not candidate_xrefs:
            candidate_xrefs = sorted(occ_map.keys())

        # 候选匹配
        candidates: list[dict[str, Any]] = []
        for xref in candidate_xrefs:
            for idx, occ in enumerate(occ_map.get(int(xref), []), start=1):
                score = bbox_score(occ, caption_rect, page_rect)
                candidates.append({
                    'xref': int(xref),
                    'occurrence_index': idx,
                    'bbox': rect_to_list(occ),
                    'score': score
                })

        primary = None
        if candidates:
            # 选取得分最高且面积较大的
            candidates.sort(key=lambda row: (row['score'], (fitz.Rect(row['bbox']).width * fitz.Rect(row['bbox']).height)), reverse=True)
            primary = candidates[0]

        refined = dict(fig)
        
        if primary:
            primary_rect = fitz.Rect(primary['bbox'])
            # 像素级裁剪：增加微小边距
            padded = fitz.Rect(
                clamp(primary_rect.x0 - 5, 0, page_rect.width),
                clamp(primary_rect.y0 - 5, 0, page_rect.height),
                clamp(primary_rect.x1 + 5, 0, page_rect.width),
                clamp(primary_rect.y1 + 5, 0, page_rect.height),
            )
            
            # [v40.2] 避让算法：如果 forbidden_zone 在 padded 内部或边缘，收缩边界
            for fz in forbidden_zones:
                if fz.intersects(padded):
                    # 如果题注在下方（最常见情况）
                    if fz.y0 > primary_rect.y0 and abs(fz.y0 - primary_rect.y1) < 40:
                        padded.y1 = min(padded.y1, fz.y0 - 2)
                    # 如果题注在上方
                    elif fz.y1 < primary_rect.y1 and abs(fz.y1 - primary_rect.y0) < 40:
                        padded.y0 = max(padded.y0, fz.y1 + 2)
            
            # 生成渲染图
            fig_dir = figure_root / f"{fig_id}"
            fig_dir.mkdir(parents=True, exist_ok=True)
            out_path = fig_dir / f"{fig_id}_crop.png"
            
            try:
                crop_meta = render_page_crop(page, padded, dpi=dpi, out_path=out_path)
                
                # 注入绝对路径供 P-Layer 使用
                refined['primary_single_figure'] = {
                    'page': page_num,
                    'xref': primary['xref'],
                    'bbox': primary['bbox'],
                    'page_crop_image': {
                        'image_path': str(out_path.absolute()),
                        'dpi': dpi
                    }
                }
                stats['with_primary_image'] += 1
                stats['with_page_crop'] += 1
            except Exception as e:
                import logging
                logging.getLogger("E_Layer").warning(f"Failed to crop figure {fig_id}: {e}")

        refined_cards.append(refined)

    return {
        'status': 'ok',
        'single_figure_cards_refined': refined_cards,
        'refinement_stats': stats
    }


def refine_multimodal_assets(material_pack: dict[str, Any], out_dir: Path, dpi: int = 220) -> dict[str, Any]:
    """ v40.2 整合：处理图表与表格的高清导出 """
    logger.info(">>> [E-Layer] 正在导出高清图表与表格证据...")
    
    # 1. 裁剪图表
    fig_res = refine_single_figures(material_pack, out_dir, dpi)
    figure_cards = fig_res.get('single_figure_cards_refined', [])
    
    # 2. 裁剪表格 [NEW v40.2]
    source_pdf = material_pack.get('source_pdf')
    table_cards = material_pack.get('single_table_cards', []) or []
    refined_tables = []
    
    if source_pdf and table_cards:
        pdf_path = Path(source_pdf)
        doc = fitz.open(str(pdf_path))
        table_root = out_dir / "tables"
        table_root.mkdir(parents=True, exist_ok=True)
        
        for tab in table_cards:
            page_num = int(tab.get('page') or 0)
            tab_id = tab.get('table_id', 't0')
            if page_num < 1 or page_num > len(doc): 
                refined_tables.append(tab)
                continue
            
            page = doc[page_num-1]
            # 表格通常没有 xref，直接根据 caption 附近的空白区裁切，或根据 bbox (如果 A-Layer 提供了)
            bbox = tab.get('bbox')
            if bbox:
                tab_rect = fitz.Rect(bbox)
                # 表格稍微多给点边距
                tab_padded = fitz.Rect(
                    clamp(tab_rect.x0 - 10, 0, page.rect.width),
                    clamp(tab_rect.y0 - 10, 0, page.rect.height),
                    clamp(tab_rect.x1 + 10, 0, page.rect.width),
                    clamp(tab_rect.y1 + 10, 0, page.rect.height),
                )
                
                tab_dir = table_root / f"{tab_id}"
                tab_dir.mkdir(parents=True, exist_ok=True)
                out_path = tab_dir / f"{tab_id}_crop.png"
                
                try:
                    crop_meta = render_page_crop(page, tab_padded, dpi=300, out_path=out_path)
                    tab_refined = dict(tab)
                    tab_refined['page_crop_image'] = {
                        'image_path': str(out_path),
                        'dpi': 300,
                        'crop_box_px': crop_meta['crop_box_px']
                    }
                    refined_tables.append(tab_refined)
                except Exception:
                    refined_tables.append(tab)
            else:
                refined_tables.append(tab)
    
    return {
        'status': 'ok',
        'single_figure_cards_refined': figure_cards,
        'single_table_cards_refined': refined_tables or table_cards,
        'stats': fig_res.get('refinement_stats', {})
    }
