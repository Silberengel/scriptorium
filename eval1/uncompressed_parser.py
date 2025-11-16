import re
import os
import sys
import pikepdf
import mmap
import zlib
from io import BytesIO

class RawByte():

    def encode(self, c):
        return c 

class PdfTextEncoder():
    def __init__(self):
        self.char_table = {}
        with open("/home/madmin/Projects/GitCitadel/Scriptorium/latin_encodings_table.csv","r") as f:
            lines = f.readlines()
            for line in lines:        
                c = line[0]
                dec_val = int(line[3:].strip())        
                if dec_val == 147:
                    c = "fi"
                elif dec_val == 148:
                    c = "fl"
                if dec_val == 161:
                    c = "i"
                if dec_val == 10:
                    c = "\n"
                self.char_table[dec_val] = c    

    def encode(self, c):        
        if c in self.char_table:
            return self.char_table[c]
        else:
            try:
                r =chr(c)
                return r
            except Exception as ex:
                #print(c,ex)
                return f"??{c}??"


class State:

    flatlist = []

    def __init__(self, objname, objtype, signalwords, parent, encoder=None):
        self.objname = objname
        self.objtype = objtype        
        self.signalwords = signalwords
        self.parent = parent
        self.children = []
        self.content = ""
        self.compressed = bytearray()
        self.encoder = encoder
        self.start = None
        self.end = None
        self.FlatDecode = False
        
        #self.content_b = BytesIO()
        self.signalchars = list( word[0][-1] for word in self.signalwords )
        
        if parent is None:
            self.depth=0
        else:
            self.depth = parent.depth+1
        self.data = {}
        
        Tracer.add_state(self)        

    def parser(self, it):
        
        """ Bytewise parser, switches states if signalword is detected"""
       
        # pull the next byte
        b = it.pull_byte()
        if not isinstance(b, str):
            c = chr(b)
        if self.FlatDecode & (c != "\n") & (c!="\r"):
            self.compressed.append(b)
        self.content += c
        
        # all the detect singalword function
        signalfunct = self.detect_signalword(c)

        if signalfunct is not None:
            #print(f"State change to {next_state.objname}")
            next_state = signalfunct(self) 
            self.children.append(next_state)
            State.flatlist.append(next_state)
            self.end = it._index -1
            next_state.start = it._index
        else:
            next_state = self
        
        return next_state

        #print(c, self.content, self.signalchars)
    
        
            
        
    def detect_signalword(self, c):
        if c in self.signalchars:
            for signalword in self.signalwords:
                try:            
                    if str(self.content).endswith(signalword[0]):
                        return signalword[1]
                except Exception as ex:
                    print(f"ERR: {self.objname} ERR_MSG: {ex}")
        return None
        
    
    def add(self, child):
        self.children.append(child)


class Tracer:
    position = 0    
    object_list_flat = []
    object_stats = {"count": {}}

    @staticmethod
    def add_state(state: State):
        
        # add to flat list
        Tracer.object_list_flat.append(state)
        
        # add to statistics (counter)
        objtype = state.objtype
        if objtype not in Tracer.object_stats["count"]:
            Tracer.object_stats["count"][objtype] = 1
        else:
            Tracer.object_stats["count"][objtype] +=1


class SourceIterator():

    def __init__(self, content):
        self._index=0
        self.data = content

    #def __init__(self, filename: str):
    #    self.filename=filename
    #    self.data = None
    #    with open(file_name,"rb") as f:            
    #        self.data=f.read()     
    #    self._index=0

    def pull_byte(self):
        try:
            b = self.data[self._index]
            self._index += 1
            return b
        except IndexError as ex:
            self.finalize()
            raise ex
        except Exception as ex:
            print(self._index, ex)
            raise ex

    def pull_byte_block(self, len, pre=0):
        try:
            start = self._index - pre
            stop = self._index + len
            bb = self.data[start:stop]
            self._index += len
        except IndexError as ex:
            self.finalize()
            raise ex
        except Exception as ex:
            print(self._index, ex)
            raise ex
    
    
    def pull_byte_block(self, len, pre=0):
        try:
            start = self._index - pre
            stop = self._index + len
            bb = self.data[start:stop]
            self._index += len
            return bb
        except Exception as ex:
            print(start, stop, ex)
            raise ex
        
    def finalize(self):
        print("Iterator says goodbye")
   
        
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
        new_state = State("stream", "Stream", StreamHandler.signalwords, current_state, RawByte())
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


def run(content, root_state):

    current_state = root_state

    it = SourceIterator(content)
    while(True):
        try:
            # pulled out by exception from iterator       
            current_state = current_state.parser(it)
        except IndexError:
            print("Done")
            break

    print("\n\n-----------SUMMARY:")
    for item in State.flatlist:
        l = len(item.content)
        print(f"{item.start} - {item.end} [{item.end - item.start}]: {item.objname}, {item.content[0:min(l,10)].replace("\n"," ")}...{item.content[-10:].replace("\n"," ")}")


if __name__=="__main__":
    print(os.getcwd())
    file_name = "examples/VerySimple2.pdf"
    #file_name = "examples/maxwell_equations_uncompressed.txt"
    #file_name = "examples/PdfParserTestDocUncompressed.txt"

    with open(file_name,"rb") as f:            
        content = f.read() 

    root_state = initialize()
    run(content, root_state)
