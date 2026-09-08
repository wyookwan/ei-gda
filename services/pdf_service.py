import fitz


def extract_pages_from_pdf(pdf_path: str):
    """Extract text page-by-page while preserving 1-based page numbers."""
    pages = []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            pages.append({
                'page': index,
                'text': page.get_text('text') or ''
            })
    return pages


def extract_text_from_pdf(pdf_path: str) -> str:
    """Backward-compatible full-document extraction."""
    return '\n'.join(x['text'] for x in extract_pages_from_pdf(pdf_path))


def combine_documents_for_analysis(document_files, json_loader):
    """Create a source-aware text stream for LLM/rule processing."""
    parts = []
    for doc_file in document_files:
        pages = json_loader(doc_file.pages_json, default=[])
        if not pages and doc_file.extracted_text:
            pages = [{'page': 1, 'text': doc_file.extracted_text}]
        for page in pages:
            parts.append(
                f"\n[SOURCE_FILE: {doc_file.original_filename}]\n"
                f"[PAGE: {page.get('page', 1)}]\n"
                f"{page.get('text', '')}"
            )
    return '\n'.join(parts)
