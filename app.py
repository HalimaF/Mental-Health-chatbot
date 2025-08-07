import os
import logging
import random
import sqlite3
import json
from datetime import datetime, timedelta, date
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from flask_session import Session
import google.generativeai as genai
from deep_translator import GoogleTranslator, exceptions
from langdetect import detect, DetectorFactory
from dotenv import load_dotenv # Added this import statement
from werkzeug.security import generate_password_hash, check_password_hash

# Try to import markdown, fall back to basic formatting if not available
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    logging.warning("Markdown library not available. Using basic formatting.")

# Try to import sentiment analysis tools
try:
    from textblob import TextBlob
    SENTIMENT_AVAILABLE = True
except ImportError:
    SENTIMENT_AVAILABLE = False
    logging.warning("TextBlob not available. Sentiment analysis disabled.")

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
DetectorFactory.seed = 0
load_dotenv()

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
if not app.config["SECRET_KEY"]:
    app.logger.warning("SECRET_KEY environment variable not set. Using a default fallback. "
                       "Please set SECRET_KEY in your .env file for production.")
    app.config["SECRET_KEY"] = "a_very_secret_and_random_fallback_key_for_dev_only"

app.config["SESSION_TYPE"] = "filesystem"
if not os.path.exists("./flask_session"):
    os.makedirs("./flask_session")
app.config["SESSION_FILE_DIR"] = "./flask_session"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True

Session(app)

# Database initialization
def init_db():
    conn = sqlite3.connect('dil_azaad.db')
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    ''')
    
    # Chat history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT NOT NULL,
            response TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Mood tracking table for mental health insights
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mood_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            mood_score INTEGER CHECK(mood_score >= 1 AND mood_score <= 10),
            mood_tags TEXT, -- JSON array of mood descriptors
            journal_entry TEXT,
            coping_strategies_used TEXT, -- JSON array
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Mental health progress tracking
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mental_health_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            goal_type TEXT NOT NULL, -- anxiety_management, sleep_improvement, etc.
            goal_description TEXT,
            target_date DATE,
            progress_notes TEXT, -- JSON array of progress updates
            status TEXT DEFAULT 'active', -- active, completed, paused
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Enhanced sentiment analysis tracking for lightweight mental health insights
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sentiment_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_message TEXT,
            sentiment TEXT, -- severe_negative, moderate_negative, mild_negative, neutral, mild_positive, positive
            confidence_score REAL, -- 0 to 1 confidence level
            emotions_detected TEXT, -- comma-separated emotions
            crisis_flag INTEGER DEFAULT 0, -- 0 = no crisis, 1 = crisis detected
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # Add missing columns to existing sentiment_tracking table if they don't exist
    try:
        cursor.execute('ALTER TABLE sentiment_tracking ADD COLUMN confidence_score REAL DEFAULT 0.5')
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        cursor.execute('ALTER TABLE sentiment_tracking ADD COLUMN emotions_detected TEXT DEFAULT ""')
    except sqlite3.OperationalError:
        pass  # Column already exists
        
    try:
        cursor.execute('ALTER TABLE sentiment_tracking ADD COLUMN crisis_flag INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        cursor.execute('ALTER TABLE sentiment_tracking RENAME COLUMN message_text TO user_message')
    except sqlite3.OperationalError:
        pass  # Column already renamed or doesn't exist
    
    conn.commit()
    
    # Streak data table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_streaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            current_streak INTEGER DEFAULT 0,
            longest_streak INTEGER DEFAULT 0,
            last_checkin DATE,
            total_checkins INTEGER DEFAULT 0,
            streak_history TEXT, -- JSON string to store daily checkin data
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

# Database helper functions
def get_db_connection():
    conn = sqlite3.connect('dil_azaad.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_user_by_username(username):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    return user

def get_user_by_id(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user

def create_user(username, email, password):
    conn = get_db_connection()
    password_hash = generate_password_hash(password)
    try:
        cursor = conn.execute(
            'INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
            (username, email, password_hash)
        )
        user_id = cursor.lastrowid
        
        # Initialize streak data for new user
        conn.execute(
            'INSERT INTO user_streaks (user_id, streak_history) VALUES (?, ?)',
            (user_id, '{}')
        )
        
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def save_chat_message(user_id, message, response):
    if not user_id:  # Don't save for guest users
        return
    
    try:
        conn = get_db_connection()
        conn.execute(
            'INSERT INTO chat_history (user_id, message, response) VALUES (?, ?, ?)',
            (user_id, message, response)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        app.logger.error(f"Error saving chat message for user {user_id}: {e}")
        # Don't raise the error to prevent chat interruption

def save_guest_chat_for_demo(message, response):
    """Save guest conversations with a demo user ID for insights demo"""
    try:
        conn = get_db_connection()
        # Use a special demo user ID (99999) for guest conversations
        conn.execute(
            'INSERT INTO chat_history (user_id, message, response) VALUES (?, ?, ?)',
            (99999, message, response)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        app.logger.error(f"Error saving guest chat for demo: {e}")

def get_user_chat_history(user_id, limit=50):
    conn = get_db_connection()
    messages = conn.execute(
        'SELECT message, response, timestamp FROM chat_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?',
        (user_id, limit)
    ).fetchall()
    conn.close()
    return list(reversed(messages))  # Return in chronological order

def get_user_streak_data(user_id):
    conn = get_db_connection()
    streak_data = conn.execute(
        'SELECT * FROM user_streaks WHERE user_id = ?',
        (user_id,)
    ).fetchone()
    conn.close()
    
    if streak_data:
        history = json.loads(streak_data['streak_history'] or '{}')
        return {
            'current_streak': streak_data['current_streak'],
            'longest_streak': streak_data['longest_streak'],
            'last_checkin': streak_data['last_checkin'],
            'total_checkins': streak_data['total_checkins'],
            'history': history
        }
    return {
        'current_streak': 0,
        'longest_streak': 0,
        'last_checkin': None,
        'total_checkins': 0,
        'history': {}
    }

def update_user_streak(user_id, streak_data):
    conn = get_db_connection()
    history_json = json.dumps(streak_data.get('history', {}))
    conn.execute(
        '''UPDATE user_streaks 
           SET current_streak = ?, longest_streak = ?, last_checkin = ?, 
               total_checkins = ?, streak_history = ?
           WHERE user_id = ?''',
        (streak_data['current_streak'], streak_data['longest_streak'], 
         streak_data['last_checkin'], streak_data['total_checkins'], 
         history_json, user_id)
    )
    conn.commit()
    conn.close()

# In-memory user database (keeping for backward compatibility, but will migrate to SQLite)
users = {}
user_streaks = {}  # Track user streaks

GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    app.logger.error("GOOGLE_API_KEY not found in environment variables. "
                     "Please set it in your .env file or as a system environment variable.")
    raise ValueError("GOOGLE_API_KEY is not set.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

urdu_affirmations = [
    "آپ مضبوط ہیں اور آپ اس مشکل وقت سے گزر سکتے ہیں۔",
    "ہر دن ایک نیا موقع ہے بہتر محسوس کرنے کا۔",
    "آپ کی باتوں کی اہمیت ہے۔",
    "سانس لیں، آپ اکیلے نہیں ہیں۔",
    "آج کا دن مثبت خیالات کے لیے ہے۔"
]

english_affirmations = [
    "You are stronger than you think.",
    "Every day is a new beginning.",
    "Your feelings are valid.",
    "Take a deep breath — you are not alone.",
    "You deserve kindness, especially from yourself.",
    "You may feel that everyone and everything around you is perfect and you are the only one whose life is crumbling — remember you are not alone. Everyone is struggling; they just mask it better. It is okay to feel. It is okay to cry. Just remember to love yourself no matter what."
]

cbt_techniques = {
    "breathing": "Let us try a breathing exercise. Breathe in slowly for 4 seconds... hold... now breathe out slowly for 4 seconds. Repeat this 3 times.",
    "grounding": "Let us try the 5-4-3-2-1 grounding technique: Name 5 things you can see, 4 things you can touch, 3 things you can hear, 2 things you can smell, and 1 thing you can taste.",
    "muscle_relaxation": "Try progressive muscle relaxation: Tense your shoulders for 5 seconds, then release. Notice the difference between tension and relaxation.",
    "mindfulness": "Take a moment to focus on the present. What do you notice around you right now? Your breathing, the temperature, sounds around you?"
}

hotlines = {
    "karachi": "Umang Hotline: 0311-7786264",
    "lahore": "Rozan Helpline: 0304-1111741",
    "islamabad": "PAHCHAAN: 051-111555627",
    "rawalpindi": "Mind Organisation: 051-8090541",
    "emergency": "Emergency: 1122 or 15",
    "national": "National Crisis Helpline: 042-35761999"
}

mental_health_keywords = {
    "anxiety": ["anxious", "worried", "panic", "fear", "nervous", "پریشان", "خوف", "گھبراہٹ", "tension", "stress"],
    "depression": ["sad", "depressed", "hopeless", "empty", "down", "اداس", "مایوس", "خالی", "lonely", "worthless"],
    "stress": ["stressed", "overwhelmed", "pressure", "burden", "تناؤ", "دباؤ", "پریشانی", "exhausted", "burnout"],
    "sleep": ["insomnia", "cannot sleep", "nightmares", "tired", "نیند", "بے خوابی", "sleepless", "restless"],
    "crisis": ["suicide", "self harm", "hurt myself", "end it all", "خودکشی", "نقصان", "crisis", "kill myself", "die"],
    "loneliness": ["alone", "lonely", "isolated", "no friends", "اکیلا", "تنہا", "disconnected", "nobody cares"],
    "anger": ["angry", "rage", "furious", "irritated", "غصہ", "ناراض", "frustrated", "mad"],
    "grief": ["loss", "died", "death", "miss", "grief", "موت", "نقصان", "یاد", "mourning", "bereavement"],
    "trauma": ["trauma", "ptsd", "flashbacks", "triggered", "abuse", "violence", "accident", "صدمہ"],
    "relationships": ["breakup", "divorce", "fighting", "conflict", "family problems", "relationship", "marriage"],
    "work_stress": ["job stress", "workplace", "boss", "career", "unemployment", "work pressure", "office"],
    "body_image": ["ugly", "fat", "skinny", "appearance", "body", "weight", "eating disorder", "self-image"],
    "addiction": ["drugs", "alcohol", "gambling", "addiction", "substance", "drinking", "smoking", "نشہ"],
    "self_esteem": ["worthless", "useless", "failure", "not good enough", "low confidence", "inadequate"]
}

# Simple therapeutic responses without religious content
therapeutic_responses = {
    "anxiety": {
        "validation": "I understand you're feeling anxious right now.",
        "techniques": ["Try deep breathing - breathe in for 4, hold for 4, exhale for 4"],
        "affirmation": "This feeling will pass. You are safe right now."
    },
    "depression": {
        "validation": "I hear that you're going through a difficult time.",
        "techniques": ["Try to do one small thing today, even something tiny"],
        "affirmation": "You are not alone. Small steps can help."
    },
    "stress": {
        "validation": "Stress can feel overwhelming.",
        "techniques": ["Take breaks and prioritize what's truly important"],
        "affirmation": "You don't have to handle everything at once."
    },
    "trauma": {
        "validation": "Your feelings are completely valid.",
        "techniques": ["Focus on your safety in this moment"],
        "affirmation": "Healing takes time, and you're brave for working through this."
    }
}

responses = {
    "anxiety": [
        "I understand you are feeling anxious. This feeling will pass. Try the breathing exercise: breathe in for 4, hold for 4, breathe out for 4.",
        "Anxiety can feel overwhelming, but you are stronger than this feeling. Let us focus on what you can control right now."
    ],
    "depression": [
        "I hear that you are going through a really tough time. Your feelings are valid, and you do not have to go through this alone.",
        "Depression can make everything feel hopeless, but small steps matter. You reached out today - that is already something."
    ],
    "stress": [
        "Stress can feel overwhelming. Let us break it down - what is one small thing you can handle right now?",
        "When everything feels too much, remember: you have survived difficult times before. You are resilient."
    ],
    "crisis": [
        "I am concerned about you. Please reach out to someone who can help immediately: Emergency 1122, or National Crisis Helpline: 042-35761999", # Updated text
        "Your life has value. Please contact a crisis helpline immediately: National Crisis Helpline: 042-35761999" # Updated text
    ]
}

coping_suggestions = [
    "Take a warm shower or bath",
    "Listen to calming music",
    "Write down three things you are grateful for",
    "Call or text someone you trust",
    "Go for a short walk, even if it is just around your room",
    "Practice deep breathing for 2 minutes",
    "Drink a glass of water slowly",
    "Look at photos that make you smile"
]

fallback_responses = {
    "general": [
        "I hear you, and I want you to know that reaching out takes courage. Your feelings matter.",
        "Thank you for sharing with me. Whatever you are going through, you do not have to face it alone.",
        "I can sense that you are dealing with something difficult. Your strength in reaching out shows how brave you are.",
        "Your feelings are completely valid. It is okay to not be okay sometimes.",
        "I am here with you in this moment. You matter, and your experiences matter."
    ],
    "encouragement": [
        "You have made it through difficult times before, and you have the strength to get through this too.",
        "Every small step forward counts, even when progress feels slow.",
        "You are worthy of love, kindness, and support - especially from yourself.",
        "This feeling you are having right now is temporary, but you are strong and resilient.",
        "You do not have to have all the answers right now. Just taking it one moment at a time is enough."
    ],
    "roman_urdu_general": [
        "Main aap ki baat sun raha hun. Aap ne himmat kar ke baat kahi hai, ye bohot acha hai.",
        "Aap jo kuch bhi feel kar rahe hain, wo bilkul theek hai. Main aap ke saath hun.",
        "Aap akele nahi hain. Jo mushkil waqt aa raha hai, wo guzar jayega.",
        "Aap ki feelings important hain. Main samajh sakta hun aap kitni mushkil mein hain.",
        "Aap bohot brave hain jo aap ne apni baat share ki. Main yahan hun aap ke liye."
    ],
    "roman_urdu_encouragement": [
        "Aap pehle bhi mushkil waqt se guzre hain aur aap strong hain.",
        "Har chota step matter karta hai. Aap achha kar rahe hain.",
        "Aap mohabbat aur care deserve karte hain, especially apne aap se.",
        "Ye feeling temporary hai. Aap mazboot hain aur ye guzar jayega.",
        "Abhi aap ko sab answers nahi chahiye. Ek ek moment lein, bas."
    ]
}

# ============================================
# COST-FREE SENTIMENT ANALYSIS FUNCTIONS
# ============================================

def analyze_sentiment_lightweight(text):
    """
    Lightweight sentiment analysis using smart keyword matching.
    Returns sentiment score and detected mental health indicators.
    """
    text_lower = text.lower()
    
    # Mental health keyword categories with weighted scores
    keywords = {
        'severe_crisis': {
            'words': ['suicide', 'kill myself', 'end it all', 'want to die', 'harm myself', 
                     'better off dead', 'no point living', 'خودکشی', 'مرنا چاہتا', 'ختم کرنا'],
            'score': -10,
            'weight': 5.0
        },
        'depression_severe': {
            'words': ['hopeless', 'worthless', 'useless', 'failure', 'hate myself', 
                     'nothing matters', 'empty inside', 'نا امید', 'بیکار', 'ناکام'],
            'score': -8,
            'weight': 3.0
        },
        'anxiety_severe': {
            'words': ['panic attack', 'cant breathe', 'heart racing', 'terrified', 
                     'scared to death', 'پیرہیان', 'گھبراہٹ', 'ڈر'],
            'score': -7,
            'weight': 2.5
        },
        'depression_moderate': {
            'words': ['sad', 'depressed', 'down', 'low', 'unhappy', 'miserable',
                     'gloomy', 'blue', 'not great', 'feeling down', 'غمگین', 'اداس', 'پریشان'],
            'score': -5,
            'weight': 2.0
        },
        'anxiety_moderate': {
            'words': ['worried', 'anxious', 'nervous', 'stressed', 'tense',
                     'restless', 'uneasy', 'pareshaan', 'ghabra', 'پریشان', 'بےچین', 'تناؤ'],
            'score': -4,
            'weight': 1.5
        },
        'isolation': {
            'words': ['alone', 'lonely', 'isolated', 'no friends', 'nobody cares',
                     'تنہا', 'اکیلا', 'کوئی نہیں'],
            'score': -4,
            'weight': 1.5
        },
        'positive': {
            'words': ['happy', 'good', 'great', 'better', 'improving', 'grateful',
                     'thankful', 'blessed', 'خوش', 'اچھا', 'بہتر'],
            'score': 5,
            'weight': 1.0
        },
        'coping': {
            'words': ['trying', 'working on it', 'getting help', 'therapy',
                     'medication', 'support', 'کوشش', 'مدد'],
            'score': 3,
            'weight': 1.2
        }
    }
    
    detected_emotions = []
    total_score = 0
    total_weight = 0
    crisis_detected = False
    
    for category, data in keywords.items():
        for word in data['words']:
            if word in text_lower:
                detected_emotions.append(category)
                weighted_score = data['score'] * data['weight']
                total_score += weighted_score
                total_weight += data['weight']
                
                if category == 'severe_crisis':
                    crisis_detected = True
                    
                break  # Only count once per category
    
    # Normalize score
    if total_weight > 0:
        normalized_score = total_score / total_weight
    else:
        normalized_score = 0
    
    # Determine sentiment category
    if normalized_score <= -6:
        sentiment = 'severe_negative'
    elif normalized_score <= -3:
        sentiment = 'moderate_negative'
    elif normalized_score <= -1:
        sentiment = 'mild_negative'
    elif normalized_score <= 1:
        sentiment = 'neutral'
    elif normalized_score <= 3:
        sentiment = 'mild_positive'
    else:
        sentiment = 'positive'
    
    return {
        'sentiment': sentiment,
        'score': round(normalized_score, 2),
        'emotions': list(set(detected_emotions)),
        'crisis_detected': crisis_detected,
        'confidence': min(1.0, total_weight / 5.0)  # Confidence based on keyword matches
    }

def get_personalized_therapeutic_response(sentiment_data, user_message=""):
    """
    Generate personalized therapeutic responses ONLY for crisis situations.
    For regular mental health support, return None to let Gemini AI handle it concisely.
    """
    sentiment = sentiment_data['sentiment']
    emotions = sentiment_data['emotions']
    crisis = sentiment_data['crisis_detected']
    
    # Crisis intervention - highest priority (only case where we return detailed response)
    if crisis:
        return {
            'response_type': 'crisis_intervention',
            'message': """🚨 **IMMEDIATE SUPPORT NEEDED**

I'm very concerned about what you're sharing with me. Your life has value and meaning.

**IMMEDIATE HELP:**
• Pakistan: Umang Mental Health Helpline: 0317-6367833
• Emergency: 15 or 1122
• International: Crisis Text Line - Text HOME to 741741

**RIGHT NOW:**
• You are not alone in this
• These feelings can change with proper help
• Call someone - a friend, family member, or helpline
• Go to your nearest hospital if you're in immediate danger

Please reach out to a human counselor or crisis helpline immediately. I care about your wellbeing.""",
            'suggested_actions': ['call_crisis_hotline', 'reach_out_to_trusted_person', 'visit_emergency_room'],
            'mood_category': 'crisis'
        }
    # For all non-crisis situations, return None to let Gemini AI provide concise responses
    return None

def save_mood_tracking(user_id, sentiment_data, user_message):
    """
    Save mood and sentiment data for registered users.
    Provides analytics for mental health tracking.
    """
    if not user_id or user_id == 'guest':
        return False
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sentiment_tracking 
            (user_id, sentiment, confidence_score, emotions_detected, crisis_flag, user_message, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            sentiment_data['sentiment'],
            sentiment_data['confidence'],
            ','.join(sentiment_data['emotions']) if sentiment_data['emotions'] else '',
            1 if sentiment_data['crisis_detected'] else 0,
            user_message[:500],  # Limit message length for privacy
            datetime.now().isoformat()
        ))
        conn.commit()
        return True
    except Exception as e:
        app.logger.error(f"Error saving mood tracking: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ============================================

def _translate_response_to_original_lang(text, target_lang):
    if target_lang == 'en':
        return text
    try:
        translated_text = GoogleTranslator(source='en', target=target_lang).translate(text)
        if not translated_text:
            app.logger.warning(f"Translation to '{target_lang}' returned empty for: '{text}'. Returning original.")
            return text
        return translated_text
    except Exception as e:
        app.logger.error(f"Translation failed for '{text}' to '{target_lang}': {e}. Returning original text.")
        return text

def analyze_sentiment_and_emotion(text):
    """
    Analyze sentiment and emotional state of user input using TextBlob
    Returns sentiment data and emotional insights for therapeutic response
    """
    if not SENTIMENT_AVAILABLE:
        return {
            'sentiment': 'neutral',
            'polarity': 0.0,
            'subjectivity': 0.5,
            'emotion': 'neutral',
            'intensity': 'moderate',
            'therapeutic_note': ''
        }
    
    try:
        # Analyze with TextBlob
        blob = TextBlob(text)
        polarity = blob.sentiment.polarity  # -1 (negative) to 1 (positive)
        subjectivity = blob.sentiment.subjectivity  # 0 (objective) to 1 (subjective)
        
        # Determine sentiment category
        if polarity > 0.3:
            sentiment = 'positive'
        elif polarity < -0.3:
            sentiment = 'negative'
        else:
            sentiment = 'neutral'
        
        # Determine intensity
        abs_polarity = abs(polarity)
        if abs_polarity > 0.7:
            intensity = 'high'
        elif abs_polarity > 0.3:
            intensity = 'moderate'
        else:
            intensity = 'low'
        
        # Emotional analysis based on keywords and sentiment
        emotion = 'neutral'
        therapeutic_note = ''
        
        text_lower = text.lower()
        
        # Emotion detection based on keywords and sentiment
        if any(word in text_lower for word in ['anxious', 'worried', 'panic', 'fear', 'nervous', 'tense']):
            emotion = 'anxiety'
            therapeutic_note = 'User expressing anxiety-related concerns'
        elif any(word in text_lower for word in ['sad', 'depressed', 'down', 'hopeless', 'empty', 'lonely']):
            emotion = 'sadness'
            therapeutic_note = 'User expressing depressive feelings'
        elif any(word in text_lower for word in ['angry', 'frustrated', 'mad', 'furious', 'irritated']):
            emotion = 'anger'
            therapeutic_note = 'User expressing anger or frustration'
        elif any(word in text_lower for word in ['happy', 'excited', 'joy', 'great', 'amazing', 'wonderful']):
            emotion = 'happiness'
            therapeutic_note = 'User expressing positive emotions'
        elif any(word in text_lower for word in ['stressed', 'overwhelmed', 'pressure', 'burden', 'exhausted']):
            emotion = 'stress'
            therapeutic_note = 'User expressing stress or overwhelm'
        elif polarity < -0.5:
            emotion = 'distress'
            therapeutic_note = 'User expressing significant negative emotions'
        elif subjectivity > 0.7 and polarity > 0.2:
            emotion = 'hopeful'
            therapeutic_note = 'User expressing subjective positive feelings'
        
        return {
            'sentiment': sentiment,
            'polarity': round(polarity, 2),
            'subjectivity': round(subjectivity, 2),
            'emotion': emotion,
            'intensity': intensity,
            'therapeutic_note': therapeutic_note
        }
        
    except Exception as e:
        app.logger.error(f"Error in sentiment analysis: {e}")
        return {
            'sentiment': 'neutral',
            'polarity': 0.0,
            'subjectivity': 0.5,
            'emotion': 'neutral',
            'intensity': 'moderate',
            'therapeutic_note': 'Analysis unavailable'
        }

def format_ai_response(text):
    """Format AI response text using markdown if available, otherwise use enhanced HTML formatting."""
    
    if MARKDOWN_AVAILABLE:
        # Professional markdown-to-HTML conversion
        markdown_css = """
        <style>
            .ai-response {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
                line-height: 1.6;
                color: #2d4a3a;
            }
            .ai-response h1, .ai-response h2, .ai-response h3, .ai-response h4 {
                color: #1a5a3a;
                font-weight: 600;
                margin: 1.2em 0 0.6em 0;
                border-bottom: 2px solid #e8f5e8;
                padding-bottom: 0.3em;
            }
            .ai-response h1 { font-size: 1.4em; }
            .ai-response h2 { font-size: 1.3em; }
            .ai-response h3 { font-size: 1.2em; }
            .ai-response h4 { font-size: 1.1em; }
            .ai-response p {
                margin: 1em 0;
                text-align: justify;
            }
            .ai-response ul, .ai-response ol {
                margin: 1em 0;
                padding-left: 1.5em;
            }
            .ai-response li {
                margin: 0.5em 0;
                line-height: 1.5;
            }
            .ai-response ul li {
                list-style-type: none;
                position: relative;
            }
            .ai-response ul li:before {
                content: "•";
                color: #27ae60;
                font-weight: bold;
                position: absolute;
                left: -1em;
            }
            .ai-response strong {
                color: #1a5a3a;
                font-weight: 600;
            }
            .ai-response em {
                color: #2980b9;
                font-style: italic;
            }
        </style>
        """
        
        # Configure markdown with extensions
        md = markdown.Markdown(extensions=[
            'markdown.extensions.extra',
            'markdown.extensions.nl2br',
            'markdown.extensions.sane_lists'
        ])
        
        html_content = md.convert(text)
        return f'{markdown_css}<div class="ai-response">{html_content}</div>'
    
    else:
        # Fallback: Enhanced HTML formatting without markdown
        formatted_html = ""
        paragraphs = text.split('\n\n')
        
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            
            # Check for headings (lines starting with ## or ### or ending with :)
            if paragraph.startswith('##'):
                heading_text = paragraph.lstrip('#').strip()
                level = min(len(paragraph) - len(paragraph.lstrip('#')), 4)
                formatted_html += f'<h{level+1} style="color: #1a5a3a; font-weight: 600; margin: 1.2em 0 0.6em 0; border-bottom: 2px solid #e8f5e8; padding-bottom: 0.3em;">{heading_text}</h{level+1}>'
            
            # Check for lists (lines starting with - or * or numbers)
            elif any(line.strip().startswith(('-', '*', '•')) for line in paragraph.split('\n')):
                formatted_html += '<ul style="margin: 1em 0; padding-left: 1.5em;">'
                for line in paragraph.split('\n'):
                    line = line.strip()
                    if line.startswith(('-', '*', '•')):
                        clean_line = line.lstrip('-*• ').strip()
                        formatted_html += f'<li style="margin: 0.5em 0; list-style: none; position: relative;"><span style="color: #27ae60; font-weight: bold; position: absolute; left: -1em;">•</span>{clean_line}</li>'
                formatted_html += '</ul>'
            
            # Regular paragraph with bold/italic formatting
            else:
                # Simple bold/italic formatting
                paragraph = paragraph.replace('**', '<strong>').replace('**', '</strong>')
                paragraph = paragraph.replace('*', '<em>').replace('*', '</em>')
                formatted_html += f'<p style="margin: 1em 0; line-height: 1.6; color: #2d4a3a; text-align: justify;">{paragraph}</p>'
        
        return f'<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', \'Roboto\', sans-serif;">{formatted_html}</div>'

@app.route("/")
def welcome():
    return render_template('welcome.html')

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        if not username or not password:
            flash("Username and password are required", "error")
            return render_template('login.html')
        
        user = get_user_by_username(username)
        
        if user and check_password_hash(user['password_hash'], password):
            session["user"] = username
            session["user_id"] = user['id']
            
            # Update last login
            conn = get_db_connection()
            conn.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
            conn.commit()
            conn.close()
            
            flash("Login successful!", "success")
            return redirect(url_for("chat"))
        else:
            flash("Invalid username or password", "error")
    
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        email = request.form.get("email")
        
        if not username or not password or not email:
            flash("All fields are required", "error")
        elif len(password) < 6:
            flash("Password must be at least 6 characters", "error")
        else:
            if create_user(username, email, password):
                flash("Registration successful! Please login.", "success")
                return redirect(url_for("login"))
            else:
                flash("Username or email already exists", "error")
    
    return render_template('register.html')

@app.route("/logout")
def logout():
    session.pop("user", None)
    session.pop("user_id", None)
    flash("Logged out successfully", "success")
    return redirect(url_for("welcome"))

@app.route("/mood_tracking")
def mood_tracking():
    # Redirect to sentiment insights which provides better analytics
    return redirect(url_for("sentiment_insights"))

@app.route("/log_mood", methods=["POST"])
def log_mood():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json()
    user_id = session.get("user_id")
    mood_score = data.get("mood_score")
    mood_tags = json.dumps(data.get("mood_tags", []))
    journal_entry = data.get("journal_entry", "")
    coping_strategies = json.dumps(data.get("coping_strategies", []))
    
    if not mood_score or not (1 <= mood_score <= 10):
        return jsonify({"error": "Valid mood score (1-10) required"}), 400
    
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO mood_entries (user_id, mood_score, mood_tags, journal_entry, coping_strategies_used) VALUES (?, ?, ?, ?, ?)',
        (user_id, mood_score, mood_tags, journal_entry, coping_strategies)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"message": "Mood logged successfully!"})

@app.route("/mental_health_insights")
def mental_health_insights():
    # Redirect to sentiment insights which provides comprehensive analytics
    return redirect(url_for("sentiment_insights"))

def analyze_chat_history_for_insights(chat_history):
    """Analyze chat history to generate mental health insights"""
    if not chat_history:
        return {
            "conversation_count": 0,
            "emotional_themes": [],
            "activity_pattern": [],
            "progress_indicators": []
        }
    
    # Basic conversation analytics
    conversation_count = len(chat_history)
    
    # Analyze emotional themes from user messages
    emotional_keywords = {
        "anxiety": ["anxious", "worried", "stress", "panic", "nervous", "overwhelmed"],
        "depression": ["sad", "depressed", "hopeless", "empty", "worthless", "lonely"],
        "anger": ["angry", "frustrated", "mad", "irritated", "furious"],
        "positive": ["happy", "good", "better", "grateful", "thankful", "excited"],
        "support": ["help", "support", "advice", "guidance", "listen"]
    }
    
    theme_counts = {theme: 0 for theme in emotional_keywords.keys()}
    
    # Count emotional themes in user messages
    for chat in chat_history:
        message_lower = chat['message'].lower()
        for theme, keywords in emotional_keywords.items():
            if any(keyword in message_lower for keyword in keywords):
                theme_counts[theme] += 1
    
    # Get top emotional themes
    emotional_themes = [
        {"theme": theme.title(), "count": count} 
        for theme, count in sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
        if count > 0
    ]
    
    # Analyze activity pattern by day
    activity_by_date = {}
    for chat in chat_history:
        date = chat['timestamp'][:10]  # Extract date part
        activity_by_date[date] = activity_by_date.get(date, 0) + 1
    
    activity_pattern = [
        {"date": date, "count": count} 
        for date, count in sorted(activity_by_date.items())
    ]
    
    # Progress indicators
    progress_indicators = []
    if conversation_count >= 5:
        progress_indicators.append("You've engaged in multiple conversations - great for building consistency!")
    if theme_counts.get('positive', 0) > 0:
        progress_indicators.append("You've shared positive moments - celebrating progress is important!")
    if theme_counts.get('support', 0) > 0:
        progress_indicators.append("You're actively seeking support - that shows strength and wisdom!")
    
    return {
        "conversation_count": conversation_count,
        "emotional_themes": emotional_themes[:5],  # Top 5 themes
        "activity_pattern": activity_pattern,
        "progress_indicators": progress_indicators
    }

@app.route("/streak")
def streak():
    if "user" not in session:
        return redirect(url_for("login"))
    
    user_id = session.get("user_id")
    streak_data = get_user_streak_data(user_id)
    
    # Generate graph data for the last 30 days
    today = date.today()
    graph_data = []
    
    for i in range(29, -1, -1):  # Last 30 days
        day = today - timedelta(days=i)
        day_str = day.strftime('%Y-%m-%d')
        checked_in = day_str in streak_data.get('history', {})
        graph_data.append({
            'date': day_str,
            'day': day.strftime('%d'),
            'month': day.strftime('%b'),
            'checked_in': checked_in
        })
    
    return render_template('streak.html', streak_data=streak_data, graph_data=graph_data)

@app.route("/checkin", methods=["POST"])
def checkin():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    user_id = session.get("user_id")
    today = date.today()
    today_str = today.strftime('%Y-%m-%d')
    
    streak_data = get_user_streak_data(user_id)
    
    # Check if already checked in today
    if today_str in streak_data.get('history', {}):
        return jsonify({
            "current_streak": streak_data["current_streak"],
            "longest_streak": streak_data["longest_streak"],
            "message": "Already checked in today!"
        })
    
    last_checkin = streak_data.get("last_checkin")
    
    if last_checkin:
        last_checkin_date = datetime.strptime(last_checkin, "%Y-%m-%d").date()
        if today - last_checkin_date == timedelta(days=1):
            streak_data["current_streak"] += 1
        elif today - last_checkin_date > timedelta(days=1):
            streak_data["current_streak"] = 1
    else:
        streak_data["current_streak"] = 1
    
    streak_data["last_checkin"] = today_str
    streak_data["total_checkins"] += 1
    
    # Add to history
    if 'history' not in streak_data:
        streak_data['history'] = {}
    streak_data['history'][today_str] = True
    
    if streak_data["current_streak"] > streak_data["longest_streak"]:
        streak_data["longest_streak"] = streak_data["current_streak"]
    
    update_user_streak(user_id, streak_data)
    
    return jsonify({
        "current_streak": streak_data["current_streak"],
        "longest_streak": streak_data["longest_streak"],
        "message": "Check-in successful!"
    })

@app.route("/get_streak_data")
def get_streak_data():
    if "user" not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    user_id = session.get("user_id")
    streak_data = get_user_streak_data(user_id)
    
    return jsonify({
        "current_streak": streak_data["current_streak"],
        "longest_streak": streak_data["longest_streak"],
        "total_checkins": streak_data["total_checkins"],
        "last_checkin": streak_data["last_checkin"]
    })

@app.route("/static/<path:filename>")
def static_files(filename):
    return app.send_static_file(filename)

@app.route("/chat")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    
    # Get chat history for logged-in users
    user_id = session.get("user_id")
    chat_history = get_user_chat_history(user_id) if user_id else []
    
    return render_template('chat.html', chat_history=chat_history)

@app.route("/guest")
def guest_chat():
    return render_template('guest_chat.html')

@app.route("/chat_history")
def chat_history_page():
    if "user" not in session:
        return redirect(url_for("login"))
    
    try:
        user_id = session.get("user_id")
        chat_history = get_user_chat_history(user_id, limit=100)  # Get last 100 conversations
        
        # Ensure chat_history is a list
        if chat_history is None:
            chat_history = []
        
        return render_template('chat_history.html', chat_history=chat_history)
    except Exception as e:
        app.logger.error(f"Error loading chat history for user {session.get('user_id')}: {e}")
        # Return empty history on error
        return render_template('chat_history.html', chat_history=[])

@app.route("/get_chat_history")
def get_chat_history():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    user_id = session["user_id"]
    chat_history = get_user_chat_history(user_id)
    
    return jsonify({"chat_history": [
        {
            "message": row["message"],
            "response": row["response"],
            "timestamp": row["timestamp"]
        } for row in chat_history
    ]})

@app.route("/chat", methods=["POST"])
def chat():
    """Simple chat endpoint using only Gemini AI without religious phrases"""
    print("=== DEBUG: Chat function called ===")  # Simple print to console
    app.logger.info("=== DEBUG: Chat function called ===")
    
    data = request.get_json()
    user_input = data.get("message", data.get("user_input", "")).strip()
    original_user_input = user_input  # Keep original case
    app.logger.info(f"Received user input: '{user_input}'")

    # Simple sentiment analysis for crisis detection only
    sentiment_data = analyze_sentiment_lightweight(original_user_input)
    app.logger.info(f"Lightweight sentiment analysis: {sentiment_data}")
    
    # Save mood tracking for registered users (if logged in)
    if "user_id" in session:
        save_mood_tracking(session["user_id"], sentiment_data, original_user_input)

    # FORCE SIMPLE GEMINI RESPONSE FOR ALL CASES (NO COMPLEX SYSTEM)
    app.logger.info("DEBUG: About to bypass all complex logic and use simple Gemini")
    try:
        app.logger.info("DEBUG: Inside try block for simple response")
        simple_prompt = f"""You are a mental health support bot. Be brief and helpful.

        Rules:
        - Answer in 1-2 sentences only
        - No religious phrases at all
        - No Islamic greetings or phrases
        - No "Allah hafiz" or similar
        - Keep responses secular
        - Be supportive but brief
        
        User said: "{original_user_input}"
        
        Give a brief, helpful response in 30 words or less.
        """
        
        app.logger.info(f"DEBUG: Calling Gemini with prompt: {simple_prompt[:100]}...")
        response = model.generate_content(simple_prompt)
        clean_response = response.text.strip()
        app.logger.info(f"DEBUG: Got Gemini response: {clean_response}")
        
        formatted_response = f'''
        <div style="background: #f8fff8; border-left: 4px solid #10B981; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <p style="color: #2c3e50; margin: 0; line-height: 1.5;">{clean_response}</p>
        </div>
        '''
        
        app.logger.info(f"DEBUG: About to return simple response: {formatted_response[:100]}...")
        
        if "user_id" in session:
            save_chat_message(session["user_id"], original_user_input, formatted_response)
        
        return jsonify({"response": formatted_response})
        
    except Exception as e:
        app.logger.error(f"DEBUG: Exception in simple response: {e}")
        fallback_response = f'''
        <div style="background: #fff8e7; border-left: 4px solid #f39c12; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <p style="color: #2c3e50; margin: 0; line-height: 1.5;">I'm here to help. Could you tell me more about how you're feeling?</p>
        </div>
        '''
        
        if "user_id" in session:
            save_chat_message(session["user_id"], original_user_input, fallback_response)
        
        return jsonify({"response": fallback_response})

    # Crisis intervention - ONLY for genuine emergencies
    if sentiment_data.get('crisis_detected', False):
        crisis_response = f'''
        <div style="background: #ffe6e6; border-left: 4px solid #ff4444; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <h3 style="color: #cc0000; margin-bottom: 10px;">🚨 Immediate Support Needed</h3>
            <p style="margin: 10px 0;">I'm concerned about what you're sharing. Your life has value.</p>
            <p style="margin: 10px 0;"><strong>Emergency Help:</strong></p>
            <ul style="margin: 10px 0; padding-left: 20px;">
                <li>Pakistan: Emergency 15 or 1122</li>
                <li>Mental Health: Umang Helpline 0317-6367833</li>
                <li>Crisis Text Line: Text HOME to 741741</li>
            </ul>
            <p style="margin: 10px 0;">Please reach out to a human counselor or crisis helpline immediately.</p>
        </div>
        '''
        
        if "user_id" in session:
            save_chat_message(session["user_id"], original_user_input, crisis_response)
        
        return jsonify({"response": crisis_response})

    # For ALL non-crisis situations: Use simple Gemini AI
    try:
        # Simple prompt without religious context or cultural additions
        simple_prompt = f"""You are a helpful mental health support chatbot. 

        CRITICAL RULES:
        - Respond in EXACTLY 1-2 sentences maximum (30 words or less)
        - Be supportive but brief
        - Give ONE practical suggestion
        - NO religious phrases (no Allah, Assalam, Peace be upon, etc.)
        - NO cultural phrases or greetings
        - NO Urdu/Hindi phrases  
        - Plain English only
        - No headings, lists, or formatting
        - Keep responses secular and universal
        
        User said: "{user_input}"
        
        Give a brief helpful response in 1-2 sentences.
        """
        
        response = model.generate_content(simple_prompt)
        clean_response = response.text.strip()
        app.logger.info(f"Gemini response: '{clean_response}'")
        
        # Simple HTML formatting
        formatted_response = f'''
        <div style="background: #f8fff8; border-left: 4px solid #10B981; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <p style="color: #2c3e50; margin: 0; line-height: 1.5;">{clean_response}</p>
        </div>
        '''
        
        # Save to database if user is logged in
        if "user_id" in session:
            save_chat_message(session["user_id"], original_user_input, formatted_response)
        
        return jsonify({"response": formatted_response})
        
    except Exception as e:
        app.logger.error(f"Error with Gemini AI: {e}")
        
        # Simple fallback without religious phrases
        fallback_text = "I'm here to support you. Could you tell me more about how you're feeling?"
        fallback_response = f'''
        <div style="background: #fff8e7; border-left: 4px solid #f39c12; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <p style="color: #2c3e50; margin: 0; line-height: 1.5;">{fallback_text}</p>
        </div>
        '''
        
        if "user_id" in session:
            save_chat_message(session["user_id"], original_user_input, fallback_response)
        
        return jsonify({"response": fallback_response})
        
        # Detect user's preferred language for the response
        if original_lang == 'ur':
            translated_input_for_gemini = _translate_to_english(original_user_input)
        else:
            translated_input_for_gemini = original_user_input

        # Ultra-concise therapeutic prompt for Gemini
        mental_health_prompt = f"""You are a mental health chatbot that provides ultra-brief, supportive responses. 

        CRITICAL: Respond in EXACTLY 1-2 sentences only. No lists, no formatting, no headings. Maximum 30 words total.

        User's emotional state: {sentiment_data['sentiment']} (confidence: {sentiment_data['confidence']})
        Crisis level: {'HIGH' if sentiment_data['crisis_detected'] else 'Normal'}
        
        Response rules:
        - Maximum 30 words total
        - Be warm but brief
        - Give ONE specific tip
        - No markdown formatting
        - Plain text only
        - NO religious phrases (no Allah, Assalam, Peace be upon, etc.)
        - Keep responses secular and universal
        - No greetings or sign-offs
        
        User said: "{translated_input_for_gemini}"
        
        Respond in 1-2 sentences with one practical suggestion. Do not add religious phrases.
        """
        
        gemini_response_object = model.generate_content(mental_health_prompt)
        english_response_from_gemini = gemini_response_object.text.strip()
        app.logger.info(f"Gemini's English response: '{english_response_from_gemini}'")

        final_response_text = _translate_response_to_original_lang(english_response_from_gemini, original_lang)
        
        # Simple response formatting for concise messages
        gemini_response_html = f'''
        <div style="background: #f8fff8; border-left: 4px solid #10B981; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <p style="color: #2c3e50; margin: 0; line-height: 1.5;">{final_response_text}</p>
        </div>
        '''
        
        # Save to database if user is logged in
        if "user_id" in session:
            save_chat_message(session["user_id"], original_user_input, gemini_response_html)
        
        return jsonify({"response": gemini_response_html})

    except Exception as e:
        app.logger.error(f"Error getting response from Gemini: {e}. Using simple fallback.")
        
        # Simple fallback message for non-crisis situations
        fallback_text = "I'm here to support you. Please try rephrasing your message."
        fallback_text = _translate_response_to_original_lang(fallback_text, original_lang)
        
        fallback_html = f'''
        <div style="background: #f8fff8; border-left: 4px solid #10B981; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <p style="color: #2c3e50; margin: 0; line-height: 1.5;">{fallback_text}</p>
        </div>
        '''
        
        if "user_id" in session:
            save_chat_message(session["user_id"], original_user_input, fallback_html)
        
        return jsonify({"response": fallback_html})

    # --- BELOW: Keep only essential specific responses ---

    # --- Hotline suggestion (keep for emergency resources) ---
    for city, number in hotlines.items():
        if city.lower() in user_input.lower():
            hotline_response_html = f'''
            <div style="background: #e8f5e8; border-left: 4px solid #27ae60; padding: 15px; border-radius: 10px; margin: 10px 0;">
                <h3 style="color: #27ae60; margin-bottom: 10px;">� {_translate_response_content("Mental Health Resources")}</h3>
                <div style="background: white; padding: 10px; border-radius: 5px; margin: 10px 0;">
                    <strong>{_translate_response_content(number)}</strong>
                </div>
                <p>{_translate_response_content("Professional help is available. Don't hesitate to reach out.")}</p>
            </div>
            '''
            return jsonify({"response": hotline_response_html})

    # --- Simple final fallback (should rarely be reached) ---
    fallback_text = "I'm here to support you. Please try rephrasing your message."
    fallback_text = _translate_response_to_original_lang(fallback_text, original_lang)
    
    fallback_html = f'''
    <div style="background: #fff8e7; border-left: 4px solid #f39c12; padding: 15px; border-radius: 8px; margin: 10px 0;">
        <p style="color: #2c3e50; margin: 0; line-height: 1.5;">{fallback_text}</p>
    </div>
    '''
    
    if "user_id" in session:
        save_chat_message(session["user_id"], original_user_input, fallback_html)
    
    return jsonify({"response": fallback_html})

@app.route("/test_simple", methods=["POST"])
def test_simple_response():
    """Test endpoint for simple Gemini responses without religious phrases"""
    try:
        data = request.get_json()
        user_input = data.get("message", "").strip().lower()
        
        # Simple prompt without religious context
        simple_prompt = f"""Respond briefly and helpfully to this message in 1-2 sentences maximum. 
        No religious phrases, no greetings, no sign-offs. Just helpful advice.
        
        User said: "{user_input}"
        """
        
        response = model.generate_content(simple_prompt)
        clean_response = response.text.strip()
        
        return jsonify({
            "response": f'<div style="padding: 10px; background: #f0f8ff; border-radius: 5px;">{clean_response}</div>'
        })
    except Exception as e:
        return jsonify({
            "response": f'<div style="padding: 10px; background: #ffe0e0; border-radius: 5px;">Error: {str(e)}</div>'
        })

@app.route("/sentiment_insights")
def sentiment_insights():
    """Enhanced sentiment analysis with comprehensive chat analytics"""
    
    # Get user ID - use demo user (99999) if not logged in
    if "user_id" in session:
        user_id = session.get("user_id")
    else:
        # Show demo data from guest conversations
        user_id = 99999
    
    # Get chat history for analysis
    conn = get_db_connection()
    chat_history = conn.execute('''
        SELECT message, response, timestamp
        FROM chat_history 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 100
    ''', (user_id,)).fetchall()
    
    conn.close()
    
    if not chat_history:
        return render_template('sentiment_insights.html', 
                             recent_sentiments=[], sentiment_stats=[], sentiment_labels=[], 
                             sentiment_counts=[], chart_colors=[], emotion_frequency={},
                             daily_dates=[], daily_sentiment_scores=[], daily_crisis_alerts=[],
                             insights=[], conversation_insights={}, progress_metrics={},
                             mood_trends=[], weekly_summary={})
    
    # COMPREHENSIVE ANALYTICS ENGINE
    analytics = {
        'conversations': [],
        'emotions': {},
        'themes': {},
        'progress_indicators': {},
        'time_patterns': {},
        'crisis_tracking': [],
        'mood_trends': [],
        'conversation_quality': {},
        'coping_strategies': []
    }
    
    # Enhanced emotional keyword mapping
    enhanced_keywords = {
        "anxiety": ["anxious", "worried", "stress", "panic", "nervous", "overwhelmed", "afraid", "tense", "restless"],
        "depression": ["sad", "depressed", "hopeless", "empty", "worthless", "lonely", "down", "low", "gloomy"],
        "anger": ["angry", "frustrated", "mad", "irritated", "furious", "upset", "rage", "annoyed"],
        "positive": ["happy", "good", "better", "grateful", "thankful", "excited", "joy", "great", "amazing", "wonderful"],
        "neutral": ["ok", "fine", "normal", "regular", "usual", "alright"],
        "sleep_issues": ["insomnia", "can't sleep", "tired", "exhausted", "sleepless", "nightmares"],
        "relationships": ["family", "friends", "partner", "spouse", "relationship", "social", "people"],
        "work_stress": ["job", "work", "career", "boss", "office", "workplace", "employment"],
        "self_esteem": ["confidence", "self-worth", "failure", "success", "achievement", "pride"],
        "physical_health": ["pain", "sick", "health", "body", "physical", "medical"],
        "future_concerns": ["future", "tomorrow", "plans", "goals", "dreams", "hopes", "fears"]
    }
    
    # Analyze each conversation
    recent_sentiments = []
    theme_counts = {theme: 0 for theme in enhanced_keywords.keys()}
    daily_patterns = {}
    word_frequency = {}
    conversation_lengths = []
    time_of_day_patterns = {"morning": 0, "afternoon": 0, "evening": 0, "night": 0}
    
    for i, chat in enumerate(chat_history):
        message = chat['message'].lower()
        message_words = message.split()
        conversation_lengths.append(len(message_words))
        
        # Time pattern analysis
        try:
            hour = int(chat['timestamp'][11:13])
            if 5 <= hour < 12:
                time_of_day_patterns["morning"] += 1
            elif 12 <= hour < 17:
                time_of_day_patterns["afternoon"] += 1
            elif 17 <= hour < 21:
                time_of_day_patterns["evening"] += 1
            else:
                time_of_day_patterns["night"] += 1
        except:
            pass
        
        # Word frequency analysis
        for word in message_words:
            if len(word) > 3:  # Only count meaningful words
                word_frequency[word] = word_frequency.get(word, 0) + 1
        
        # Enhanced emotion detection
        detected_emotions = []
        sentiment_score = 0
        intensity = 1
        
        for theme, keywords in enhanced_keywords.items():
            matches = sum(1 for keyword in keywords if keyword in message)
            if matches > 0:
                theme_counts[theme] += matches
                detected_emotions.append(f"{theme}({matches})")
                
                # Calculate sentiment impact
                if theme in ["anxiety", "depression", "anger", "sleep_issues"]:
                    sentiment_score -= matches * 2
                elif theme == "positive":
                    sentiment_score += matches * 3
                elif theme in ["relationships", "self_esteem"] and any(pos in message for pos in ["good", "better", "happy"]):
                    sentiment_score += matches
                else:
                    sentiment_score -= matches * 0.5
        
        # Crisis detection
        crisis_keywords = ["suicide", "kill myself", "end it all", "want to die", "hurt myself", "self harm", "hopeless", "worthless"]
        crisis_detected = any(keyword in message for keyword in crisis_keywords)
        
        # Determine overall sentiment
        if sentiment_score <= -5:
            sentiment_type = "severe_negative"
        elif sentiment_score <= -2:
            sentiment_type = "moderate_negative" 
        elif sentiment_score <= 0:
            sentiment_type = "mild_negative"
        elif sentiment_score <= 2:
            sentiment_type = "neutral"
        elif sentiment_score <= 4:
            sentiment_type = "mild_positive"
        else:
            sentiment_type = "positive"
        
        # Store conversation analysis
        chat_date = chat['timestamp'][:10]
        recent_sentiments.append({
            'sentiment': sentiment_type,
            'emotions_detected': ', '.join(detected_emotions[:3]) if detected_emotions else 'neutral',
            'timestamp': chat['timestamp'],
            'crisis_flag': crisis_detected,
            'confidence_score': min(0.9, 0.4 + (len(detected_emotions) * 0.1)),
            'sentiment_score': sentiment_score,
            'word_count': len(message_words)
        })
        
        # Daily aggregation
        if chat_date not in daily_patterns:
            daily_patterns[chat_date] = {"positive": 0, "negative": 0, "neutral": 0, "score_sum": 0, "count": 0}
        
        daily_patterns[chat_date]["count"] += 1
        daily_patterns[chat_date]["score_sum"] += sentiment_score
        
        if sentiment_score > 0:
            daily_patterns[chat_date]["positive"] += 1
        elif sentiment_score < -1:
            daily_patterns[chat_date]["negative"] += 1
        else:
            daily_patterns[chat_date]["neutral"] += 1
    
    # GENERATE INSIGHTS AND METRICS
    
    # 1. Progress Analysis
    progress_metrics = {}
    if len(recent_sentiments) >= 5:
        recent_scores = [s['sentiment_score'] for s in recent_sentiments[:10]]
        older_scores = [s['sentiment_score'] for s in recent_sentiments[10:20]] if len(recent_sentiments) > 10 else [0]
        
        recent_avg = sum(recent_scores) / len(recent_scores)
        older_avg = sum(older_scores) / len(older_scores)
        
        progress_metrics = {
            'recent_mood_avg': round(recent_avg, 1),
            'older_mood_avg': round(older_avg, 1),
            'improvement': recent_avg > older_avg,
            'improvement_amount': round(abs(recent_avg - older_avg), 1)
        }
    
    # 2. Conversation Quality Analysis  
    avg_conversation_length = sum(conversation_lengths) / len(conversation_lengths) if conversation_lengths else 0
    conversation_insights = {
        'total_conversations': len(chat_history),
        'avg_length': round(avg_conversation_length, 1),
        'longest_conversation': max(conversation_lengths) if conversation_lengths else 0,
        'engagement_level': 'High' if avg_conversation_length > 15 else 'Medium' if avg_conversation_length > 8 else 'Low'
    }
    
    # 3. Top concerns identification
    top_concerns = sorted([(theme, count) for theme, count in theme_counts.items() if count > 0], 
                         key=lambda x: x[1], reverse=True)[:5]
    
    # 4. Weekly summary
    weekly_summary = {
        'most_active_time': max(time_of_day_patterns, key=time_of_day_patterns.get),
        'primary_emotions': [concern[0] for concern in top_concerns[:3]],
        'conversation_frequency': len(chat_history),
        'crisis_alerts': sum(1 for s in recent_sentiments if s['crisis_flag'])
    }
    
    # 5. Prepare chart data
    sentiment_labels = [theme.replace('_', ' ').title() for theme, count in top_concerns]
    sentiment_counts = [count for theme, count in top_concerns]
    
    color_map = {
        "Anxiety": "#e74c3c", "Depression": "#8e44ad", "Anger": "#e67e22",
        "Positive": "#27ae60", "Neutral": "#95a5a6", "Sleep Issues": "#3498db",
        "Relationships": "#f39c12", "Work Stress": "#e74c3c", "Self Esteem": "#9b59b6",
        "Physical Health": "#1abc9c", "Future Concerns": "#34495e"
    }
    chart_colors = [color_map.get(label, "#95a5a6") for label in sentiment_labels]
    
    # 6. Daily mood trends
    daily_dates_sorted = sorted(daily_patterns.keys())[-14:]  # Last 14 days
    daily_sentiment_scores = []
    daily_crisis_alerts = []
    
    for date in daily_dates_sorted:
        if daily_patterns[date]["count"] > 0:
            avg_score = daily_patterns[date]["score_sum"] / daily_patterns[date]["count"]
            # Convert to 1-10 scale
            mood_score = max(1, min(10, 5 + avg_score))
        else:
            mood_score = 5
        
        daily_sentiment_scores.append(mood_score)
        crisis_count = sum(1 for s in recent_sentiments 
                          if s['timestamp'][:10] == date and s['crisis_flag'])
        daily_crisis_alerts.append(crisis_count)
    
    # 7. Emotion frequency for display
    emotion_frequency = dict(top_concerns)
    
    # 8. Create sentiment stats
    sentiment_stats = [{'type': theme, 'count': count} for theme, count in top_concerns]
    
    return render_template('sentiment_insights.html', 
                         recent_sentiments=recent_sentiments[:20],  # Show recent 20
                         sentiment_stats=sentiment_stats,  
                         sentiment_labels=sentiment_labels,
                         sentiment_counts=sentiment_counts,
                         chart_colors=chart_colors,
                         emotion_frequency=emotion_frequency,
                         daily_dates=daily_dates_sorted,
                         daily_sentiment_scores=daily_sentiment_scores,
                         daily_crisis_alerts=daily_crisis_alerts,
                         insights=[],
                         conversation_insights=conversation_insights,
                         progress_metrics=progress_metrics,
                         mood_trends=daily_sentiment_scores,
                         weekly_summary=weekly_summary)

@app.route("/chat_clean", methods=["POST"])
def chat_clean():
    """Clean chat endpoint without religious phrases"""
    print("=== CLEAN CHAT ENDPOINT CALLED ===")
    app.logger.info("=== CLEAN CHAT ENDPOINT CALLED ===")
    
    data = request.get_json()
    user_input = data.get("message", "").strip()
    
    # Basic crisis detection
    crisis_keywords = ['suicide', 'kill myself', 'end my life', 'want to die', 'harm myself', 'suicidal', 'no point living']
    is_crisis = any(keyword in user_input.lower() for keyword in crisis_keywords)
    
    if is_crisis:
        crisis_response = f'''
        <div style="background: #ffe6e6; border-left: 4px solid #ff4444; padding: 20px; border-radius: 8px; margin: 10px 0; border: 1px solid #ffcccc;">
            <h3 style="color: #cc0000; margin-top: 0; margin-bottom: 15px;">🚨 Immediate Support Available</h3>
            <p style="color: #2c3e50; margin: 10px 0; line-height: 1.6; font-weight: 500;">Your life has value. Please reach out for help immediately:</p>
            
            <div style="background: #fff; padding: 15px; border-radius: 6px; margin: 10px 0; border: 1px solid #ddd;">
                <h4 style="color: #1a5a3a; margin-top: 0; margin-bottom: 10px;">🇵🇰 Pakistan Mental Health Helplines:</h4>
                <ul style="margin: 0; padding-left: 20px; line-height: 1.8;">
                    <li><strong>Umang Helpline:</strong> <a href="tel:0317-6367833" style="color: #007bff; text-decoration: none;">0317-6367833</a> (24/7 Mental Health Support)</li>
                    <li><strong>Roshan Helpline:</strong> <a href="tel:0800-22444" style="color: #007bff; text-decoration: none;">0800-22444</a> (Free Mental Health Counseling)</li>
                    <li><strong>Pakistan Emergency:</strong> <a href="tel:15" style="color: #007bff; text-decoration: none;">15</a> or <a href="tel:1122" style="color: #007bff; text-decoration: none;">1122</a></li>
                    <li><strong>Madadgaar Helpline:</strong> <a href="tel:1098" style="color: #007bff; text-decoration: none;">1098</a> (Child Protection & Mental Health)</li>
                </ul>
            </div>
            
            <p style="color: #2c3e50; margin: 10px 0; line-height: 1.6;">You are not alone. Professional help is available. Please call one of these numbers now.</p>
        </div>
        '''
        
        # Save crisis message if user is logged in
        if "user_id" in session:
            save_chat_message(session["user_id"], user_input, crisis_response)
        
        return jsonify({"response": crisis_response})
    
    # For non-crisis situations, use regular supportive AI response
    prompt = f"""You are a mental health support chatbot. Be brief, helpful, and supportive.

    STRICT RULES:
    - NO religious phrases (no Allah, Assalam, Peace be upon you, etc.)
    - NO cultural greetings in any language
    - NO Urdu/Hindi phrases
    - Plain English only
    - 1-2 sentences maximum
    - Be supportive but secular
    
    User said: "{user_input}"
    
    Respond in 30 words or less with helpful support.
    """
    
    response = model.generate_content(prompt)
    clean_text = response.text.strip()
    
    formatted_response = f'''
    <div style="background: #f8fff8; border-left: 4px solid #10B981; padding: 15px; border-radius: 8px; margin: 10px 0;">
        <p style="color: #2c3e50; margin: 0; line-height: 1.5;">{clean_text}</p>
    </div>
    '''
    
    # Save regular message if user is logged in OR create demo data for guest users
    if "user_id" in session:
        save_chat_message(session["user_id"], user_input, formatted_response)
    else:
        # For demo purposes, save guest conversations with a demo user ID
        save_guest_chat_for_demo(user_input, formatted_response)
    
    return jsonify({"response": formatted_response})


def save_guest_chat_for_demo(user_input, response_text):
    """Save guest chat conversations for demo analytics"""
    try:
        conn = sqlite3.connect("mentalhealth.db")
        cursor = conn.cursor()
        
        # Use a demo user ID for guest conversations
        demo_user_id = "guest_demo"
        
        cursor.execute(
            "INSERT INTO chat_history (user_id, message, response, timestamp) VALUES (?, ?, ?, ?)",
            (demo_user_id, user_input, response_text, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving guest chat: {e}")


@app.route("/mental_health_tips")
def mental_health_tips():
    """Mental health tips and resources page"""
    tips = [
        {
            "title": "Deep Breathing Exercise",
            "description": "Practice 4-7-8 breathing: Inhale for 4 counts, hold for 7, exhale for 8. Repeat 3-4 times.",
            "category": "Anxiety Relief"
        },
        {
            "title": "Daily Gratitude Practice",
            "description": "Write down 3 things you're grateful for each day. This helps shift focus to positive aspects of life.",
            "category": "Mood Enhancement"
        },
        {
            "title": "Progressive Muscle Relaxation",
            "description": "Tense and then relax each muscle group in your body, starting from your toes and working up.",
            "category": "Stress Relief"
        },
        {
            "title": "Mindful Walking",
            "description": "Take a 10-minute walk focusing on your surroundings, breathing, and body sensations.",
            "category": "Mindfulness"
        },
        {
            "title": "Sleep Hygiene",
            "description": "Maintain consistent sleep schedule, avoid screens before bed, and create a calm bedtime routine.",
            "category": "Sleep Health"
        }
    ]
    
    resources = [
        {
            "name": "Pakistan Mental Health Helpline",
            "contact": "0317-6367833",
            "description": "24/7 mental health support and counseling"
        },
        {
            "name": "Roshan Helpline",
            "contact": "0800-22444",
            "description": "Free mental health counseling and support"
        },
        {
            "name": "Emergency Services",
            "contact": "15 or 1122",
            "description": "For immediate emergency assistance"
        }
    ]
    
    return render_template("mental_health_tips.html", tips=tips, resources=resources)


# PWA Routes
@app.route('/manifest.json')
def manifest():
    """Serve PWA manifest"""
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def service_worker():
    """Serve service worker"""
    response = app.send_static_file('sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

@app.route('/offline')
def offline():
    """Offline page for PWA"""
    return render_template('offline.html')


if __name__ == "__main__":
    init_db()
    # Production configuration
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV', 'production') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
