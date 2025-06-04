const express = require('express');
const axios = require('axios');
const app = express();
app.use(express.json());

app.post('/api/nlc-predict', async (req, res) => {
  const { prompt } = req.body;

  try {
    const openAIResponse = await axios.post('https://your-azure-openai-endpoint', {
      prompt,
    }, {
      headers: {
        'Authorization': `Bearer YOUR_API_KEY`
      }
    });

    res.json({ predicted_balance: openAIResponse.data.choices[0].message.content });
  } catch (error) {
    res.status(500).json({ error: error.toString() });
  }
});

app.listen(3001, () => console.log('Server running on port 3001'));
