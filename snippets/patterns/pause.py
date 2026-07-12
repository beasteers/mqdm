import mqdm
import time

# A long job that hits something worth a closer look partway through. `pause()`
# freezes the live bars so you can drop into a real shell (or debugger) on a
# clean screen, poke at live state, then let the job carry on where it left off.
data = {}
for i in mqdm.mqdm(range(20), desc="processing"):
    time.sleep(0.08)
    data[i] = i * i
    if i == 9:
        with mqdm.pause():
            print("Halfway — let's inspect the data so far in a shell.")
            import IPython
            IPython.embed()
        # bars resume automatically once the shell exits

print("Done — processed", len(data), "items")
