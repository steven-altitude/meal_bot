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

def get_available_model():
    """Consulta a la API qué modelos están disponibles realmente para esta Key/Región"""
    print("🔍 Consultando lista de modelos disponibles en Google API...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"⚠️ Error listando modelos: {response.status_code} - {response.text}")
            return None
            
        data = response.json()
        models = data.get('models', [])
        
        print(f"📋 Modelos encontrados: {len(models)}")
        
        # Filtramos modelos que sirvan para 'generateContent'
        usable_models = []
        for m in models:
            if 'generateContent' in m.get('supportedGenerationMethods', []):
                usable_models.append(m['name']) # El nombre ya viene como 'models/gemini-xyz'
        
        print(f"✅ Modelos utilizables para generar texto: {usable_models}")
        
        # Prioridad: Buscar versiones Flash (rápidas y baratas/gratis), luego Pro
        for m in usable_models:
            if 'flash' in m and '1.5' in m:
                return m.replace('models/', '') # La API a veces requiere el nombre sin prefijo en la URL, a veces con.
            
        # Si no hay flash 1.5, cualquiera con 'pro'
        for m in usable_models:
            if 'pro' in m:
                return m.replace('models/', '')

        # Si no, el primero que haya
        if usable_models:
            return usable_models[0].replace('models/', '')
            
        return None

    except Exception as e:
        print(f"❌ Error crítico buscando modelos: {str(e)}")
        return None

def generate_meal_plan(history):
    """Generate a daily meal plan using dynamic model selection"""
    
    # 1. AUTODESCUBRIMIENTO DE MODELO
    model_name = get_available_model()
    
    if not model_name:
        # Fallback de emergencia si la lista falla
        print("⚠️ No se pudo obtener lista dinámica. Usando fallback manual.")
        model_name = "gemini-1.5-flash" 
    
    print(f"🚀 Usando modelo seleccionado: {model_name}")

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

    # Intentamos con el modelo descubierto
    # Nota: A veces la API quiere 'models/nombre' y a veces solo 'nombre'. Probamos ambos.
    variations = [model_name, f"models/{model_name}"] if "models/" not in model_name else [model_name]
    
    for current_model in variations:
        # Limpiamos slashes duplicados por si acaso
        current_model = current_model.replace("models/models/", "models/")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={GEMINI_API_KEY}"
        
        try:
            print(f"📡 Conectando a: ...{url[-40:]}") # Log seguro sin mostrar toda la key
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and result['candidates'] and 'content' in result['candidates'][0]:
                    return result['candidates'][0]['content']['parts'][0]['text']
            
            print(f"⚠️ Falló intento con {current_model}: {response.status_code} - {response.text}")
            
        except Exception as e:
            print(f"⚠️ Error conexión: {str(e)}")

    raise Exception(f"No se pudo generar contenido con el modelo {model_name}")

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
    # Si quieres probar hoy, comenta las siguientes lineas:
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
