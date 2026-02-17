# Importaciones de las bibliotecas de los proveedores de IA
from openai import OpenAI
from google import genai
import os

# --- Clases de Generadores de Texto ---

class OpenAIGenerator:
    """
    Encapsula la lógica para interactuar con la API de OpenAI.
    Esta clase se encarga de enviar un prompt a un modelo específico de OpenAI (como GPT-4o)
    y devolver la respuesta generada.
    """
    def __init__(self, model_name="gpt-4o"):
        """
        Inicializa el cliente de OpenAI.

        Args:
            model_name (str): El identificador del modelo de OpenAI a utilizar.
                              El valor por defecto es "gpt-4o", un modelo potente y reciente.
        """
        self.model_name = model_name
        # Crea una instancia del cliente de OpenAI. La clave de API se toma automáticamente
        # de la variable de entorno OPENAI_API_KEY.
        self.client = OpenAI()

    def generate(self, prompt):
        """
        Envía un prompt al modelo de OpenAI y devuelve el texto generado.

        Args:
            prompt (str): El texto de entrada que se le dará al modelo como instrucción.

        Returns:
            str: El contenido de texto de la respuesta generada por el modelo.
        """
        print(f"Generando con OpenAI ({self.model_name})...")
        # Llama al método `create` del endpoint de `chat.completions` de la API.
        chat_completion = self.client.chat.completions.create(
            messages=[
                {
                    "role": "user",  # Se define el rol como "user" para indicar que es la entrada del usuario.
                    "content": prompt
                }
            ],
            model=self.model_name,
        )
        # La respuesta es un objeto complejo; extraemos el contenido del mensaje de la primera opción.
        return chat_completion.choices[0].message.content

class GeminiGenerator:
    """
    Encapsula la lógica para interactuar con la API de Google Gemini usando el SDK `google-genai`.
    """
    def __init__(self, model_name="gemini-2.5-flash"):
        """
        Inicializa el cliente de Gemini.

        Args:
            model_name (str): El identificador del modelo a utilizar.
        """
        self.model_name = model_name
        self.client = None
        self._initialize_client()

    def _initialize_client(self):
        """Intenta inicializar el cliente con la API Key del entorno."""
        api_key = os.getenv("GOOGLE_API_KEY_FOR_GEMINI")
        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
            except Exception as e:
                print(f"Error al inicializar cliente Gemini: {e}")

    def generate(self, prompt):
        """
        Envía un prompt al modelo de Gemini y devuelve el texto generado.

        Args:
            prompt (str): El texto de entrada.

        Returns:
            str: El texto de la respuesta.
        """
        if not self.client:
            self._initialize_client()
            if not self.client:
                return "Error: Cliente de Gemini no inicializado (falta API Key GOOGLE_API_KEY_FOR_GEMINI)."

        print("Generando con Gemini...")
        try:
            # La nueva SDK usa client.models.generate_content
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"Error en generación con Gemini: {e}"

# --- Clase del Agente de IA ---

class IAAgent:
    """
    Actúa como un intermediario o "agente" que utiliza un generador de texto
    (como OpenAIGenerator o GeminiGenerator) para realizar tareas más complejas y específicas.
    Esta abstracción permite cambiar fácilmente el motor de IA subyacente sin alterar
    la lógica de la tarea (como generar un Google Dork).
    """
    def __init__(self, generator):
        """
        Inicializa el agente con una estrategia de generación de texto específica.

        Args:
            generator: Una instancia de una clase generadora (ej. `OpenAIGenerator()`).
                       Esto es un ejemplo del patrón de diseño "Strategy".
        """
        self.generator = generator

    def generate_gdork(self, description):
        """
        Genera un Google Dork optimizado a partir de una descripción en lenguaje natural.

        Args:
            description (str): La descripción proporcionada por el usuario de lo que desea encontrar.

        Returns:
            str: El Google Dork generado como una cadena de texto, o None si ocurre un error.
        """
        # Construye un prompt detallado y específico para la tarea de generar dorks.
        prompt = self._build_prompt(description)
        try:
            # Delega la generación de texto al generador que se le pasó en el constructor.
            output = self.generator.generate(prompt)
            return output
        except Exception as e:
            # Captura y maneja cualquier error que pueda ocurrir durante la llamada a la API.
            print(f'Error al generar el Google Dork: {e}')
            return None

    def _build_prompt(self, description):
        """
        Crea un prompt estructurado para guiar al modelo de IA.

        Este método es crucial para la "ingeniería de prompts" (prompt engineering).
        Proporciona al modelo un contexto claro, instrucciones precisas y ejemplos
        (few-shot learning) para mejorar significativamente la calidad y el formato
        de la respuesta.

        Args:
            description (str): La descripción en bruto del usuario.

        Returns:
            str: El prompt completo y formateado que se enviará al modelo de IA.
        """
        # El f-string multilínea define el prompt.
        return f'''
        Tu tarea es actuar como un experto en OSINT y generar un Google Dork preciso y efectivo
        basado en la descripción proporcionada por el usuario. Un Google Dork utiliza operadores
        de búsqueda avanzada para encontrar información específica que no es fácilmente accesible
        mediante búsquedas convencionales.

        Instrucciones:
        1.  Analiza la descripción del usuario para identificar las palabras clave, los tipos de archivo,
            los dominios y cualquier otra restricción.
        2.  Traduce estos requisitos a los operadores de Google correspondientes (ej. `site:`, `filetype:`, `inurl:`, `intitle:`, etc.).
        3.  Combina los operadores de forma lógica para crear un dork cohesivo y eficiente.
        4.  Devuelve únicamente el dork generado, sin explicaciones adicionales.

        Ejemplos:

        Descripción del usuario: "Encuentra informes anuales en formato PDF de la empresa Microsoft."
        Google Dork: filetype:pdf "informe anual" site:microsoft.com

        Descripción del usuario: "Busca páginas de login de administrador en sitios educativos de Colombia."
        Google Dork: site:.edu.co intitle:"admin login" | inurl:"admin"

        Descripción del usuario: "Quiero encontrar hojas de cálculo de Excel que contengan listas de precios de productos electrónicos."
        Google Dork: filetype:xlsx "lista de precios" "productos electrónicos"

        Ahora, genera el Google Dork para la siguiente descripción:

        Descripción del usuario: "{description}"
        '''
