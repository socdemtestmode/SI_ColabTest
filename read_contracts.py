import os

def read_ts_files(directory):
    """Recursively reads all .ts files in a directory and prints their content."""
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".ts"):
                filepath = os.path.join(root, file)
                print(f"--- Contents of {filepath} ---\n")
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        print(f.read())
                except Exception as e:
                    print(f"Error reading file {filepath}: {e}")
                print(f"\n--- End of {filepath} ---\n")

if __name__ == "__main__":
    contracts_dir = "SIOnline/src/client/contracts"
    if os.path.isdir(contracts_dir):
        read_ts_files(contracts_dir)
    else:
        print(f"Directory not found: {contracts_dir}")
