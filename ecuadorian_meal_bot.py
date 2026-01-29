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

# Lista de modelos a probar (en orden de preferencia)
# Si uno falla, el bot probará el siguiente automáticamente.
MODELS_TO_TRY = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash-002",
    "gemini-1.5-flash-8b",
    "gemini-pro"  # El modelo clásico de respaldo
]

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

def generate_meal_plan(history):
    """Generate a daily meal plan using Gemini API via REST with fallback models"""
    
    # Get recent recipes to avoid repetition
    recent_recipes = [r['meals'] for r in history['recipes'][-14:]] if history['recipes'] else []
    recent_context = "\n".join([f"- {meal}" for meals in recent_recipes for meal in meals])
    
    prompt = f"""Genera 3 recetas auténticas ecuatorianas para hoy: desayuno, almuerzo y merienda.

REQUISITOS IMPORTANTES:
- Usa SOLO ingredientes nativos de Ecuador o comúnmente usados en la cocina ecuatoriana
- Incluye platos tradicionales ecuatorianos
- Sé específico con los nombres de ingredientes (usa nombres en español cuando sea apropiado)
- Haz las recetas prácticas y realistas para cocinar diariamente

Recetas recientes para EVITAR repetir:
{recent_context if recent_context else "Ninguna aún - esta es la primera generación"}

Formatea tu respuesta EXACTAMENTE así:

🌅 DESAYUNO:
[Nombre del plato]
Ingredientes: [lista]
Preparación: [pasos breves]

🌮 ALMUERZO:
[Nombre del plato]
Ingredientes: [lista]
Preparación: [pasos breves]

🌙 MERIENDA:
[Nombre del plato]
Ingredientes: [lista]
Preparación: [pasos breves]

¡Hazlo auténtico, delicioso y únicamente ecuatoriano!"""

    headers = {
        'Content-Type': 'application/json'
    }
    
    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }

    last_error = None

    # Intentar con cada modelo en la lista hasta que uno funcione
    for model_name in MODELS_TO_TRY:
        print(f"🔄 Intentando con modelo: {model_name}...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        
        try:
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and result['candidates'] and 'content' in result['candidates'][0]:
                    print(f"✅ Éxito con el modelo: {model_name}")
                    return result['candidates'][0]['content']['parts'][0]['text']
            
            # Si falló, guardamos el error y continuamos al siguiente modelo
            error_msg = f"Modelo {model_name} falló: {response.status_code} - {response.text}"
            print(f"⚠️ {error_msg}")
            last_error = error_msg
            
        except Exception as e:
            print(f"⚠️ Error de conexión con {model_name}: {str(e)}")
            last_error = str(e)

    # Si llegamos aquí, fallaron todos los modelos
    raise Exception(f"Todos los modelos fallaron. Último error: {last_error}")

def send_telegram_message(message):
    """Send message via Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    response = requests.post(url, data=data)
    return response.json()

def is_workday():
    """Check if today is Monday-Friday"""
    return datetime.now().weekday() < 5  # 0-4 is Monday-Friday

def should_send_today(history):
    """Check if we should send today (workday + not already sent)"""
    # Si quieres probar hoy (aunque sea fin de semana), comenta las siguientes 2 líneas:
    if not is_workday():
       return False
    
    today = datetime.now().date().isoformat()
    last_sent = history.get('last_sent')
    
    return last_sent != today

def main():
    """Main function to generate and send meal plan"""
    print(f"🤖 Starting Ecuadorian Meal Bot - {datetime.now()}")
    
    # Load history
    history = load_history()
    history = clean_old_recipes(history)
    
    # Check if we should send today
    if not should_send_today(history):
        print("⏭️  Skipping - either weekend or already sent today")
        return
    
    print("📝 Generating meal plan...")
    
    try:
        # Generate meal plan
        meal_plan = generate_meal_plan(history)
        
        # Prepare message
        today_str = datetime.now().strftime("%A, %B %d, %Y")
        message = f"🇪🇨 <b>Plan de Comidas Ecuatorianas</b>\n📅 {today_str}\n\n{meal_plan}"
        
        # Send via Telegram
        print("📤 Sending to Telegram...")
        result = send_telegram_message(message)
        
        if result.get('ok'):
            print("✅ Message sent successfully!")
            
            # Update history
            history['recipes'].append({
                'date': datetime.now().date().isoformat(),
                'meals': meal_plan.split('\n')[:3]  # Store first 3 lines (meal names)
            })
            history['last_sent'] = datetime.now().date().isoformat()
            save_history(history)
        else:
            print(f"❌ Error sending message: {result}")
            
    except Exception as e:
        print(f"❌ Error crítico final: {str(e)}")

if __name__ == "__main__":
    main()
