
from flask import Flask, request, jsonify
from openai_interface import get_structured_input_from_nl
import requests

app = Flask(__name__)

AZURE_ML_URL = "https://<region>.azurewebsites.net/score"
AZURE_ML_KEY = "<your-api-key>"

@app.route('/predict-from-nl', methods=['POST'])
def predict_from_nl():
    nl_text = request.json.get("input")
    structured_input = get_structured_input_from_nl(nl_text)

    data = {
        "data": [structured_input]
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AZURE_ML_KEY}"
    }

    azure_response = requests.post(AZURE_ML_URL, headers=headers, json=data)

    return jsonify({
        "structured_input": structured_input,
        "prediction": azure_response.json()
    })

if __name__ == '__main__':
    app.run(port=5000, debug=True)
