import subprocess
import sys

p1 = subprocess.Popen([sys.executable, "bot.py"])
p2 = subprocess.Popen([sys.executable, "bot_synthetic.py"])
p1.wait()
p2.wait()
