# Importaciones de bibliotecas estándar de Python.
import os
from dotenv import load_dotenv

# --- Carga y Verificación del Archivo .env ---

# Este script está diseñado para ayudar a depurar problemas relacionados con la carga
# de variables de entorno desde un archivo .env.

# `load_dotenv(verbose=True)` intenta encontrar y cargar un archivo .env en el directorio actual
# o en directorios superiores. El argumento `verbose=True` es útil para la depuración, ya que
# imprimirá en la consola la ruta del archivo .env que está intentando cargar.
found_dotenv = load_dotenv(verbose=True)

# Se comprueba el valor de retorno de `load_dotenv`. Devuelve True si encontró y cargó un archivo,
# y False en caso contrario.
if found_dotenv:
    # Si el archivo .env fue localizado y procesado, se imprime un mensaje de éxito.
    print("\n✅ ¡Éxito! Se encontró y cargó el archivo .env.")
else:
    # Si no se pudo encontrar el archivo .env, se informa al usuario.
    print("\n❌ ¡Error! No se encontró ningún archivo .env en el directorio actual o superiores.")
    # Se muestra el directorio de trabajo actual para ayudar al usuario a verificar
    # que el archivo .env está en la ubicación correcta.
    print(f"Directorio actual: {os.getcwd()}")

# Imprime una línea separadora para organizar visualmente la salida en la consola.
print("-" * 30)
print("Comprobando las variables de entorno cargadas...")

# --- Comprobación de Variables de Entorno Específicas ---

# Lista de variables a comprobar
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
        # Si la clave existe, se imprime un mensaje de confirmación.
        # Por seguridad, es una buena práctica no imprimir la clave completa.
        # Mostrar solo los primeros caracteres confirma que se ha cargado sin exponerla.
        print(f"{var_name}: Encontrada. Comienza con: {value[:8]}...")
    else:
        # Si la clave no se encontró, se informa claramente al usuario.
        print(f"{var_name}: NO ENCONTRADA (es None o está vacía).")

# Imprime una línea separadora final para concluir el informe de depuración.
print("-" * 30)
