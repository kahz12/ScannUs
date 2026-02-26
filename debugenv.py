# Standard Python library imports.
import os
from dotenv import load_dotenv

# --- Load and Verify .env Runtime Configuration ---

# Diagnostic script designed to verify the presence and accessibility 
# of environment variables from the local .env manifest.

# `load_dotenv(verbose=True)` recursively searches for a .env file starting 
# from the current working directory. Verbose mode logs the resolved path.
found_dotenv = load_dotenv(verbose=True)

# Binary check for .env resolution status.
if found_dotenv:
    print("\n✅ Success! .env file found and successfully loaded into environment context.")
else:
    print("\n❌ Error! No .env file found in the current or parent directory tree.")
    # Display the CWD to assist in path troubleshooting.
    print(f"Current Working Directory: {os.getcwd()}")

# Visual separator for console output segmentation.
print("-" * 30)
print("Verifying target environment variable hydration...")

# --- Specific Key Integrity Checks ---

# List of critical credentials required for ScannUs operations.
variables_to_check = [
    "API_KEY_GOOGLE",
    "SEARCH_ENGINE_ID",
    "GOOGLE_API_KEY_FOR_GEMINI",
    "BRAVE_API_KEY",
    "OPENAI_API_KEY"
]

for var_name in variables_to_check:
    value = os.getenv(var_name)
    if value:
        # Key resolution success. 
        # Safety: We only log a short prefix to confirm existence without exposing full secrets.
        print(f"{var_name}: RESOLVED. Prefix: {value[:8]}...")
    else:
        # Critical key resolution failure.
        print(f"{var_name}: NOT FOUND (Variable is None or empty).")

print("-" * 30)
