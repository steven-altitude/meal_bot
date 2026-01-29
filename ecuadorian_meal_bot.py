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
    """
    Consulta la API y devuelve una lista de modelos ORDENADA por probabilidad de éxito en Free Tier.
    Prioridad: Flash 2.0 > Flash 1.5 > Otros Flash > Pro
    """
    print("🔍 Consultando lista de modelos disponibles...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    
    # Lista de respaldo por si falla la consulta
    fallback_models = [
        "gemini-2.0-flash",
        "gemini-1.5-flash", 
        "gemini-1.5-flash-001",
        "gemini-1.5-flash-002",
        "gemini-pro"
    ]

    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"⚠️ Error listando modelos ({response.status_code}). Usando lista de respaldo.")
            return fallback_models
            
        data = response.json()
        raw_models = [m['name'].replace('models/', '') for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        print(f"📋 Total modelos encontrados: {len(raw_models)}")

        # Lógica de Ordenamiento para Free Tier
        sorted_models = []
        
        # 1. Los reyes del Free Tier (Flash)
        priority_keywords = ['gemini-2.0-flash', 'gemini-1.5-flash']
        for keyword in priority_keywords:
            for m in raw_models:
                if keyword in m and m not in sorted_models:
                    sorted_models.append(m)
        
        # 2. Cualquier otro "flash" que haya sobrado
        for m in raw_models:
            if 'flash' in m and m not in sorted_models:
                sorted_models.append(m)
                
        # 3. Modelos Pro (Usar con precaución en Free Tier)
        for m in raw_models:
            if 'pro' in m and m not in sorted_models:
                sorted_models.append(m)
                
        # 4. El resto
        for m in raw_models:
            if m not in sorted_models:
                sorted_models.append(m)

        print(f"✅ Orden de prueba priorizado: {sorted_models[:5]}...")
        return sorted_models

    except Exception as e:
        print(f"❌ Error buscando modelos: {str(e)}")
        return fallback_models

def generate_meal_plan(history):
    """Generate a daily meal plan trying multiple models if necessary"""
    
    # 1. Obtener lista priorizada
    candidate_models = get_prioritized_models()
    
    # Get recent recipes context
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

    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}]}

    last_error = None

    # 2. Bucle de intentos: Probar modelos uno por uno
    for model_name in candidate_models:
        
        # Intentamos con y sin el prefijo 'models/' por inconsistencias de la API
        variations = [model_name, f"models/{model_name}"] if "models/" not in model_name else [model_name]
        
        for specific_model_name in variations:
            # Limpieza de slash doble por seguridad
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
                
                # Si falló, analizamos por qué
                error_msg = f"Error {response.status_code}: {response.text[:200]}..." # Log corto
                print(f"⚠️ Falló {specific_model_name}: {error_msg}")
                
                # Si es error 429 (Cuota) o 404 (No encontrado), continuamos al siguiente modelo inmediatamente
                
            except Exception as e:
                print(f"⚠️ Error de conexión con {specific_model_name}: {str(e)}")
                last_error = str(e)
                
        # Pequeña pausa antes del siguiente modelo para no saturar
        time.sleep(1)

    # Si salimos del bucle, todo falló
    raise Exception(f"Todos los modelos fallaron. Revise su API Key y cuotas.")

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
