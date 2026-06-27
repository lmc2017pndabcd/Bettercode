import sys
import os
if sys.argv[1]=="config":
    import src.config as config
    config.main()
else:
    import src.chat_loop as chat_loop
    chat_loop.chat_loop()