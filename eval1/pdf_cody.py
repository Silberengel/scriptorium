import re
import zlib
import mmap
import time
import os
from pathlib import Path


class State:
    """Represents a state in the PDF parsing state machine"""
    
    def __init__(self, marker, objtype, signalwords, parent=None):
        self.marker = marker
        self.objtype = objtype
        self.signalwords = signalwords
        self.parent = parent
        self.children = []
        self.content = ""
        
    def add(self, child):
        self.children.append(child)


class PDFToAsciiDocConverter:
    """Converts PDF files to AsciiDoc format"""
    
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.extracted_text = []
        self.current_font = None
        self.text_handlers = {
            b'Tj': self.handle_text_element,
            b'TJ': self.handle_text_array
        }
    
    def handle_text_element(self, content):
        """Extract text from a Tj operator"""
        if content.startswith(b'(') and content.endswith(b')'):
            text = content[1:-1].decode('latin-1', errors='replace')
            # Handle basic PDF string escapes
            text = text.replace('\\(', '(').replace('\\)', ')').replace('\\\\', '\\')
            self.extracted_text.append(text)
    
    def handle_text_array(self, content):
        """Extract text from a TJ operator (array of strings and positioning)"""
        if content.startswith(b'[') and content.endswith(b']'):
            # Simple parsing of TJ array - extract only the strings
            parts = content[1:-1].split(b'(')
            for part in parts[1:]:  # Skip the first part (before first parenthesis)
                if b')' in part:
                    text_part = part.split(b')')[0].decode('latin-1', errors='replace')
                    # Handle basic PDF string escapes
                    text_part = text_part.replace('\\(', '(').replace('\\)', ')').replace('\\\\', '\\')
                    self.extracted_text.append(text_part)
    
    def process_content_stream(self, stream_content):
        """Process a content stream to extract text"""
        # Convert bytes to string for easier regex processing
        content_str = stream_content.decode('latin-1', errors='replace')
        
        # Find all text showing operators (Tj and TJ)
        tj_pattern = r'\(([^\)\\]*(?:\\.[^\)\\]*)*)\)\s+Tj'
        TJ_pattern = r'\[((?:\([^\)\\]*(?:\\.[^\)\\]*)*\)|[^[]*)*)\]\s+TJ'
        
        # Extract text from Tj operators
        for match in re.finditer(tj_pattern, content_str):
            text = match.group(1)
            # Handle basic PDF string escapes
            text = text.replace('\\(', '(').replace('\\)', ')').replace('\\\\', '\\')
            self.extracted_text.append(text)
        
        # Extract text from TJ operators
        for match in re.finditer(TJ_pattern, content_str):
            array_content = match.group(1)
            # Extract strings from the array
            string_pattern = r'\(([^\)\\]*(?:\\.[^\)\\]*)*)\)'
            for string_match in re.finditer(string_pattern, array_content):
                text = string_match.group(1)
                # Handle basic PDF string escapes
                text = text.replace('\\(', '(').replace('\\)', ')').replace('\\\\', '\\')
                self.extracted_text.append(text)
    
    def parse(self):
        """Parse the PDF file bytewise and extract text from TJ and Tj operators"""
        start_time = time.time()
        
        # Use memory mapping for efficient file access
        with open(self.pdf_path, 'rb') as f:
            # Memory-map the file for faster access
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                i = 0
                length = len(mm)
                
                while i < length:
                    # Look for content stream markers
                    if i + 9 < length and mm[i:i+9] == b'stream\r\n' or i + 7 < length and mm[i:i+7] == b'stream\n':
                        # Handle the stream start
                        stream_start = i + (9 if mm[i:i+9] == b'stream\r\n' else 7)
                        # Find the end of the stream
                        endstream_pos = mm.find(b'endstream', stream_start)
                        if endstream_pos != -1:
                            # Extract and process the stream content
                            stream_content = mm[stream_start:endstream_pos]
                            try:
                                # Try to decompress (assuming it might be compressed)
                                decompressed = zlib.decompress(stream_content)
                                self.process_content_stream(decompressed)
                            except zlib.error:
                                # If decompression fails, it might be an uncompressed stream
                                self.process_content_stream(stream_content)
                            
                            # Skip to after endstream
                            i = endstream_pos + 10
                            continue
                    
                    # If we're not processing a stream, just move forward
                    i += 1
        
        end_time = time.time()
        print(f"Parsing completed in {end_time - start_time:.2f} seconds")
        return ''.join(self.extracted_text)
    
    def clean_text_for_asciidoc(self, text):
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
    
    def convert_to_asciidoc(self):
        """Convert PDF to AsciiDoc format"""
        raw_text = self.parse()
        
        # Post-process the text to make it more readable
        processed_text = raw_text
        
        # Replace common ligatures
        ligature_map = {
            'ﬁ': 'fi',
            'ﬂ': 'fl',
            'ﬀ': 'ff',
            'ﬃ': 'ffi',
            'ﬄ': 'ffl'
        }
        for lig, replacement in ligature_map.items():
            processed_text = processed_text.replace(lig, replacement)
        
        # Add paragraph breaks where appropriate
        processed_text = re.sub(r'([.!?])\s+([A-Z])', r'\1\n\n\2', processed_text)
        
        # Clean and format for AsciiDoc
        asciidoc_text = self.clean_text_for_asciidoc(processed_text)
        
        # Add document title
        pdf_filename = os.path.basename(self.pdf_path)
        title = f"= {pdf_filename}\n\n"
        
        return title + asciidoc_text


def convert_pdf_to_asciidoc(pdf_path, output_path=None):
    """Convert a PDF file to AsciiDoc format"""
    converter = PDFToAsciiDocConverter(pdf_path)
    asciidoc_content = converter.convert_to_asciidoc()
    
    if output_path is None:
        # Default output path: same directory, same name but with .adoc extension
        output_path = str(Path(pdf_path).with_suffix('.adoc'))
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(asciidoc_content)
    
    print(f"Conversion complete. AsciiDoc file saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    # Convert the test document
    pdf_path = "examples/PdfParserTestDoc.pdf"
    output_path = convert_pdf_to_asciidoc(pdf_path)
    print(f"Successfully converted {pdf_path} to {output_path}")