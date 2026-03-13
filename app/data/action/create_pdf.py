from agent_core import action

@action(
    name="create_pdf",
    description="Creates a PDF file at the specified path using the provided Markdown content. Converts Markdown to PDF using fpdf2, preserving headings, paragraphs, lists, bold and italic formatting. Use absolute paths.",
    mode="CLI",
    action_sets=["document_processing"],
    input_schema={
        "file_path": {
            "type": "string",
            "example": "C:/Users/user/Documents/my_file.pdf",
            "description": "Absolute path where the new PDF file will be created. Use full absolute paths (e.g., C:/Users/user/file.pdf or /home/user/file.pdf). Ensure the directory exists and is writable."
        },
        "content": {
            "type": "string",
            "example": "# My Title\n\nThis is a paragraph with **bold** text and a bullet list:\n- Item 1\n- Item 2",
            "description": "The Markdown-formatted content to be converted into a PDF file. Supports headings (#, ##, etc.), paragraphs, bullet lists (-, *), numbered lists (1., 2.), bold (**text**), and italics (*text*)."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if the file was created, 'error' otherwise."
        },
        "path": {
            "type": "string",
            "example": "C:/Users/user/Documents/my_file.pdf",
            "description": "The path to the newly created PDF file."
        },
        "message": {
            "type": "string",
            "example": "Permission denied.",
            "description": "Error message, present only if status is 'error'."
        }
    },
    requirement=["markdown2", "FPDF", "fpdf2"],
    test_payload={
        "file_path": "C:/Users/user/Documents/my_file.pdf",
        "content": "# My Title\n\nThis is a paragraph with **bold** text and a bullet list:\n- Item 1\n- Item 2",
        "simulated_mode": True
    }
)
def create_pdf_file(input_data: dict) -> dict:
    import json,sys,subprocess,importlib,os
    def _ensure(pkg):
        try:
            importlib.import_module(pkg)
        except ImportError:
            subprocess.check_call([sys.executable,"-m","pip","install",pkg,"--quiet"])
    [_ensure(p) for p in ("markdown2","fpdf2")]
    import markdown2
    from fpdf import FPDF,HTMLMixin
    class PDF(FPDF,HTMLMixin):
        pass

    simulated_mode = input_data.get('simulated_mode', False)
    
    file_path = str(input_data.get("file_path", "")).strip()
    content = str(input_data.get("content", "")).strip()
    
    if not file_path:
        return {"status": "error", "path": "", "message": "The 'file_path' field is required."}
    if not content:
        return {"status": "error", "path": "", "message": "The 'content' field is required."}
    
    if simulated_mode:
        # Return mock result for testing
        return {"status": "success", "path": file_path}
    
    try:
        html_content = markdown2.markdown(content)
        pdf = PDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.write_html(html_content)
        pdf.output(file_path)
        return {"status": "success", "path": file_path}
    except Exception as e:
        return {"status": "error", "path": "", "message": str(e)}