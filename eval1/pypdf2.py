from PyPDF2 import PdfReader


reader = PdfReader("examples/ct-2022-05.pdf")
number_of_pages = len(reader.pages)
page = reader.pages[16]

# TEXT
text = page.extract_text()
print(text)

# IMAGES
count=0
for image_file_object in page.images:
    with open(str(count) + image_file_object.name, "wb") as fp:
        fp.write(image_file_object.data)
        count += 1

# BOOKMARKS and OUTLINES

