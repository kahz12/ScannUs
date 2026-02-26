# AI Provider Library Imports
from openai import OpenAI
from google import genai
import os

# --- Text Generator Classes ---

class OpenAIGenerator:
    """
    Encapsulates the logic to interact with the OpenAI API.
    This class handles dispatching prompts to a specific OpenAI model (e.g., GPT-4o)
    and retrieving the generated response.
    """
    def __init__(self, model_name="gpt-4o"):
        """
        Initializes the OpenAI client singleton.

        Args:
            model_name (str): The identifier of the OpenAI model to target.
                              Defaults to "gpt-4o".
        """
        self.model_name = model_name
        # The client automatically resolves the OPENAI_API_KEY from the environment.
        self.client = OpenAI()

    def generate(self, prompt):
        """
        Dispatches a prompt to the OpenAI inference engine.

        Args:
            prompt (str): The structured instruction set for the model.

        Returns:
            str: The raw text payload from the model's response.
        """
        print(f"Generating with OpenAI ({self.model_name})...")
        chat_completion = self.client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            model=self.model_name,
        )
        # Extract the message content from the primary choice branch.
        return chat_completion.choices[0].message.content

class GeminiGenerator:
    """
    Encapsulates logic for interfacing with the Google Gemini API via the `google-genai` SDK.
    """
    def __init__(self, model_name="gemini-2.5-flash"):
        """
        Initializes the Gemini client context.

        Args:
            model_name (str): The Gemini model identifier.
        """
        self.model_name = model_name
        self.client = None
        self._initialize_client()

    def _initialize_client(self):
        """Attempts to bootstrap the client using the GOOGLE_API_KEY_FOR_GEMINI environment variable."""
        api_key = os.getenv("GOOGLE_API_KEY_FOR_GEMINI")
        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
            except Exception as e:
                print(f"Error initializing Gemini client: {e}")

    def generate(self, prompt):
        """
        Sends a prompt to the Gemini model and returns the generated text.

        Args:
            prompt (str): The input text payload.

        Returns:
            str: The response text content.
        """
        if not self.client:
            self._initialize_client()
            if not self.client:
                return "Error: Gemini client not initialized (missing GOOGLE_API_KEY_FOR_GEMINI API Key)."

        print("Generating with Gemini...")
        try:
            # Executes content generation using the modern GenAI SDK syntax.
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            return response.text
        except Exception as e:
            return f"Error during Gemini generation: {e}"

# --- AI Agent Class ---

class IAAgent:
    """
    Orchestrator class that leverages an underlying text generator (Strategy Pattern)
    to perform domain-specific OSINT tasks, such as automated Google Dork synthesis.
    """
    def __init__(self, generator):
        """
        Initializes the agent with a specific generation strategy.

        Args:
            generator: An implementation of a generator (e.g., `OpenAIGenerator`).
        """
        self.generator = generator

    def generate_gdork(self, description):
        """
        Synthesizes an optimized Google Dork from a natural language description.

        Args:
            description (str): Human-readable target description.

        Returns:
            str: The generated dork string, or None on failure.
        """
        prompt = self._build_prompt(description)
        try:
            output = self.generator.generate(prompt)
            return output
        except Exception as e:
            print(f'Error generating Google Dork: {e}')
            return None

    def _build_prompt(self, description):
        """
        Constructs a structured few-shot prompt to guide the LLM's output format.
        
        This method defines the persona and constraints required to ensure the
        model returns a valid, high-precision search query.

        Args:
            description (str): User-provided search target.

        Returns:
            str: Formatted prompt for the LLM.
        """
        return f'''
        Your task is to act as an OSINT expert and generate a precise and effective Google Dork
        based on the user's description. A Google Dork uses advanced search operators to find
        specific information that is not easily accessible through conventional searches.

        Instructions:
        1. Analyze the user's description to identify keywords, file types, domains, and any other constraints.
        2. Translate these requirements into the corresponding Google operators (e.g., `site:`, `filetype:`, `inurl:`, `intitle:`, etc.).
        3. Combine the operators logically to create a cohesive and efficient dork.
        4. Return ONLY the generated dork, without any additional explanations or text.

        Examples:

        User description: "Find annual reports in PDF format from Microsoft."
        Google Dork: filetype:pdf "annual report" site:microsoft.com

        User description: "Search for admin login pages on educational sites in Colombia."
        Google Dork: site:.edu.co intitle:"admin login" | inurl:"admin"

        User description: "I want to find Excel spreadsheets containing price lists for electronic products."
        Google Dork: filetype:xlsx "price list" "electronic products"

        Now, generate the Google Dork for the following description:

        User description: "{description}"
        '''
