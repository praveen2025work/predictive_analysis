
import openai

openai.api_key = "YOUR_OPENAI_API_KEY"

def get_structured_input_from_nl(nl_input: str):
    prompt = f"""
You are a helpful assistant. Convert the following natural language into a JSON object with keys:
- TOTAL_JOURNALS
- TOTAL_AMOUNT
- AVG_AMOUNT

Input: "{nl_input}"
JSON:
"""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0,
    )

    output = response['choices'][0]['message']['content']
    return eval(output)  # ⚠️ In production, use `json.loads` safely
