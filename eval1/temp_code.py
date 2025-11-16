
obj_signalwords = None
def enter_object(current_state):
    global obj_signalwords
    if obj_signalwords is None:
        obj_signalwords = signalwords_object_exit
        obj_signalwords += signalwords_stream_entry
        obj_signalwords += signalwords_dict_entry
        obj_signalwords += signalwords_textblock_entry        
    return State("Object","Object",obj_signalwords, current_state)
   
def leave_object(state):
    return state.parent

stream_signalwords = None
def enter_stream(current_state):
    global stream_signalwords
    if stream_signalwords is None:
        stream_signalwords = signalwords_stream_exit
        stream_signalwords += signalwords_dict_entry
        stream_signalwords += signalwords_textblock_entry    
    return State("Stream","Stream",stream_signalwords,current_state)

def leave_stream(current_state):
    return current_state.parent

textblock_singalwords = None
def enter_textblock(current_state):
    global textblock_signalwords
    if textblock_singalwords is None:
        textblock_singalwords = signalwords_textblock_exit
        textblock_singalwords += signalwords_dict_entry
        textblock_singalwords += signalwords_textline   
        textblock_singalwords += signalwords_textarray
    return State("BT", "Textblock", textblock_singalwords, current_state)

def leave_textblock(current_state):
    return current_state.parent

def enter_dict(current_state):
    signalwords = signalwords_dict_exit    
    return State("<<", "Dict", signalwords, current_state)
    
def leave_dict(current_state):
    key_value_pairs = current_state.content.split("\n")
    for key_value_pair in key_value_pairs:
        res = re.match("\\(.*) (.*)", key_value_pair)
        if res:
            key = res.groups[1]
            value_raw = res.groups[2]
            if value_raw[0] == "\\":
                value = value_raw[1:]
            else:
                value = value
            current_state.data[key] = value
    return current_state.parent

def parse_textline(current_state):
    try:
        texts = current_state.content.rsplit("\n")[1]
    except:    
        texts = current_state.content        
    temp_state = State("Textline","Textline",[],current_state)
    text_data = texts.split("(")[1]
    text_data = text_data.rsplit(")")[0]
    text_data = text_data.replace(r"\(","(").replace(r"\)",")")
    temp_state.content = text_data
    return current_state

def parse_textarray(current_state):
    try:
        texts = current_state.content.rsplit("\n")[1]
    except:    
        texts = current_state.content
    temp_state = State("Textline","Textline",[],current_state)
    text_data = texts.split("[")[1]
    text_data = text_data.rsplit("]")[0]
    text_data = text_data.replace(r"\(","<<<|").replace(r"\)","|>>>")
    items = text_data.split("(")
    text_data_items = []
    for item in items:
        try:
            text_data_items.append(item.split(")")[0].replace("<<<|","(").replace("|>>>",")"))
        except Exception as ex:
            print(ex)
    temp_state.content = "".join(text_data_items)

    return current_state


def parse_Td(current_state):
    ''' 
    tx ty Td
    Move to the start of the next line, offset from the start of the current line by (tx, ty).
    tx and ty are numbers expressed in unscaled text space units.
                |1  0  0|
    Tm = Tlm =  |0  1  0| x Tlm
                |tx ty 1|
    see chapter 5.3.1 Table 5.5
    '''
    try:
        td_data = current_state.content.rsplit("\n")[1]
    except:
        td_data = current_state.content
    if "TD" not in current_state.data:
        current_state.data["Td"]=[]
    current_state.data["Td"].append(td_data)        
    return current_state

def parse_TD(current_state):
    ''' 
    tx ty TD
    Move to the start of the next line, offset from the start of the current line by (tx, ty).
    see chapter 5.3.1 Table 5.5
    '''
    try:
        td_data = current_state.content.rsplit("\n")[1]
    except:
        td_data = current_state.content
    if "TD" not in current_state.data:
        current_state.data["TD"]=[]
    current_state.data["TD"].append(td_data)        
    return current_state

def parse_Tm(current_state):
    '''
    a b c d e f Tm
    Set the text matrix, Tm and the text line matrix, Tlm
                |a b 0|
    Tm = Tlm =  |c d 0|
                |e f 1|
    '''
    try:
        data = current_state.content.rsplit("\n")[1]
    except:
        data = current_state.content
    if "Tm" not in current_state.data:
        current_state.data["Tm"]=[]
    current_state.data["Tm"].append(data)        
    return current_state


def parse_Tc(current_state):
    '''
    charSpace Tc 
    Set the caracter spacing Tc to char Space which is a number expressed in unscaled text space units  
    '''
    try:
        data = current_state.content.rsplit("\n")[1]
    except:
        data = current_state.content
    if "Tc" not in current_state.data:
        current_state.data["Tc"]=[]
    current_state.data["Tc"].append(data)        
    return current_state

def parse_Tf(current_state):
    '''
    fontsize Tf
    Set the text font, Tf to font and the text font size Tfs to size.
    see chapter 5.2 table 5.2
    '''
    try:
        data = current_state.content.rsplit("\n")[1]
    except:
        data = current_state.content
    if "Tf" not in current_state.data:
        current_state.data["Tf"]=[]
    current_state.data["Tf"].append(data)        
    return current_state

def parse_Tz(current_state):
    '''
    scale Tz
    Set the horizontal scaling.
    see chapter 5.2 table 5.2
    '''
    try:
        data = current_state.content.rsplit("\n")[1]
    except:
        data = current_state.content
    if "Tz" not in current_state.data:
        current_state.data["Tz"]=[]
    current_state.data["Tz"].append(data)        
    return current_state

def parse_Tf(current_state):
    '''
    fontsize Tf
    Set the text font, Tf to font and the text font size Tfs to size.
    see chapter 5.2 table 5.2
    '''
    try:
        data = current_state.content.rsplit("\n")[1]
    except:
        data = current_state.content
    if "Tf" not in current_state.data:
        current_state.data["Tf"]=[]
    current_state.data["Tf"].append(data)        
    return current_state

def parse_TL(current_state):
    '''
    leading TL
    Set the text leading, TL which is a number expressed in unscaled text space units.
    see chapter 5.2 table 5.2
    '''
    try:
        data = current_state.content.rsplit("\n")[1]
    except:
        data = current_state.content
    if "TL" not in current_state.data:
        current_state.data["TL"]=[]
    current_state.data["TL"].append(data)        
    return current_state

def parse_Tr(current_state):
    '''
    render Tr
    Set the text rendering mode, Tmode to render, which is an integer.
    see chapter 5.2 table 5.2
    '''
    try:
        data = current_state.content.rsplit("\n")[1]
    except:
        data = current_state.content
    if "Tr" not in current_state.data:
        current_state.data["Tr"]=[]
    current_state.data["Tr"].append(data)        
    return current_state

def parse_Ts(current_state):
    '''
    render Ts
    Set the text rise,
    see chapter 5.2 table 5.2
    '''
    try:
        data = current_state.content.rsplit("\n")[1]
    except:
        data = current_state.content
    if "Ts" not in current_state.data:
        current_state.data["Ts"]=[]
    current_state.data["Ts"].append(data)        
    return current_state

def parse_name(current_state):
    try:
        name_data = current_state.content.rsplit("\n")[1]
    except:
        name_data = current_state.content
    return current_state

def parse_newline(current_state):
    try:
        name_newline = current_state.content.rsplit("\n")[1]
    except:
        name_newline = current_state.content
    return current_state
    

#signalwords_text_entry = [["("]]
#signalwords_text_exit = [[")"]]

signalwords = signalwords_object_entry
root = State("root", "root", signalwords , None)
current_state = root

buffer = ""
signalwords_root = []

signalwords_object_entry = [["obj", enter_object]]
signalwords_object_exit = [["endobj",leave_object]]

signalwords_stream_entry = [["stream", enter_stream]]
signalwords_stream_exit = [["endstream", leave_stream],]

signalwords_textblock_entry = [["BT", enter_textblock]]
signalwords_textblock_exit = [["ET", leave_textblock]]

signalwords_dict_entry = [["<<", enter_dict]]
signalwords_dict_exit = [[">>", leave_dict],["<<", enter_dict]]

signalwords_textline = [["Tj", parse_textline]]
signalwords_textarray = [["TJ", parse_textarray]]
signalwords_Tf = [["Tf", parse_Tf]]
signalwords_TD = [["TD", parse_TD]]
signalwords_Tc = [["Tc", parse_Tc]]
signalwords_Tm = [["Tm", parse_Tm]]
signalwords_name = [["/", parse_name]]
signalwords_newline = [["\n", parse_newline]]


def collect_text(state, result, depth):
    if depth>10:
        return
    for child in state.children:
        if child.objname == "Textline":
            result += child.content
        else:
            for grandchild in child.children:
                collect_text(grandchild, result, depth+1)