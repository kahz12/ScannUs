# Standard Python library imports.
import os
from dotenv import load_dotenv

# --- Load and Verify .env File ---

# This script is designed to help debug issues related to loading
# environment variables from a .env file.

# `load_dotenv(verbose=True)` attempts to find and load a .env file in the current
# directory or parent directories. The `verbose=True` argument is useful for debugging,
# as it prints the path of the .env file it is attempting to load to the console.
found_dotenv = load_dotenv(verbose=True)

# Check the return value of `load_dotenv`. Returns True if a file was found and loaded,
# and False otherwise.
if found_dotenv:
    # If the .env file was located and processed, print a success message.
    print("\n✅ ¡Éxito! Se encontró y cargó el archivo .env.")
else:
    # If the .env file could not be found, inform the user.
    print("\n❌ ¡Error! No se encontró ningún archivo .env en el directorio actual o superiores.")
    # Display the current working directory to help the user verify
    # that the .env file is in the correct location.
    print(f"Directorio actual: {os.getcwd()}")

# Print a separator line to visually organize console output.
print("-" * 30)
print("Comprobando las variables de entorno cargadas...")

# --- Check Specific Environment Variables ---

# List of variables to check
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
        # If the key exists, print a confirmation message.
        # For security, it's best practice not to print the complete key.
        # Showing only the first few characters confirms it loaded without exposing it.
        print(f"{var_name}: Encontrada. Comienza con: {value[:8]}...")
    else:
        # If the key was not found, clearly inform the user.
        print(f"{var_name}: NO ENCONTRADA (es None o está vacía).")

# Print a final separator line to conclude the debug report.
print("-" * 30)
