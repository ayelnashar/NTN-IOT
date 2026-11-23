import nbformat, sys, time
from nbclient import NotebookClient
nb = nbformat.read(sys.argv[1], as_version=4)
t = time.time()
NotebookClient(nb, timeout=14400, kernel_name="python3", resources={"metadata": {"path": "."}}).execute()
nbformat.write(nb, sys.argv[2])
print("executed in", round(time.time() - t), "s")
