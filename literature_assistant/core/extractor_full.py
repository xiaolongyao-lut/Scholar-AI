# -*- coding: utf-8 -*-
"""
extractor_full.py
文献处理器 - 完整内容提取模块

核心功能:
1. 提取 PDF 文本与多模态资源
2. 识别章节结构与引文
3. 提取图表描述与位置信息
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

FIGURE_PREFIX_RE = re.compile(r'^(Fig(?:ure)?\.?\s*\d+[A-Za-z]?[\.:]?)', re.I)
TABLE_PREFIX_RE = re.compile(r'^(Table\s*\d+[A-Za-z]?[\.:]?)', re.I)
FIGURE_MENTION_RE = re.compile(r'\b(?:Fig(?:ure)?\.?)[\s\u00A0]*(\d+)\b', re.I)
TABLE_MENTION_RE = re.compile(r'\bTable[\s\u00A0]*(\d+)\b', re.I)
REF_SINGLE_RE = re.compile(r'\[(\d+)\]')
REF_MULTI_RE = re.compile(r'\[(\d+(?:\s*[-–,]\s*\d+)*)\]')
REF_LINE_START_RE = re.compile(r'^\s*\[?(\d+)\]?[.)]?\s*(.*)$')
PARAM_UNIT_RE = re.compile(
    r'(?:\b\d+(?:\.\d+)?\s*(?:W|kW|J|mJ|V|A|Hz|kHz|MHz|rpm|r/min|mm|cm|m|mm/s|mm/min|m/s|µm|μm|nm|MPa|GPa|Pa|N|kN|°C|K|s|min|h|wt\.%|at\.%|mol\.%|%|mL/min|L/min|g/L|mg/L|g|kg)\b)',
    re.I,
)
PARAM_KEYWORD_RE = re.compile(
    r'\b(power|speed|velocity|frequency|radius|diameter|thickness|flow rate|gas flow|amplitude|modulation|offset|defocus|current|voltage|pressure|temperature|time|duration|scan|scanning|composition|content)\b',
    re.I,
)
RESULT_CUE_RE = re.compile(
    r'\b(increase(?:d|s)?|decrease(?:d|s)?|reduc(?:e|ed|es|tion)|improv(?:e|ed|es|ement)|enhanc(?:e|ed|es|ement)|refin(?:e|ed|ement)|mitigat(?:e|ed|es|ion)|higher|lower|wider|narrower|greater|smaller|better|worse|optimal|optimum|achiev(?:e|ed|es)|reach(?:ed|es)|led to|resulted in|promoted|suppressed)\b',
    re.I,
)
REF_HEADING_RE = re.compile(r'^\s*(references|bibliography)\s*$', re.I)
SECTION_PATTERNS = [
    re.compile(r'^(\d+(?:\.\d+)*)\s+[A-Z][\w\-\s,:()/%]{2,}$'),
    re.compile(r'^(Abstract|Introduction|Materials and methods|Methods|Experimental(?: procedures?)?|Results(?: and discussion)?|Discussion|Conclusions?|References)\s*$', re.I),
]
NOISE_RE = re.compile(
    r'(journal homepage|available online|accepted \d{1,2} \w+ \d{4}|received \d{1,2} \w+ \d{4}|keywords?:|corresponding author|doi\s*:|www\.)',
    re.I,
)
BROKEN_WORD_RE = re.compile(r'(?<=[A-Za-z])\s+(?=[A-Za-z])')


def normalize_ws(text: str) -> str:
    text = text.replace('\xa0', ' ')
    text = text.replace('-\n', '')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def clean_caption(text: str) -> str:
    text = text.replace('-\n', '')
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\b([A-Za-z]{2,5})\s+([A-Za-z]{2,5})\b', lambda m: m.group(1)+m.group(2) if (m.group(1)+m.group(2)).lower() in {'morphologies','mechanism','microstructure','comparison','different','modulation'} else m.group(0), text)
    return text


def extract_ref_numbers(text: str) -> list[int]:
    out: list[int] = []
    for m in REF_MULTI_RE.finditer(text):
        spec = m.group(1)
        for part in re.split(r'\s*,\s*', spec):
            if re.search(r'[-–]', part):
                a, b = re.split(r'\s*[-–]\s*', part)[:2]
                if a.isdigit() and b.isdigit():
                    start, end = sorted((int(a), int(b)))
                    out.extend(list(range(start, end + 1)))
            elif part.strip().isdigit():
                out.append(int(part.strip()))

    # Handle superscript-like inline citations that appear in extracted PDF text
    # e.g. "software48" or "et al.33" in Nature-style PDFs.
    for m in re.finditer(r'(?<=[A-Za-z\)])(\d{1,3})(?=[,.;:\s])', text):
        num = int(m.group(1))
        prefix = text[max(0, m.start() - 14):m.start()].lower()
        if any(prefix.endswith(tok) for tok in ('fig', 'figure', 'table', 'eq', 'equation', 'ref', 'refs')):
            continue
        if 1 <= num <= 300:
            out.append(num)
    return sorted(set(out))


def find_reference_start_page(pages_text: list[str]) -> int | None:
    ref_like_re = re.compile(r'^\s*(?:\[?\d+\]?[.)]?\s+|\d+[.)]\s*$)')
    for idx, text in enumerate(pages_text, start=1):
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if any(REF_HEADING_RE.match(line) for line in lines):
            return idx
    # Fallback for styles where the references page starts without a heading at the top.
    page_scores = []
    for idx, text in enumerate(pages_text, start=1):
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        count = sum(1 for line in lines if ref_like_re.match(line))
        page_scores.append((idx, count))
    dense_pages = [idx for idx, count in page_scores if count >= 8]
    if dense_pages:
        return dense_pages[0]
    return None


def page_image_manifest(doc: fitz.Document, pdf_path: Path) -> list[dict[str, Any]]:
    out_dir = pdf_path.with_name(pdf_path.stem + '_embedded_images')
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for page_index in range(len(doc)):
        page = doc[page_index]
        rects_by_xref: dict[int, list[list[float]]] = {}
        for info in page.get_image_info(xrefs=True):
            xref = int(info.get('xref', 0) or 0)
            bbox = info.get('bbox')
            if xref <= 0 or bbox is None:
                continue
            rects_by_xref.setdefault(xref, []).append([round(float(v), 2) for v in bbox])
        page_imgs = page.get_images(full=True)
        for i, img in enumerate(page_imgs, start=1):
            xref = int(img[0])
            try:
                base = doc.extract_image(xref)
            except Exception:
                continue
            ext = base.get('ext', 'png')
            img_bytes = base['image']
            path = out_dir / f'page_{page_index+1:02d}_img_{i:02d}.{ext}'
            path.write_bytes(img_bytes)
            manifest.append({
                'page': page_index + 1,
                'xref': xref,
                'path': str(path),
                'width': int(base.get('width', 0) or 0),
                'height': int(base.get('height', 0) or 0),
                'rects': rects_by_xref.get(xref, []),
            })
    return manifest


def is_section_title(text: str, max_font: float, median_font: float) -> bool:
    t = normalize_ws(text)
    if not t or len(t) > 120:
        return False
    if FIGURE_PREFIX_RE.match(t) or TABLE_PREFIX_RE.match(t) or REF_HEADING_RE.match(t):
        return False
    if any(p.match(t) for p in SECTION_PATTERNS):
        return True
    if max_font >= median_font + 1.5 and len(t.split()) <= 12 and t[0].isupper():
        return True
    return False


def parse_blocks(page: fitz.Page) -> list[dict[str, Any]]:
    data = page.get_text('dict', sort=True)
    blocks: list[dict[str, Any]] = []
    for bi, b in enumerate(data.get('blocks', [])):
        if b.get('type') != 0:
            continue
        lines = []
        max_font = 0.0
        for line in b.get('lines', []):
            spans = line.get('spans', [])
            line_text = ''.join(span.get('text', '') for span in spans)
            if line_text.strip():
                lines.append(line_text)
            for span in spans:
                max_font = max(max_font, float(span.get('size', 0) or 0))
        text = '\n'.join(lines).strip()
        if not text:
            continue
        blocks.append({
            'block_index': bi,
            'text': text,
            'bbox': [round(float(v), 2) for v in b.get('bbox', [0, 0, 0, 0])],
            'max_font': round(max_font, 2),
        })
    return blocks


def collect_captions(blocks: list[dict[str, Any]], kind: str) -> tuple[list[dict[str, Any]], set[int]]:
    prefix_re = FIGURE_PREFIX_RE if kind == 'figure' else TABLE_PREFIX_RE
    items: list[dict[str, Any]] = []
    used: set[int] = set()
    i = 0
    while i < len(blocks):
        text = normalize_ws(blocks[i]['text'])
        m = prefix_re.match(text)
        if not m:
            i += 1
            continue
        prefix = m.group(1).strip()
        num_m = re.search(r'(\d+)', prefix)
        if not num_m:
            i += 1
            continue
        number = int(num_m.group(1))
        caption_parts = [text]
        used.add(blocks[i]['block_index'])
        base_top = blocks[i]['bbox'][1]
        j = i + 1
        while j < len(blocks):
            nxt = blocks[j]
            nxt_text = normalize_ws(nxt['text'])
            if not nxt_text:
                j += 1
                continue
            if FIGURE_PREFIX_RE.match(nxt_text) or TABLE_PREFIX_RE.match(nxt_text) or is_likely_body_start(nxt_text):
                break
            if abs(nxt['bbox'][1] - base_top) > 120 and len(caption_parts) >= 1:
                break
            if len(nxt_text) > 240:
                break
            caption_parts.append(nxt_text)
            used.add(nxt['block_index'])
            j += 1
        caption = clean_caption(' '.join(caption_parts))
        items.append({
            f'{kind}_id': f"{'f' if kind=='figure' else 't'}{number}",
            f'{kind}_number': number,
            'caption_prefix': prefix,
            'caption': caption,
            'bbox': blocks[i]['bbox'],
            'block_index': blocks[i]['block_index'],
        })
        i = j
    return items, used


def is_likely_body_start(text: str) -> bool:
    t = normalize_ws(text)
    if len(t) > 300:
        return True
    if re.match(r'^[A-Z][a-z].+[\.;:]$', t) and len(t.split()) > 10:
        return True
    return False


def build_sections(page_blocks: list[list[dict[str, Any]]], median_font: float) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for page_idx, blocks in enumerate(page_blocks, start=1):
        for b in blocks:
            text = normalize_ws(b['text'])
            if is_section_title(text, b['max_font'], median_font):
                title = re.sub(r'^\d+(?:\.\d+)*\s+', '', text).strip()
                key = title.lower()
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                sections.append({
                    'section_id': str(len(sections) + 1),
                    'title': title,
                    'page': page_idx,
                    'bbox': b['bbox'],
                })
    return sections


def assign_section(sections: list[dict[str, Any]], page: int, y0: float) -> tuple[str | None, str | None]:
    chosen: dict[str, Any] | None = None
    for sec in sections:
        if sec['page'] < page or (sec['page'] == page and sec['bbox'][1] <= y0 + 1):
            chosen = sec
        elif sec['page'] > page:
            break
    if chosen:
        return chosen['section_id'], chosen['title']
    return None, None


def block_is_noise(text: str) -> bool:
    t = normalize_ws(text)
    if not t:
        return True
    if NOISE_RE.search(t):
        return True
    if len(t) < 4:
        return True
    if t.lower() in {'abstract', 'references'}:
        return True
    if re.fullmatch(r'\d+', t):
        return True
    return False


def collect_chunks(page_blocks: list[list[dict[str, Any]]], sections: list[dict[str, Any]], ref_start: int | None, used_caption_indices: dict[int, set[int]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page_idx, blocks in enumerate(page_blocks, start=1):
        if ref_start and page_idx >= ref_start:
            continue
        for b in blocks:
            if b['block_index'] in used_caption_indices.get(page_idx, set()):
                continue
            text = normalize_ws(b['text'])
            if block_is_noise(text):
                continue
            if FIGURE_PREFIX_RE.match(text) or TABLE_PREFIX_RE.match(text):
                continue
            if is_section_title(text, b['max_font'], median_font=0):
                continue
            sec_id, sec_title = assign_section(sections, page_idx, b['bbox'][1])
            if sec_id is None and page_idx == 1 and len(text.split()) < 40:
                continue
            chunk = {
                'chunk_id': f'c{len(chunks)+1:04d}',
                'page': page_idx,
                'section_id': sec_id,
                'section_title': sec_title,
                'text': text,
                'bbox': b['bbox'],
                'block_index': b['block_index'],
                'cited_refs': extract_ref_numbers(text),
                'mentioned_figures': sorted({int(n) for n in FIGURE_MENTION_RE.findall(text)}),
                'mentioned_tables': sorted({int(n) for n in TABLE_MENTION_RE.findall(text)}),
            }
            chunks.append(chunk)
    return chunks


def attach_nearby_chunks(items: list[dict[str, Any]], chunks: list[dict[str, Any]], page_images: list[dict[str, Any]], kind: str) -> None:
    images_by_page: dict[int, list[dict[str, Any]]] = {}
    for img in page_images:
        images_by_page.setdefault(img['page'], []).append(img)
    chunks_by_page: dict[int, list[dict[str, Any]]] = {}
    for c in chunks:
        chunks_by_page.setdefault(c['page'], []).append(c)
    key_num = f'{kind}_number'
    id_key = f'{kind}_id'
    for item in items:
        page = item['page']
        related: list[tuple[float, str]] = []
        for c in chunks_by_page.get(page, []):
            if item[key_num] in c.get(f'mentioned_{kind}s', []):
                related.append((0.0, c['chunk_id']))
                continue
            dy = abs(c['bbox'][1] - item['bbox'][1])
            if dy <= 200:
                related.append((dy, c['chunk_id']))
        related = sorted(related, key=lambda x: (x[0], x[1]))[:3]
        item['nearby_chunk_ids'] = [cid for _, cid in related]
        item['candidate_image_count_on_page'] = len(images_by_page.get(page, []))
        item['candidate_image_xrefs_on_page'] = [img['xref'] for img in images_by_page.get(page, [])]
        item[id_key] = item[id_key]


def extract_references(pages_text: list[str], ref_start: int | None) -> list[dict[str, Any]]:
    if not ref_start:
        return []
    ref_text = '\n'.join(pages_text[ref_start - 1:]).replace('-\n', '')
    lines = [l.rstrip() for l in ref_text.splitlines()]

    refs: list[dict[str, Any]] = []
    current_num: int | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_num, current_parts
        if current_num is None:
            return
        raw = normalize_ws(' '.join(current_parts))
        raw = re.sub(r'^(Article|Nature Communications\|).*$', '', raw, flags=re.I).strip()
        if raw:
            refs.append({'ref_number': int(current_num), 'ref_id': f'ref_{int(current_num):03d}', 'raw_text': raw})
        current_num = None
        current_parts = []

    for line in lines:
        s = line.strip()
        if not s:
            continue
        if REF_HEADING_RE.match(s):
            continue
        if re.match(r'^(Acknowledgements|Author contributions|Competing interests|Additional information|CRediT authorship contribution statement|Declaration of Competing Interest|Appendix)', s, re.I):
            flush()
            continue
        if re.match(r'^(Article|Nature Communications\||https?://doi\.org/10\.1038/)', s, re.I):
            continue

        m = REF_LINE_START_RE.match(s)
        if m:
            num = int(m.group(1))
            rest = m.group(2).strip()
            # A start-of-reference line is a standalone number line or a line with author/title text after the number.
            if rest == '' or re.search(r'[A-Za-z].{3,}', rest):
                flush()
                current_num = num
                current_parts = [rest] if rest else []
                continue

        if current_num is not None:
            current_parts.append(s)
    flush()
    return refs


def collect_parameter_candidates(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in chunks:
        text = c['text']
        if PARAM_UNIT_RE.search(text) and (PARAM_KEYWORD_RE.search(text) or len(re.findall(r'\d+(?:\.\d+)?', text)) >= 2):
            out.append({'chunk_id': c['chunk_id'], 'page': c['page'], 'section_id': c['section_id'], 'text': text})
    return dedupe_by_text(out)


def collect_result_candidates(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in chunks:
        text = c['text']
        if RESULT_CUE_RE.search(text) and (PARAM_UNIT_RE.search(text) or '%' in text or len(re.findall(r'\d+(?:\.\d+)?', text)) >= 2):
            out.append({'chunk_id': c['chunk_id'], 'page': c['page'], 'section_id': c['section_id'], 'text': text})
    return dedupe_by_text(out)


def dedupe_by_text(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = normalize_ws(item['text']).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def full_extract(pdf_path: str) -> dict[str, Any]:
    src = Path(pdf_path)
    doc = fitz.open(pdf_path)
    pages_text = [doc[i].get_text('text') for i in range(len(doc))]
    all_blocks = [parse_blocks(doc[i]) for i in range(len(doc))]
    fonts = [b['max_font'] for blocks in all_blocks for b in blocks if b['max_font'] > 0]
    median_font = sorted(fonts)[len(fonts)//2] if fonts else 10.0
    ref_start = find_reference_start_page(pages_text)
    page_images = page_image_manifest(doc, src)
    sections = build_sections(all_blocks, median_font)

    figures: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    used_caption_indices: dict[int, set[int]] = {}
    for page_idx, blocks in enumerate(all_blocks, start=1):
        figs, used_f = collect_captions(blocks, 'figure')
        tabs, used_t = collect_captions(blocks, 'table')
        used_caption_indices[page_idx] = set(used_f) | set(used_t)
        for item in figs:
            item['page'] = page_idx
            figures.append(item)
        for item in tabs:
            item['page'] = page_idx
            tables.append(item)

    chunks = collect_chunks(all_blocks, sections, ref_start, used_caption_indices)
    attach_nearby_chunks(figures, chunks, page_images, 'figure')
    attach_nearby_chunks(tables, chunks, page_images, 'table')
    references = extract_references(pages_text, ref_start)
    parameter_candidates = collect_parameter_candidates(chunks)
    result_candidates = collect_result_candidates(chunks)

    out = {
        'source_pdf': str(src),
        'page_count': len(doc),
        'reference_start_page': ref_start,
        'pages_text': pages_text,
        'full_text': '\n'.join(pages_text),
        'sections': sections,
        'chunks': chunks,
        'figures': figures,
        'tables': tables,
        'references': references,
        'parameter_candidates': parameter_candidates,
        'result_candidates': result_candidates,
        'page_images': page_images,
        'stats': {
            'section_count': len(sections),
            'chunk_count': len(chunks),
            'figure_count': len(figures),
            'table_count': len(tables),
            'reference_count': len(references),
            'parameter_candidate_count': len(parameter_candidates),
            'result_candidate_count': len(result_candidates),
            'embedded_image_count': len(page_images),
        },
        'status': 'full_extraction_ready',
    }
    return out


def main(input_pdf: str, output_json: str | None = None) -> None:
    src = Path(input_pdf)
    out = full_extract(input_pdf)
    if output_json is None:
        output_json = str(src.with_name(src.stem + '_full_extract.json'))
    Path(output_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(out['stats'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python extractor_full.py <input_pdf> [output_json]')
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
