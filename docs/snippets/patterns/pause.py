import mqdm
import time


for i in mqdm.mqdm(range(20), desc="initial loop"):
    time.sleep(0.08)
    if i == 9:
        print("Pausing at step 10...")
        with mqdm.pause():
            # Wait for user input before continuing
            print("Something interesting is a foot!")
            print("Some data", i)
            input("Continue? (press Enter to continue)")
