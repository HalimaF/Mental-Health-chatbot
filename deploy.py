#!/usr/bin/env python3
"""
Production deployment script for Dil-e-Azaad Mental Health Chatbot
"""
import os
import sys
import subprocess
import secrets

def generate_secret_key():
    """Generate a secure secret key"""
    return secrets.token_hex(32)

def check_requirements():
    """Check if all requirements are installed"""
    print("🔍 Checking requirements...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                      check=True, capture_output=True)
        print("✅ All requirements installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing requirements: {e}")
        return False

def setup_production_env():
    """Set up production environment variables"""
    print("⚙️ Setting up production environment...")
    
    if not os.path.exists('.env'):
        print("📝 Creating .env file from example...")
        with open('.env.example', 'r') as example:
            content = example.read()
        
        # Generate a secret key
        secret_key = generate_secret_key()
        content = content.replace('your_secret_key_here', secret_key)
        
        with open('.env', 'w') as env_file:
            env_file.write(content)
        
        print("✅ .env file created")
        print("⚠️  IMPORTANT: Add your GOOGLE_API_KEY to the .env file!")
        return False
    else:
        print("✅ .env file already exists")
        return True

def create_directories():
    """Create necessary directories"""
    print("📁 Creating necessary directories...")
    os.makedirs('flask_session', exist_ok=True)
    print("✅ Directories created")

def run_production_server():
    """Run the production server"""
    print("🚀 Starting production server...")
    print("🌐 Your mental health chatbot will be available at: http://localhost:5000")
    print("🛑 Press Ctrl+C to stop the server")
    
    try:
        # Set production environment
        os.environ['FLASK_ENV'] = 'production'
        os.environ['FLASK_DEBUG'] = 'False'
        
        # Import and run the app
        from app import app
        app.run(host='0.0.0.0', port=5000, debug=False)
        
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Error starting server: {e}")

def main():
    """Main deployment function"""
    print("🧠 DIL-E-AZAAD MENTAL HEALTH CHATBOT - PRODUCTION DEPLOYMENT")
    print("=" * 60)
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        sys.exit(1)
    
    print(f"✅ Python {sys.version.split()[0]} detected")
    
    # Setup steps
    if not check_requirements():
        sys.exit(1)
    
    env_ready = setup_production_env()
    create_directories()
    
    if not env_ready:
        print("\n⚠️  NEXT STEPS:")
        print("1. Edit the .env file and add your GOOGLE_API_KEY")
        print("2. Get your API key from: https://ai.google.dev")
        print("3. Run this script again: python deploy.py")
        sys.exit(0)
    
    # Check if API key is set
    from dotenv import load_dotenv
    load_dotenv()
    
    if not os.getenv('GOOGLE_API_KEY') or os.getenv('GOOGLE_API_KEY') == 'your_gemini_api_key_here':
        print("❌ GOOGLE_API_KEY not set in .env file")
        print("📝 Please edit .env and add your Gemini API key")
        print("🔗 Get it from: https://ai.google.dev")
        sys.exit(1)
    
    print("✅ Environment configuration complete")
    print("🎉 Ready for deployment!")
    
    run_production_server()

if __name__ == "__main__":
    main()
