import subprocess
import sys
import threading

def run_xau():
    subprocess.Popen([sys.executable, "-u", "bot.py"]).wait()

def run_synthetic():
    subprocess.Popen([sys.executable, "-u", "bot_synthetic.py"]).wait()

t1 = threading.Thread(target=run_xau, daemon=False)
t2 = threading.Thread(target=run_synthetic, daemon=False)

t1.start()
t2.start()

t1.join()
t2.join()
