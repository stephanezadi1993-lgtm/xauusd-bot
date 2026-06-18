import subprocess
import sys
import threading

def run_xau():
    subprocess.Popen([sys.executable, "-u", "bot.py"]).wait()

def run_synthetic():
    result = subprocess.run(
        [sys.executable, "-u", "bot_synthetic.py"],
        capture_output=False,
        stderr=sys.stderr,
        stdout=sys.stdout
    )
    print(f"bot_synthetic exited with code {result.returncode}", flush=True)

t1 = threading.Thread(target=run_xau, daemon=False)
t2 = threading.Thread(target=run_synthetic, daemon=False)

t1.start()
t2.start()

t1.join()
t2.join()
