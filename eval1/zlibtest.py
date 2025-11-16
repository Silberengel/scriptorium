import re
import zlib
import sys

file = "examples/PdfParserTestDoc.pdf"
pdf = open(file, "rb").read()
stream = re.compile(rb'.*?FlateDecode.*?stream(.*?)endstream', re.S)

for s in stream.findall(pdf)[:5]:
    s = s.strip(b'\r\n')
    try:
        print("---- ORIGIAL: ----------------------")
        print(s)
        print("---- DECOMPRESSED: ----------------------")
        print(zlib.decompress(s))
        print("---- END ----------------------")
    except Exception as ex:
        print(ex)
        pass