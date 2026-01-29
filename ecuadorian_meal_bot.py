import os
import json
import time
from datetime import datetime, timedelta
import requests

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# File to store recipe history
HISTORY_FILE = 'recipe_history.json'

def load_history():
    """Load the recipe history from file"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'recipes': [], 'last_sent': None}

def save_history(history):
    """Save the recipe history to file"""
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def clean_old_recipes(history):
    """Remove recipes older than 14 days"""
    cutoff_date = (datetime.now() - timedelta(days=14)).isoformat()
    history['recipes'] = [r for r in history['recipes'] if r['date'] > cutoff_date]
    return history

def get_prioritized_models():
    """Consulta la API y devuelve una lista de modelos ORDENADA por probabilidad de éxito en Free Tier."""
    print("🔍 Consultando lista de modelos disponibles...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    
    fallback_models = [
        "gemini-2.0-flash", "gemini-1.5-flash", 
        "gemini-1.5-flash-001", "gemini-1.5-flash-002", "gemini-pro"
    ]

    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"⚠️ Error listando modelos ({response.status_code}). Usando lista de respaldo.")
            return fallback_models
            
        data = response.json()
        raw_models = [m['name'].replace('models/', '') for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        print(f"📋 Total modelos encontrados: {len(raw_models)}")

        sorted_models = []
        # 1. Prioridad: Flash 2.x y 1.x
        for m in raw_models:
            if 'flash' in m and 'exp' not in m and m not in sorted_models:
                sorted_models.append(m)
        # 2. El resto
        for m in raw_models:
            if m not in sorted_models:
                sorted_models.append(m)

        print(f"✅ Orden de prueba: {sorted_models[:5]}...")
        return sorted_models

    except Exception as e:
        print(f"❌ Error buscando modelos: {str(e)}")
        return fallback_models

def generate_meal_plan(history):
    """Generate a daily meal plan trying multiple models if necessary"""
    candidate_models = get_prioritized_models()
    
    recent_recipes = [r['meals'] for r in history['recipes'][-14:]] if history['recipes'] else []
    recent_context = "\n".join([f"- {meal}" for meals in recent_recipes for meal in meals])
    
    # PROMPT ACTUALIZADO CON TUS NUEVOS REQUERIMIENTOS
    prompt = f"""Genera un plan de comidas detallado para hoy.

REGLAS GENERALES:
- Usa ingredientes fáciles de conseguir en supermercados de Ecuador (Supermaxi, Mi Comisariato).
- Sé conciso en la preparación.

ESTRUCTURA DEL MENÚ:

1. 🌅 DESAYUNO (100% Ecuatoriano):
- Debe ser una receta tradicional y auténtica de Ecuador (ej: bolones, tigrillo, majado, etc).

2. 🌮 ALMUERZO (Tradicional Completo):
- Debe incluir DOS platos: SOPA y SEGUNDO (Plato fuerte).
- El Segundo debe ser balanceado: Proteína + Carbohidrato + Ensalada.
- OBLIGATORIO: Incluye una sugerencia de plátano (Patacones, Verde asado, Maduro frito o Maduro asado).

3. 🌙 MERIENDA/CENA (Estilo Fit/Internacional):
- NO tiene que ser comida típica ecuatoriana.
- Estilo "Foodie Fit" de redes sociales (comida rica pero saludable).
- Ejemplos: Sánduches gourmet con yogurt griego, Ensaladas con pasta, Wraps de atún, etc.

Recetas recientes a EVITAR repetir:
{recent_context if recent_context else "Ninguna"}

FORMATO DE RESPUESTA OBLIGATORIO:

🌅 DESAYUNO: [Nombre del plato]
Ingredientes: [lista]
Preparación: [pasos breves]

🥣 ALMUERZO - SOPA: [Nombre de la sopa]
Ingredientes: [lista]
Preparación: [pasos breves]

🍛 ALMUERZO - SEGUNDO: [Nombre del plato fuerte]
Ingredientes: [lista]
Acompañante sugerido: [Patacones/Verde/Maduro]
Preparación: [pasos breves]

🌙 MERIENDA: [Nombre del plato]
Ingredientes: [lista]
Preparación: [pasos breves]"""

    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}]}

    for model_name in candidate_models:
        variations = [model_name, f"models/{model_name}"] if "models/" not in model_name else [model_name]
        
        for specific_model_name in variations:
            specific_model_name = specific_model_name.replace("models/models/", "models/")
            print(f"🔄 Probando modelo: {specific_model_name}...")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{specific_model_name}:generateContent?key={GEMINI_API_KEY}"
            
            try:
                response = requests.post(url, headers=headers, json=data)
                
                if response.status_code == 200:
                    result = response.json()
                    if 'candidates' in result and result['candidates'] and 'content' in result['candidates'][0]:
                        print(f"🚀 ¡ÉXITO! Contenido generado con: {specific_model_name}")
                        return result['candidates'][0]['content']['parts'][0]['text']
                
                print(f"⚠️ Falló {specific_model_name}: {response.status_code}")
                if response.status_code == 429: # Quota limit, fail fast to next model
                    break 
                
            except Exception as e:
                print(f"⚠️ Error conexión: {str(e)}")
        time.sleep(0.5)

    raise Exception(f"Todos los modelos fallaron.")

def send_telegram_message(message):
    """Send message via Telegram with chunking for long messages"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    MAX_LENGTH = 4000
    
    if len(message) <= MAX_LENGTH:
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        return requests.post(url, data=data).json()
    
    print(f"⚠️ Mensaje muy largo ({len(message)} chars). Dividiendo...")
    parts = []
    while message:
        if len(message) <= MAX_LENGTH:
            parts.append(message)
            break
        
        split_index = message.rfind('\n', 0, MAX_LENGTH)
        if split_index == -1:
            split_index = MAX_LENGTH
            
        parts.append(message[:split_index])
        message = message[split_index:]
    
    last_result = None
    for i, part in enumerate(parts):
        print(f"📤 Enviando parte {i+1}/{len(parts)}...")
        text_to_send = part if len(parts) == 1 else f"[{i+1}/{len(parts)}]\n{part}"
        
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text_to_send,
            # Quitamos HTML en partes divididas para seguridad
        }
        
        try:
            response = requests.post(url, data=data)
            last_result = response.json()
            time.sleep(1)
        except Exception as e:
            print(f"❌ Error enviando parte {i+1}: {e}")
            
    return last_result

def is_workday():
    return datetime.now().weekday() < 5 

def should_send_today(history):
    # Comentar esta línea para pruebas de fin de semana
    if not is_workday(): return False
    today = datetime.now().date().isoformat()
    return history.get('last_sent') != today

def main():
    print(f"🤖 Starting Ecuadorian Meal Bot - {datetime.now()}")
    
    history = load_history()
    history = clean_old_recipes(history)
    
    if not should_send_today(history):
        print("⏭️  Skipping - either weekend or already sent today")
        return
    
    print("📝 Generating meal plan...")
    
    try:
        meal_plan = generate_meal_plan(history)
        
        today_str = datetime.now().strftime("%A, %B %d, %Y")
        message = f"🇪🇨 <b>Plan de Comidas (Fit & Tradicional)</b>\n📅 {today_str}\n\n{meal_plan}"
        
        print("📤 Sending to Telegram...")
        result = send_telegram_message(message)
        
        if result and (result.get('ok') or isinstance(result, list)): # Handle chunked responses too
            print("✅ Message sent successfully!")
            history['recipes'].append({
                'date': datetime.now().date().isoformat(),
                'meals': meal_plan.split('\n')[:4] # Guardamos un poco más de contexto
            })
            history['last_sent'] = datetime.now().date().isoformat()
            save_history(history)
        else:
            print(f"❌ Error sending message: {result}")
            
    except Exception as e:
        print(f"❌ Error crítico final: {str(e)}")

if __name__ == "__main__":
    main()
