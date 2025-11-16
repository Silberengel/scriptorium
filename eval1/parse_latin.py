from PyPDF2 import PdfReader

def read():

    reader = PdfReader("/home/madmin/Projects/GitCitadel/Scriptorium/docs/pdfreference1.7old.pdf")
    number_of_pages = len(reader.pages)


    # TEXT
    page = reader.pages[996]
    text_1 = page.extract_text()

    page = reader.pages[997]
    text_2 = page.extract_text()

    page = reader.pages[998]
    text_3 = page.extract_text()

    page = reader.pages[999]
    text_4 = page.extract_text()
    
    text = "------------------- PAGE -----------------".join([text_1,text_2,text_3,text_4])

    print(text)
    with open("latin_encodings_p4.txt", "w") as f:
        f.write(text)


def evaluate_clean():
    csv_lines = []
    with open("/home/madmin/Projects/GitCitadel/Scriptorium/latin_encodings_clean.txt", "r") as f:
        lines = f.readlines()
        for line in lines:
            c = line[0]
            if line=='\n':
                continue
            oct_txt = line.rsplit(" ",1)[1]            
            val_int = int(oct_txt, 8)            
            #val_oct = int(line.rsplit(" ",1)[1])
            #val_hex = hex(val_oct)
            #print(c, val_oct, val_hex)
            csv_lines.append(c+"||"+str(val_int))

    with open("/home/madmin/Projects/GitCitadel/Scriptorium/latin_encodings_table.csv", "w") as f:
        f.write("\n".join(csv_lines))

evaluate_clean()