import os
import PyPDF2
import re

def pdf_to_asciidoc(pdf_path, output_path=None):
    """
    Convert a PDF file to an AsciiDoc file.
    
    Args:
        pdf_path (str): Path to the PDF file
        output_path (str, optional): Path for the output AsciiDoc file. 
                                     If None, uses the PDF name with .adoc extension
    
    Returns:
        str: Path to the created AsciiDoc file
    """
    # Set the output path if not provided
    if output_path is None:
        base_name = os.path.splitext(pdf_path)[0]
        output_path = f"{base_name}.adoc"
    
    # Extract text from the PDF
    text = extract_text_from_pdf(pdf_path)
    
    # Clean up the text for AsciiDoc format
    cleaned_text = clean_text_for_asciidoc(text)
    
    # Write to AsciiDoc file
    with open(output_path, 'w', encoding='utf-8') as adoc_file:
        # Add a basic AsciiDoc header
        adoc_file.write(f"= {os.path.basename(os.path.splitext(pdf_path)[0])}\n")
        adoc_file.write(":doctype: book\n")
        adoc_file.write(":toc: left\n")
        adoc_file.write(":toclevels: 3\n\n")
        
        # Write the content
        adoc_file.write(cleaned_text)
    
    return output_path

def extract_text_from_pdf(pdf_path):
    """Extract text from all pages of a PDF file"""
    text = ""
    
    with open(pdf_path, 'rb') as file:
        pdf_reader = PyPDF2.PdfReader(file)
        
        # Extract text from each page
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            text += page.extract_text() + "\n"
    
    return text

def clean_text_for_asciidoc(text):
    """Clean the extracted text for AsciiDoc format"""
    # Remove multiple spaces
    text = re.sub(r' +', ' ', text)
    
    # Remove multiple newlines (preserve paragraphs)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Try to identify headings (this is a simple heuristic)
    lines = text.split('\n')
    result = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Simple heuristic: short lines that don't end with punctuation 
        # and are followed by blank lines might be headings
        if (len(stripped) > 0 and len(stripped) < 80 and 
            not stripped[-1] in '.,:;?!' and 
            (i == len(lines)-1 or not lines[i+1].strip())):
            # Mark as heading level 2
            if stripped.isupper():  # Likely a chapter heading
                result.append(f"== {stripped.title()}")
            else:
                result.append(f"=== {stripped}")
        else:
            result.append(line)
            
    return '\n'.join(result)

if __name__ == "__main__":
    # Example usage
    pdf_file = "example.pdf"
    output_file = pdf_to_asciidoc(pdf_file)
    print(f"AsciiDoc file created: {output_file}")