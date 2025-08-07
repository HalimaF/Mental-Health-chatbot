#!/usr/bin/env python3
"""
Create sample data for testing the sentiment insights page
"""
import sys
import os
import sqlite3
from datetime import datetime, timedelta
import random

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def create_sample_user_and_data():
    """Create a sample user with sentiment data for testing"""
    
    print("🧪 CREATING SAMPLE USER AND SENTIMENT DATA")
    print("=" * 50)
    
    # Connect to database (using the correct database name)
    conn = sqlite3.connect('dil_azaad.db')
    cursor = conn.cursor()
    
    try:
        # Create test user
        cursor.execute('''
            INSERT OR IGNORE INTO users (id, username, email, password_hash) 
            VALUES (999, 'testuser', 'test@example.com', 'dummy_hash')
        ''')
        
        # Comprehensive sample sentiment data (more realistic mental health conversations)
        sample_conversations = [
            ("I feel hopeless and sad", "severe_negative", 0.8, "depression_severe", 0),
            ("I'm worried about my job interviews", "moderate_negative", 0.7, "anxiety_moderate", 0), 
            ("Having a good day with my family", "positive", 0.6, "positive", 0),
            ("I'm so anxious I can't breathe properly", "severe_negative", 0.9, "anxiety_severe", 0),
            ("Feeling down but trying to cope today", "mild_negative", 0.5, "depression_moderate", 0),
            ("Great news about my promotion at work!", "positive", 0.8, "positive", 0),
            ("Sometimes I feel like giving up on everything", "moderate_negative", 0.6, "depression_moderate", 0),
            ("Really grateful for my supportive friends", "positive", 0.8, "positive", 0),
            ("Can't sleep, mind racing with worries", "moderate_negative", 0.7, "anxiety_moderate", 0),
            ("Proud of myself for exercising today", "positive", 0.6, "positive", 0),
            ("Everything feels overwhelming lately", "moderate_negative", 0.8, "depression_moderate", 0),
            ("Had a panic attack this morning", "severe_negative", 0.9, "anxiety_severe", 0),
            ("Feeling motivated to start new projects", "positive", 0.7, "positive", 0),
            ("Stressed about family expectations", "moderate_negative", 0.6, "anxiety_moderate", 0),
            ("Accomplished my daily goals successfully", "positive", 0.7, "positive", 0),
            ("Lonely and isolated from everyone", "moderate_negative", 0.7, "depression_moderate", 0),
            ("Enjoyed a peaceful walk in nature", "positive", 0.6, "positive", 0),
            ("Fighting negative thoughts constantly", "moderate_negative", 0.8, "depression_moderate", 0),
            ("Celebrated small wins today", "positive", 0.6, "positive", 0),
            ("Exhausted from emotional stress", "moderate_negative", 0.7, "anxiety_moderate", 0)
        ]
        
        # Insert sample sentiment tracking data with varied timestamps
        for i, (message, sentiment, confidence, emotions, crisis) in enumerate(sample_conversations):
            # Create timestamps over the last 14 days for better analytics
            days_back = 14 - (i * 0.7)  # More varied distribution
            timestamp = (datetime.now() - timedelta(days=days_back)).isoformat()
            
            cursor.execute('''
                INSERT INTO sentiment_tracking 
                (user_id, sentiment, confidence_score, emotions_detected, crisis_flag, user_message, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (999, sentiment, confidence, emotions, crisis, message, timestamp))
        
        # Insert some chat history
        for i, (message, sentiment, confidence, emotions, crisis) in enumerate(sample_conversations[:5]):
            response = f"Thank you for sharing. I understand you're feeling {sentiment.replace('_', ' ')}. Here's some support..."
            timestamp = (datetime.now() - timedelta(days=5-i)).isoformat()
            
            cursor.execute('''
                INSERT INTO chat_history (user_id, message, response, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (999, message, response, timestamp))
        
        conn.commit()
        print("✅ Sample user created (ID: 999)")
        print("✅ Sample sentiment data inserted")
        print("✅ Sample chat history created")
        print("\n🎯 TEST CREDENTIALS:")
        print("Username: testuser")
        print("Password: (any password will work for this test)")
        print("\n💡 Now you can:")
        print("1. Go to http://127.0.0.1:5000")
        print("2. Login with 'testuser' (any password)")
        print("3. Visit /sentiment_insights to see the analytics!")
        
    except Exception as e:
        print(f"❌ Error creating sample data: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    create_sample_user_and_data()
