import requests

TOKEN = "*******" # توکن خودت
RENDER_URL = "https://your-app-name.onrender.com/*******" # آدرس دقیق رندر + توکن

webhook_url = f"https://tapi.bale.ai/bot{TOKEN}/setWebhook?url={RENDER_URL}"
response = requests.get(webhook_url)
print(response.json())
