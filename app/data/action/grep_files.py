from agent_core import action

# Common output schema for all platforms
_OUTPUT_SCHEMA = {
    "status": {
        "type": "string",
        "example": "success",
        "description": "'success' or 'error'."
    },
    "message": {
        "type": "string",
        "example": "Found 5 matching chunks",
        "description": "Status message or error description."
    },
    "chunks": {
        "type": "array",
        "example": [
            "[line 275] ...some text chunk...",
            "[line 937] ...another text chunk..."
        ],
        "description": "List of formatted chunks for the requested range."
    },
    "total_matches": {
        "type": "integer",
        "example": 23,
        "description": "Total number of matched chunks available."
    },
    "returned_range": {
        "type": "array",
        "example": [1, 5],
        "description": "The 1-based [start, end] chunk indices that were requested (clamped to available matches)."
    }
}

# Common input schema for all platforms
_INPUT_SCHEMA = {
    "input_file": {
        "type": "string",
        "example": "/path/to/input.txt",
        "description": "Absolute path to the input text file to search."
    },
    "keywords": {
        "type": "array",
        "example": ["Mt. Fuji", "visibility"],
        "description": "List of plain-text keywords to search for (OR-ed together, case-insensitive).",
        "default": []
    },
    "chunk_size": {
        "type": "integer",
        "example": 300,
        "description": "Approximate number of words per chunk.",
        "default": 300
    },
    "overlap": {
        "type": "integer",
        "example": 50,
        "description": "Number of overlapping words between consecutive chunks.",
        "default": 50
    },
    "chunk_start": {
        "type": "integer",
        "example": 1,
        "description": "1-based start index of the matched chunk range to return.",
        "default": 1
    },
    "chunk_end": {
        "type": "integer",
        "example": 5,
        "description": "1-based end index of the matched chunk range to return.",
        "default": 5
    }
}


@action(
    name="grep_files",
    description="Searches a text file for keywords and returns matching chunks with pagination.",
    mode="CLI",
    platforms=["linux", "windows", "darwin"],
    action_sets=["core"],
    input_schema=_INPUT_SCHEMA,
    output_schema=_OUTPUT_SCHEMA,
    test_payload={
        "input_file": "/path/to/input.txt",
        "keywords": ["Mt. Fuji", "visibility"],
        "chunk_size": 300,
        "overlap": 50,
        "chunk_start": 1,
        "chunk_end": 5,
        "simulated_mode": True
    }
)
def grep_files(input_data: dict) -> dict:
    """Searches a text file for keywords and returns matching chunks with pagination."""
    import os
    import re

    def chunk_text(text, chunk_size=300, overlap=50):
        """Split text into overlapping word chunks."""
        words = re.findall(r'\S+', text or '')
        if not words:
            return []
        if chunk_size <= 0:
            chunk_size = 300
        if overlap < 0:
            overlap = 0
        step = max(1, chunk_size - overlap)
        n = len(words)
        segments = []
        for start in range(0, n, step):
            end = min(start + chunk_size, n)
            chunk_words = words[start:end]
            if not chunk_words:
                break
            chunk_text_val = ' '.join(chunk_words).strip()
            if not chunk_text_val:
                continue
            has_leading = start > 0
            has_trailing = end < n
            segments.append({
                'text': chunk_text_val,
                'start_word_index': start + 1,
                'has_leading_ellipsis': bool(has_leading),
                'has_trailing_ellipsis': bool(has_trailing)
            })
        return segments

    simulated_mode = input_data.get('simulated_mode', False)

    if simulated_mode:
        return {
            'status': 'success',
            'message': 'Found 1 matching chunk(s)',
            'chunks': ['[line 10] Test chunk with keyword'],
            'total_matches': 1,
            'returned_range': [1, 5]
        }

    try:
        input_file = input_data.get('input_file')
        if not input_file:
            return {
                'status': 'error',
                'message': 'input_file is required',
                'chunks': [],
                'total_matches': 0,
                'returned_range': [0, 0]
            }

        if not os.path.isfile(input_file):
            return {
                'status': 'error',
                'message': f'Input file does not exist: {input_file}',
                'chunks': [],
                'total_matches': 0,
                'returned_range': [0, 0]
            }

        keywords = input_data.get('keywords') or []
        if not keywords:
            return {
                'status': 'error',
                'message': 'keywords must be a non-empty array',
                'chunks': [],
                'total_matches': 0,
                'returned_range': [0, 0]
            }

        try:
            chunk_size = int(input_data.get('chunk_size', 300))
        except (TypeError, ValueError):
            chunk_size = 300
        try:
            overlap = int(input_data.get('overlap', 50))
        except (TypeError, ValueError):
            overlap = 50
        try:
            start_idx = int(input_data.get('chunk_start', 1))
        except (TypeError, ValueError):
            start_idx = 1
        try:
            end_idx = int(input_data.get('chunk_end', 5))
        except (TypeError, ValueError):
            end_idx = 5

        # Normalize values
        if chunk_size <= 0:
            chunk_size = 300
        if overlap < 0:
            overlap = 0
        if start_idx < 1:
            start_idx = 1
        if end_idx < 1:
            end_idx = 1
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx

        with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        segments = chunk_text(content, chunk_size=chunk_size, overlap=overlap)

        if not segments:
            return {
                'status': 'success',
                'message': 'File is empty or has no content',
                'chunks': [],
                'total_matches': 0,
                'returned_range': [start_idx, end_idx]
            }

        pattern = re.compile('(' + '|'.join(re.escape(k) for k in keywords) + ')', re.I)
        matched_segments = [s for s in segments if pattern.search(s['text'])]

        total_matches = len(matched_segments)
        if total_matches == 0:
            return {
                'status': 'success',
                'message': 'No matches found for the given keywords',
                'chunks': [],
                'total_matches': 0,
                'returned_range': [start_idx, end_idx]
            }

        start_idx_clamped = max(1, min(start_idx, total_matches))
        end_idx_clamped = max(1, min(end_idx, total_matches))
        if end_idx_clamped < start_idx_clamped:
            start_idx_clamped, end_idx_clamped = end_idx_clamped, start_idx_clamped

        start_zero = start_idx_clamped - 1
        end_zero_excl = end_idx_clamped

        page_segments = matched_segments[start_zero:end_zero_excl]

        def clean_text(s):
            s = s.strip()
            s = re.sub(r'\s+', ' ', s)
            return s

        formatted_chunks = []
        for seg in page_segments:
            text_clean = clean_text(seg['text'])
            if not text_clean:
                continue
            display_text = text_clean
            if seg.get('has_leading_ellipsis'):
                display_text = '...' + display_text
            if seg.get('has_trailing_ellipsis'):
                if not display_text.endswith('...'):
                    display_text = display_text + '...'
            line_no = int(seg.get('start_word_index', 1))
            para = f"[line {line_no}] {display_text}"
            formatted_chunks.append(para)

        return {
            'status': 'success',
            'message': f'Found {total_matches} matching chunk(s)',
            'chunks': formatted_chunks,
            'total_matches': total_matches,
            'returned_range': [start_idx_clamped, end_idx_clamped]
        }

    except Exception as e:
        return {
            'status': 'error',
            'message': str(e),
            'chunks': [],
            'total_matches': 0,
            'returned_range': [0, 0]
        }
