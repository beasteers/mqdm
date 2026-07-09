# Examples

Here are some common patterns for using `mqdm`:

- [Loops](loops.md): simple iteration, nested bars, and dynamic descriptions
- [Pools](pools.md): sequential, parallel, extra arguments, and complex arguments
- [Output](output.md): printing, logging, and byte progress
- [Patterns](patterns.md): a few lower-priority patterns that are still useful
- [Other multiprocessing tools](other-pools.md): use `mqdm` bars with
  `concurrent.futures`, `multiprocessing.Pool`, and raw threads

## A complete example

A common situation I find myself in is processing a large amount of sensor data in parallel. 

I have the data partitioned by `{sensor_id}/{date}.csv`

If you were to boil down the problem to its simplest form, it would look like this:

```python
for sensor_id in mqdm.mqdm(sensor_ids):
    for date in mqdm.mqdm(dates):
        process_sensor_chunk(sensor_id, date)
```

With `mqdm.pool`, you can submit each sensor as a separate job so that they will run through their files in parallel.

```python
import os
import mqdm
from mqdm import print

import pandas as pd


def main(csv_dir="data", out_dir="output", n_workers=2, **kw):
    """Main function to process all sensor data in parallel."""

    # List all sensor IDs in the csv_dir
    sensor_ids = sorted(os.listdir(csv_dir))

    # Run process_sensor in parallel for each sensor_id
    mqdm.pool(
        process_sensor,
        sensor_ids,
        desc="Processing sensor data",
        n_workers=n_workers,
        csv_dir=csv_dir,
        out_dir=out_dir,
        **kw
    )


def process_sensor(sensor_id, csv_dir, out_dir, **kw):
    """Worker function to process a single sensor's data."""

    # List available files for sensor
    dates = sorted(os.listdir(os.path.join(csv_dir, sensor_id)))

    # Dynamic description to show current sensor & date
    desc = lambda date, i: f"{sensor_id}: {os.path.splitext(date)[0]}"

    # Process each file for the sensor
    for date in mqdm.mqdm(dates, desc=desc):
        src_path = os.path.join(csv_dir, sensor_id, date)
        out_path = os.path.join(out_dir, sensor_id, date)
        process_single_sensor_csv(src_path, out_path, **kw)

    # I don't usually return anything, but you can.
    return len(dates)


def process_single_sensor_csv(src_path, out_path, overwrite=False):
    """Process a single sensor csv file and save the output."""

    # Check if the output file already exists
    if os.path.exists(out_path) and not overwrite:
        print(f"Skipping {out_path} (already exists)")
        return

    # Read the CSV file
    df = pd.read_csv(src_path)

    # do something useful here...

    # Save the processed DataFrame to the output path
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False)


if __name__ == "__main__":
    import fire
    fire.Fire(main)
```

Plugging [`fire`](https://github.com/google/python-fire) here cuz she's been getting me through years of scripting. argparse who?
