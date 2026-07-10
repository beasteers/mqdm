import mqdm
import time

print("Normal behavior")
for i in range(3):
    for _ in mqdm.mqdm(range(4), desc=f"section {i}"):
        time.sleep(0.2)
    print(f"Finished section {i}")
print("Finished all sections in normal behavior")

print("\nSustained behavior")
with mqdm.sustain():
    for i in range(3):
        for _ in mqdm.mqdm(range(4), desc=f"section {i}"):
            time.sleep(0.2)
        print(f"Finished section {i}")
    print("Finished all sections in sustained behavior")
