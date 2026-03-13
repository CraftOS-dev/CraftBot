from agent_core import action

@action(
    name="convert_to_markdown",
    description="Cleans scraped text from .txt, .md, or .docx and converts it into clean, well-structured Markdown suitable for PDF conversion. Use absolute paths.",
    mode="CLI",
    action_sets=["document_processing"],
    input_schema={
        "input_file": {
            "type": "string",
            "example": "C:/Users/user/Documents/input.txt",
            "description": "Absolute path to the input file (txt, md, docx). Use full absolute paths (e.g., C:/Users/user/file.txt or /home/user/file.txt)."
        },
        "output_md": {
            "type": "string",
            "example": "C:/Users/user/Documents/output.md",
            "description": "Absolute path where the cleaned Markdown file will be saved."
        }
    },
    output_schema={
        "md_file": {
            "type": "string",
            "example": "C:/Users/user/Documents/output.md",
            "description": "Path to the generated Markdown file."
        }
    },
    requirement=["Document", "docx"],
    test_payload={
        "input_file": "C:/Users/user/Documents/input.txt",
        "output_md": "C:/Users/user/Documents/output.md",
        "simulated_mode": True
    }
)
def clean_to_md(input_data: dict) -> dict:
    import os, sys, json, subprocess, importlib, re

    # Ensure required libraries
    for pkg in ['python-docx']:
        try:
            importlib.import_module(pkg.replace('-', '_'))
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])

    from docx import Document

    def read_input_file(path):
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.txt', '.md']:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        if ext == '.docx':
            doc = Document(path)
            return '\n'.join(p.text for p in doc.paragraphs)
        raise ValueError('Unsupported input file type.')

    def normalize_headings(text):
        # Convert lines in ALL CAPS into Markdown H2
        lines = text.split('\n')
        out = []
        for line in lines:
            stripped = line.strip()
            if stripped.isupper() and len(stripped.split()) <= 6:
                out.append('## ' + stripped)
            else:
                out.append(line)
        return '\n'.join(out)

    def fix_lists(text):
        # Clean bullet points like '-', '*', '•'
        text = re.sub(r'^[\s]*[\-*•][\s]+', '- ', text, flags=re.MULTILINE)
        # Fix numbered lists
        text = re.sub(r'^[\s]*\d+[\.)]\s+', lambda m: f"{m.group(0).strip()} ", text, flags=re.MULTILINE)
        return text

    def clean_text(text):
        # Remove inline references [1], [2]
        text = re.sub(r'\[\d+\]', '', text)
        # Remove URLs inside brackets e.g. [src]
        text = re.sub(r'\[[^\]]*?src[^\]]*?\]', '', text, flags=re.IGNORECASE)
        # Remove extra spaces
        text = re.sub(r' {2,}', ' ', text)
        # Remove non-ASCII artifacts
        text = re.sub(r'[^\x00-\x7F]+', '', text)
        # Merge single line breaks into spacing
        text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
        # Ensure blank line between paragraphs
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = normalize_headings(text)
        text = fix_lists(text)
        return text.strip() + '\n'

    def save_as_md(cleaned_text, output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(cleaned_text)
        return output_path

    simulated_mode = input_data.get('simulated_mode', False)
    
    if simulated_mode:
        # Return mock result for testing
        output_md = input_data.get('output_md') or '/path/to/output.md'
        return {'status': 'success', 'md_file': output_md}
    
    try:
        input_file = input_data.get('input_file')
        output_md = input_data.get('output_md')

        if not input_file or not os.path.isfile(input_file):
            return {'status': 'error', 'md_file': '', 'message': 'Valid input_file required.'}
        else:
            if not output_md:
                base, _ = os.path.splitext(input_file)
                output_md = base + '_clean.md'

            raw_text = read_input_file(input_file)
            cleaned_text = clean_text(raw_text)
            result = save_as_md(cleaned_text, output_md)
            return {'status': 'success', 'md_file': result}
    except Exception as e:
        return {'status': 'error', 'md_file': '', 'message': str(e)}