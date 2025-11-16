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
        
        #Tracer.add_state(self)        

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

