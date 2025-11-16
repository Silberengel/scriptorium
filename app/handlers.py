import zlib

from state import State
from run import run

class ObjectHandler():

    signalwords = []

    @staticmethod
    def set_routing(substates=[]):
        ObjectHandler._set_exit()
        ObjectHandler._set_substates(substates)
    
    @staticmethod
    def _set_exit():
        ObjectHandler.signalwords += ObjectHandler.signalwords_exit()        

    @staticmethod
    def _set_substates(substates=[]):        
        for substate in substates:
            ObjectHandler.signalwords += substate.signalwords_entry()
        for signalword in ObjectHandler.signalwords:
            print(f"Signalword: {signalword[0]}")


    @staticmethod
    def enter(current_state):
        return State("obj", "Object", ObjectHandler.signalwords, current_state)

    @staticmethod
    def exit(current_state):
        return current_state.parent

    @staticmethod
    def signalwords_entry():
        return [["obj", ObjectHandler.enter]]

    @staticmethod
    def signalwords_exit():
        return [["endobj",ObjectHandler.exit]]


class StreamHandler():

    signalwords = []  
    
    @staticmethod
    def set_routing(substates=[]):
        StreamHandler._set_exit()
        StreamHandler._set_substates(substates)

    @staticmethod
    def _set_exit():
        StreamHandler.signalwords += StreamHandler.signalwords_exit()
    
    @staticmethod
    def _set_substates(substates=[]):
        for substate in substates:
            StreamHandler.signalwords += substate.signalwords_entry()
        for signalword in StreamHandler.signalwords:
            print(f"Signalword: {signalword[0]}")

    @staticmethod
    def enter(current_state):    
        new_state = State("stream", "Stream", StreamHandler.signalwords, current_state, None)
        new_state.FlatDecode = True
        return new_state

    @staticmethod
    def exit(current_state):
        
        #try:
        #    # Try to decompress (assuming it might be compressed)
        #    content = zlib.decompress(current_state.content.encode())            
        #except zlib.error as e:
        #    # If decompression fails, it might be an uncompressed stream
        #    print(e)
        #    content = current_state.content        
        #print(content)
        try:
            uncompressed = zlib.decompress(current_state.compressed[:-9])
            ret = uncompressed.decode("latin-1")
            print(ret)
        except Exception as ex:
            print(ex)
            print(current_state.compressed)
        run(content, current_state)
        return current_state.parent

    @staticmethod
    def signalwords_entry():
        return [["stream", StreamHandler.enter]]

    @staticmethod
    def signalwords_exit():
        return [["endstream",StreamHandler.exit]]


class TextblockHandler():

    signalwords = []

    @staticmethod
    def set_routing(substates=[]):
        TextblockHandler._set_exit()
        TextblockHandler._set_substates(substates)  
    
    @staticmethod
    def _set_exit():
        TextblockHandler.signalwords += TextblockHandler.signalwords_exit()
        
    @staticmethod
    def _set_substates(substates=[]):        
        for substate in substates:
            TextblockHandler.signalwords += substate.signalwords_entry()
        #print("TextblockHandler Signalwords:")
        #for signalword in TextblockHandler.signalwords:
        #    print(f"Signalword: {signalword[0]}, Entry-Function: {signalword[1]}")

    @staticmethod
    def enter(current_state):
        return State("BT", "Textblock", TextblockHandler.signalwords, current_state, PdfTextEncoder())

    @staticmethod
    def exit(current_state):
        return current_state.parent

    @staticmethod
    def signalwords_entry():
        return [["BT", TextblockHandler.enter]]

    @staticmethod
    def signalwords_exit():
        return [["ET",TextblockHandler.exit]]


class DictionaryHandler():

    signalwords = []  
    
    @staticmethod
    def set_routing(substates=[]):
        DictionaryHandler._set_exit()
        DictionaryHandler._set_substates(substates)

    @staticmethod
    def _set_exit():
        DictionaryHandler.signalwords += DictionaryHandler.signalwords_exit()
        
    @staticmethod
    def _set_substates(substates=[]):
        for substate in substates:
            DictionaryHandler.signalwords += substate.signalwords_entry()

    @staticmethod
    def enter(current_state):
        return State("<<", "Dictionary", DictionaryHandler.signalwords, current_state)

    @staticmethod
    def exit(current_state):
        elements = current_state.content.split("/")
        print(elements)
        return current_state.parent

    @staticmethod
    def signalwords_entry():
        return [["<<", DictionaryHandler.enter]]

    @staticmethod
    def signalwords_exit():
        return [[">>",DictionaryHandler.exit]]
    signalwords = []


class TextArrayHandler():

    signalwords = []  
    
    @staticmethod
    def set_routing(substates=[]):        
        TextArrayHandler._set_substates(substates)

    @staticmethod
    def _set_substates(substates=[]):
        for substate in substates:
            TextArrayHandler.signalwords += substate.signalwords_entry()

    @staticmethod
    def enter(current_state):
        next_state = State("TJ", "TextArray", TextArrayHandler.signalwords, current_state, PdfTextEncoder)
        try:
            current_state.content, next_state.content = current_state.content.split("[")
            next_state.content = next_state.split("]")[0]
            print(next_state.content)
        except Exception as ex:
            pass
        current_state.add(next_state)
        print(current_state.content)
        return current_state        # no state change here because this is a oneline state    
    

    @staticmethod
    def signalwords_entry():
        return [["TJ", TextArrayHandler.enter]]

    @staticmethod
    def signalwords_exit():
        return []


class TextElementHandler():

    signalwords = []  
    
    @staticmethod
    def set_routing(substates=[]):        
        TextElementHandler._set_substates(substates)

    @staticmethod
    def _set_substates(substates=[]):
        for substate in substates:
            TextElementHandler.signalwords += substate.signalwords_entry()

    @staticmethod
    def enter(current_state):
        next_state = State("Tj", "TextElement", TextElementHandler.signalwords, current_state)
        try:
            current_state.content, next_state.content = current_state.content.split("<")
            next_state.content = next_state.split(">")[0]
        except Exception as ex:
            pass
        current_state.add(next_state)
        print(current_state.content)
        return current_state        # no state change here because this is a oneline state

    @staticmethod
    def signalwords_entry():
        return [["Tj", TextElementHandler.enter]]

    @staticmethod
    def signalwords_exit():
        return []
    

class TDHandler():

    signalwords = []  
    
    @staticmethod
    def set_routing(substates=[]):        
        TextElementHandler._set_substates(substates)

    @staticmethod
    def _set_substates(substates=[]):
        for substate in substates:
            TextElementHandler.signalwords += substate.signalwords_entry()

    @staticmethod
    def enter(current_state):
        next_state = State("TD", "TD", TDHandler.signalwords, current_state)
        try:
            if "\n" in current_state.content:
                current_state.content, next_state.content = current_state.content.rsplit("\n")
            else:
                next_state.content = current_state.content
                current_state.content = ""
            next_state.content = next_state.content.split("TD")[0].trim()
        except Exception as ex:
            pass
        current_state.add(next_state)
        print(current_state.content)
        return current_state        # no state change here because this is a oneline state

    @staticmethod
    def signalwords_entry():
        return [["TD", TDHandler.enter]]

    @staticmethod
    def signalwords_exit():
        return []


class TcHandler():

    signalwords = []  
    
    @staticmethod
    def set_routing(substates=[]):        
        TextElementHandler._set_substates(substates)

    @staticmethod
    def _set_substates(substates=[]):
        for substate in substates:
            TextElementHandler.signalwords += substate.signalwords_entry()

    @staticmethod
    def enter(current_state):
        next_state = State("Tc", "Tc", TcHandler.signalwords, current_state)
        try:
            if "\n" in current_state.content:
                current_state.content, next_state.content = current_state.content.rsplit("\n")
            else:
                next_state.content = current_state.content
                current_state.content = ""
            next_state.content = next_state.content.split("Tc")[0].trim()
        except Exception as ex:
            pass
        current_state.add(next_state)
        print(current_state.content)
        return current_state        # no state change here because this is a oneline state

    @staticmethod
    def signalwords_entry():
        return [["Tc", TcHandler.enter]]

    @staticmethod
    def signalwords_exit():
        return []
