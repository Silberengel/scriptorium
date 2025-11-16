import os


from state import State
from handlers import ObjectHandler, StreamHandler, DictionaryHandler, TextblockHandler,TextElementHandler, TextArrayHandler, TcHandler, TDHandler
from run import run

def initialize() -> State:

    ObjectHandler.set_routing([
        StreamHandler
        ])
    StreamHandler.set_routing([
        DictionaryHandler,
        TextblockHandler
        ])
    TextblockHandler.set_routing([
        DictionaryHandler, 
        TextElementHandler, 
        TextArrayHandler
        ])
    DictionaryHandler.set_routing([
        DictionaryHandler,
        ])
    TextArrayHandler.set_routing([

    ])
    TextElementHandler.set_routing([
        
    ])
    
    root_signalwords = ObjectHandler.signalwords_entry()
    root_state = State("root", "Root", root_signalwords , None)
    return root_state

if __name__=="__main__":
    print(os.getcwd())
    file_name = "examples/VerySimple2.pdf"
    #file_name = "examples/maxwell_equations_uncompressed.txt"
    #file_name = "examples/PdfParserTestDocUncompressed.txt"

    with open(file_name,"rb") as f:            
        content = f.read() 

    root_state = initialize()
    run(content, root_state)
