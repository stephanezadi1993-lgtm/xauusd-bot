import asyncio
import subprocess
import sys
import threading

def run_bot(script):
    subprocess.run([sys.executable, script])

t1 = threading.Thread(target=run_bot, args=("bot.py",))
t2 = threading.Thread(target=run_bot, args=("bot_synthetic.py",))

t1.start()
t2.start()

t1.join()
t2.join()
