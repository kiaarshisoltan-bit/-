import requests

TOKEN = "1892656218:RKl_cA6b4OJuSoMJ1GCSWznqC1WD5X46OWw"
url = f"https://tapi.bale.ai/bot{TOKEN}/getMe"

response = requests.get(url)
print(response.status_code)
print(response.text)
