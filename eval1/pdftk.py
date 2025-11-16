import os

# install sudo apt pdftk-java

ret = os.system("pdftk ct-2022-05.pdf output ct-2022-05-uncompressed.txt uncompress")
#ret = os.system("pdftk ct-2022-05.pdf dump_data output ct-2022-05-report.txt")

