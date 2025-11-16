import re
import time
import mmap
from io import BytesIO
import zlib

class PDFBytewiseParser:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.current_object = bytearray()
        self.extracted_text = []
        self.in_content_stream = False
        self.font_map = {}  # To store font encoding information if needed

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
                    if i + 9 < length and mm[i:i+9] == b'stream\r\n' or mm[i:i+7] == b'stream\n':
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

    def process_content_stream(self, content):
        """Process a content stream to extract text"""
        # Create a memory buffer for efficient processing
        buffer = BytesIO(content)
        data = buffer.read()
        
        # Use regex to find TJ and Tj operators and their arguments
        # This is more efficient than byte-by-byte processing
        
        # Find TJ operations - array of strings: [(...)Tj]
        tj_pattern = re.compile(rb'\[(.*?)\]\s*TJ')
        for match in tj_pattern.finditer(data):
            array_content = match.group(1)
            # Extract text parts from the array
            text_parts = re.findall(rb'[(](.*?)[)]', array_content)
            for text_part in text_parts:
                decoded_text = self.decode_pdf_string(text_part)
                if decoded_text.strip():
                    self.extracted_text.append(decoded_text)
            
            # Add space between TJ operations as they often represent words
            if self.extracted_text and self.extracted_text[-1] != ' ':
                self.extracted_text.append(' ')
        
        # Find Tj operations - single string: (...)Tj
        tj_single_pattern = re.compile(rb'[(](.*?)[)]\s*Tj')
        for match in tj_single_pattern.finditer(data):
            text = match.group(1)
            decoded_text = self.decode_pdf_string(text)
            if decoded_text.strip():
                self.extracted_text.append(decoded_text)
                # Add space after each Tj operation
                self.extracted_text.append(' ')

    def decode_pdf_string(self, byte_string):
        """Decode PDF string objects considering character encoding"""
        # Basic decoding of PDF strings
        result = ""
        i = 0
        length = len(byte_string)
        
        while i < length:
            if byte_string[i:i+1] == b'\\':
                # Handle escape sequences
                if i + 1 < length:
                    next_char = byte_string[i+1:i+2]
                    if next_char == b'n':
                        result += '\n'
                    elif next_char == b'r':
                        result += '\r'
                    elif next_char == b't':
                        result += '\t'
                    elif next_char == b'b':
                        result += '\b'
                    elif next_char == b'f':
                        result += '\f'
                    elif next_char == b'(':
                        result += '('
                    elif next_char == b')':
                        result += ')'
                    elif next_char == b'\\':
                        result += '\\'
                    elif next_char in b'0123':
                        # Octal character code
                        if i + 3 < length and byte_string[i+1:i+4].isdigit():
                            char_code = int(byte_string[i+1:i+4], 8)
                            result += chr(char_code)
                            i += 3
                        else:
                            result += '\\'
                    else:
                        result += '\\'
                    i += 2
                    continue
            
            # Regular character
            try:
                # Try UTF-8 first
                result += byte_string[i:i+1].decode('utf-8')
            except UnicodeDecodeError:
                # Fall back to latin-1 which can decode any byte
                result += byte_string[i:i+1].decode('latin-1')
            i += 1
                
        return result

    def convert_to_asciidoc(self, output_path=None):
        """Convert the extracted text to an AsciiDoc file"""
        if output_path is None:
            output_path = self.pdf_path.rsplit('.', 1)[0] + '.adoc'
        
        text = ''.join(self.extracted_text)
        
        # Basic text cleanup for AsciiDoc
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Split into paragraphs based on empty lines or significant spacing
        paragraphs = re.split(r'\n\s*\n', text)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            # Add AsciiDoc header
            f.write(f"= {self.pdf_path.rsplit('/', 1)[-1].rsplit('.', 1)[0]}\n")
            f.write(":doctype: book\n")
            f.write(":toc: left\n\n")
            
            # Write paragraphs
            for paragraph in paragraphs:
                if paragraph.strip():
                    f.write(paragraph.strip() + "\n\n")
        
        return output_path

# Example usage
if __name__ == "__main__":
    parser = PDFBytewiseParser("examples/PdfParserTestDoc.pdf")
    text = parser.parse()
    asciidoc_file = parser.convert_to_asciidoc()
    print(f"Extracted {len(text)} characters of text")
    print(f"AsciiDoc file created: {asciidoc_file}")
