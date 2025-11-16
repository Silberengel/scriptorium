from iterator import SourceIterator

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

