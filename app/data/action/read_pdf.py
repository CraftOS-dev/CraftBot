from agent_core import action

@action(
    name="read_pdf",
    description="Securely reads a PDF with Docling and returns compact, layout-aware JSON including page sizes, bboxes, text, and form-field candidates. Implements a robust fallback using pypdfium2 and pdfminer.six if Docling cannot determine page sizes or extract text.",
    mode="CLI",
    action_sets=["document_processing"],
    platforms=["windows", "linux", "darwin"],
    input_schema={
        "file_path": {
            "type": "string",
            "example": "C:/path/to/form.pdf",
            "description": "Local path to the PDF to read."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success"
        },
        "content": {
            "type": "object",
            "description": "Layout-aware PDF extraction output.",
            "example": {
                "document_metadata": {
                    "file_name": "sample.pdf",
                    "mimetype": "application/pdf",
                    "docling_version": "1.7.0"
                },
                "pages": [
                    {
                        "page_number": 1,
                        "width": 595.44,
                        "height": 841.68
                    }
                ],
                "elements": [
                    {
                        "page_number": 1,
                        "element_type": "text",
                        "text": "Name:",
                        "bbox_abs": {
                            "x0": 10,
                            "y0": 20,
                            "x1": 100,
                            "y1": 40,
                            "coord_origin": "BOTTOMLEFT"
                        },
                        "bbox_norm": {
                            "x0": 0.05,
                            "y0": 0.02,
                            "x1": 0.2,
                            "y1": 0.05
                        },
                        "is_form_field_candidate": False
                    }
                ]
            }
        },
        "message": {
            "type": "string",
            "example": "File not found.",
            "description": "Only set if status = error."
        }
    },
    requirement=["Any", "DocumentConverter", "pypdfium2", "extract_text", "docling", "pdfminer"],
    test_payload={
        "file_path": "C:/path/to/form.pdf",
        "simulated_mode": True
    }
)
def read_pdf_file(input_data: dict) -> dict:
    #!/usr/bin/env python3
    import json, sys, os, re, importlib, subprocess
    from typing import Any, Dict, List

    simulated_mode = input_data.get('simulated_mode', False)

    if simulated_mode:
        # Return mock result for testing
        return {
            'status': 'success',
            'message': '',
            'content': {
                'document_metadata': {
                    'file_name': 'test.pdf',
                    'mimetype': 'application/pdf',
                    'docling_version': '1.7.0'
                },
                'pages': [{'page_number': 1, 'width': 595.44, 'height': 841.68}],
                'elements': [
                    {
                        'page_number': 1,
                        'element_type': 'text',
                        'text': 'Test PDF content',
                        'bbox_abs': {'x0': 10, 'y0': 20, 'x1': 100, 'y1': 40, 'coord_origin': 'BOTTOMLEFT'},
                        'bbox_norm': {'x0': 0.05, 'y0': 0.02, 'x1': 0.2, 'y1': 0.05},
                        'is_form_field_candidate': False
                    }
                ]
            }
        }

    # -------------------
    # Safe dependency install
    # -------------------
    def _ensure(pkg: str) -> None:
        try:
            importlib.import_module(pkg)
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])

    for _pkg in ('docling','pypdfium2','pdfminer.six','Pillow'):
        _ensure(_pkg)

    from docling.document_converter import DocumentConverter
    import pypdfium2
    from pdfminer.high_level import extract_text

    SAFE_EXTS = {'.pdf'}
    MAX_FILE_SIZE_MB = 50
    _FIELD_RE = re.compile(r'(?:_{4,}|\.{4,}|—{3,}|–{3,})')

    # Helper functions
    def _json(status, message='', content=None):
        return {'status': status, 'message': message, 'content': content or ''}

    def _is_form_blank(text):
        if not text:
            return False
        return bool(_FIELD_RE.search(text.strip()))

    def _to_safe_int(v):
        if isinstance(v, int):
            if v > 9223372036854775807 or v < -9223372036854775808:
                return str(v)
        return v

    def _deep_sanitize(o):
        if isinstance(o, dict):
            return {k: _deep_sanitize(_to_safe_int(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [_deep_sanitize(_to_safe_int(v)) for v in o]
        return _to_safe_int(o)

    # Page extraction with fallback
    def _extract_pages(raw, src):
        pages = raw.get('pages') if raw else []
        out = []

        if isinstance(pages, list):
            for p in pages:
                size = p.get('size') or {}
                out.append({'page_number': p.get('page_no') or p.get('number'), 'width': size.get('width'), 'height': size.get('height')})
        elif isinstance(pages, dict):
            for k in sorted(pages.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
                p = pages[k]
                size = p.get('size') or {}
                out.append({'page_number': p.get('page_no') or p.get('number') or int(k), 'width': size.get('width'), 'height': size.get('height')})

        needs_fallback = any(p['width'] in (None,0) or p['height'] in (None,0) for p in out) or not out
        if needs_fallback:
            try:
                pdf = pypdfium2.PdfDocument(src)
                if not out:
                    out = [{'page_number': i+1, 'width': None, 'height': None} for i in range(len(pdf))]
                for idx, p in enumerate(out):
                    page = pdf.get_page(idx)
                    w, h = page.get_size()
                    if not p['width']:
                        p['width'] = float(w)
                    if not p['height']:
                        p['height'] = float(h)
            except Exception:
                out = [{'page_number': i+1, 'width': 612, 'height': 792} for i in range(len(out) or 1)]
        return out

    # Map page dimensions
    def _page_dims_map(pages):
        out = {}
        for p in pages:
            pn = p.get('page_number')
            if isinstance(pn, int) and p.get('width') and p.get('height'):
                out[pn] = {'w': float(p['width']), 'h': float(p['height'])}
        return out

    # Bbox helpers
    def _bbox_abs_from_docling(bbox):
        return {'x0': float(bbox.get('l',0)),'y0': float(bbox.get('b',0)),'x1': float(bbox.get('r',0)),'y1': float(bbox.get('t',0)),'coord_origin': str(bbox.get('coord_origin') or 'BOTTOMLEFT')}

    def _norm_bbox(absb, w, h):
        return {'x0': max(0, min(1, absb['x0']/w)),'y0': max(0, min(1, absb['y0']/h)),'x1': max(0, min(1, absb['x1']/w)),'y1': max(0, min(1, absb['y1']/h))}

    # Extract elements
    def _extract_elements(raw, dims, src):
        out = []
        texts = raw.get('texts') if raw else []

        if not texts:
            try:
                full_text = extract_text(src)
                for i, line in enumerate(full_text.splitlines()):
                    page_no = 1
                    w,h = dims[page_no]['w'], dims[page_no]['h']
                    abs_bbox = {'x0':0,'y0':i*10,'x1':w,'y1':(i+1)*10,'coord_origin':'BOTTOMLEFT'}
                    norm = _norm_bbox(abs_bbox,w,h)
                    out.append({'page_number':page_no,'element_type':'text','text':line.strip(),'bbox_abs':abs_bbox,'bbox_norm':norm,'is_form_field_candidate':_is_form_blank(line)})
            except Exception:
                pass
            return out

        for t in texts:
            text_val = t.get('text') or t.get('orig')
            label = t.get('label') or t.get('type') or 'text'
            prov = t.get('prov')
            if not (isinstance(prov,list) and prov):
                continue
            p0 = prov[0]
            page_no = p0.get('page_no')
            bbox = p0.get('bbox')
            if page_no is None or not isinstance(bbox, dict) or int(page_no) not in dims:
                continue
            d = dims[int(page_no)]
            abs_bbox = _bbox_abs_from_docling(bbox)
            norm = _norm_bbox(abs_bbox,d['w'],d['h'])
            out.append({'page_number':int(page_no),'element_type':label,'text':text_val,'bbox_abs':abs_bbox,'bbox_norm':norm,'is_form_field_candidate':_is_form_blank(text_val)})
        return out

    simulated_mode = input_data.get('simulated_mode', False)
    
    if simulated_mode:
        # Return mock result for testing
        return {
            'status': 'success',
            'content': {
                'document_metadata': {
                    'file_name': os.path.basename(input_data.get('file_path', 'test.pdf')),
                    'mimetype': 'application/pdf',
                    'docling_version': '1.7.0'
                },
                'pages': [{'page_number': 1, 'width': 595.44, 'height': 841.68}],
                'elements': [{'page_number': 1, 'element_type': 'text', 'text': 'Test PDF content'}]
            },
            'message': ''
        }
    
    # Main execution
    try:
        src = str(input_data.get('file_path', '')).strip()
        if not src:
            return _json('error', "'file_path' is required.")
        if '..' in src.replace('\\', '/'):
            return _json('error', 'Invalid file path.')
        if not os.path.isfile(src):
            return _json('error', 'File does not exist.')
        if not os.access(src, os.R_OK):
            return _json('error', 'File is not readable.')
        ext = os.path.splitext(src)[1].lower()
        if ext not in SAFE_EXTS:
            return _json('error', f"Unsupported file type '{ext}'. Only PDF allowed.")
        size_mb = os.path.getsize(src) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            return _json('error', f'File too large ({size_mb:.1f} MB). Max {MAX_FILE_SIZE_MB} MB.')

        raw = None
        try:
            conv = DocumentConverter()
            result = conv.convert(src)
            if result.status == 'success':
                raw = result.document.export_to_dict()
        except Exception:
            pass

        pages = _extract_pages(raw, src)
        dims = _page_dims_map(pages)
        elements = _extract_elements(raw, dims, src)

        origin = raw.get('origin') if raw else {}
        meta = {'file_name': origin.get('filename') or os.path.basename(src), 'mimetype': origin.get('mimetype') or 'application/pdf', 'docling_version': raw.get('version') if raw else None}

        payload = {'document_metadata': _deep_sanitize(meta), 'pages': _deep_sanitize(pages), 'elements': _deep_sanitize(elements)}

        return _json('success', 'PDF extracted successfully.', payload)
    except Exception as e:
        return _json('error', str(e))