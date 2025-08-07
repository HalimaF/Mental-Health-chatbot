#!/usr/bin/env python3
"""
Quick deployment checker for Dil-e-Azaad Mental Health Chatbot
Run this to verify your project is ready for deployment
"""
import os
import sys

def check_file_exists(filename, required=True):
    """Check if a file exists"""
    exists = os.path.exists(filename)
    status = "✅" if exists else ("❌" if required else "⚠️")
    requirement = "Required" if required else "Optional"
    print(f"{status} {filename} - {requirement}")
    return exists

def check_env_variables():
    """Check environment variables"""
    print("\n📋 ENVIRONMENT VARIABLES CHECK:")
    
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            content = f.read()
            
        has_api_key = 'GOOGLE_API_KEY=' in content and 'your_gemini_api_key_here' not in content
        has_secret = 'SECRET_KEY=' in content and 'your_secret_key_here' not in content
        
        print(f"{'✅' if has_api_key else '❌'} GOOGLE_API_KEY configured")
        print(f"{'✅' if has_secret else '❌'} SECRET_KEY configured")
        
        return has_api_key and has_secret
    else:
        print("❌ .env file not found")
        return False

def main():
    """Main deployment check function"""
    print("🧠 DIL-E-AZAAD DEPLOYMENT READINESS CHECK")
    print("=" * 50)
    
    print("\n📁 REQUIRED FILES CHECK:")
    
    # Check required files
    required_files = [
        'app.py',
        'requirements.txt',
        '.env.example',
        '.gitignore',
        'README.md',
        'Procfile',
        'Templates/',
        'static/'
    ]
    
    all_required_exist = True
    for file in required_files:
        if not check_file_exists(file):
            all_required_exist = False
    
    print("\n📁 DEPLOYMENT FILES CHECK:")
    
    # Check deployment files
    deployment_files = [
        ('render.yaml', False),
        ('Dockerfile', False),
        ('config.py', False),
        ('deploy.py', False),
        ('DEPLOYMENT_GUIDE.md', False)
    ]
    
    for file, required in deployment_files:
        check_file_exists(file, required)
    
    # Check environment variables
    env_ready = check_env_variables()
    
    print("\n🚀 DEPLOYMENT OPTIONS:")
    print("1. 🌐 Render.com (RECOMMENDED - FREE)")
    print("   - Sign up: https://render.com")
    print("   - Connect GitHub repository")
    print("   - Set environment variables in dashboard")
    print("   - Deploy automatically!")
    print()
    print("2. 🚂 Railway.app (FREE TIER)")
    print("   - Sign up: https://railway.app")
    print("   - Deploy from GitHub")
    print("   - Add environment variables")
    print()
    print("3. 🪂 Fly.io (FREE WITH LIMITS)")
    print("   - Install: npm install -g flyctl")
    print("   - Login: flyctl auth login")
    print("   - Deploy: flyctl launch")
    print()
    
    # Final status
    print("\n" + "=" * 50)
    if all_required_exist and env_ready:
        print("🎉 PROJECT READY FOR DEPLOYMENT!")
        print("✅ All required files present")
        print("✅ Environment variables configured")
        print("📝 Next: Push to GitHub and deploy to Render.com")
    elif all_required_exist:
        print("⚠️  PROJECT ALMOST READY!")
        print("✅ All required files present")
        print("❌ Environment variables need configuration")
        print("📝 Next: Edit .env file with your API keys")
    else:
        print("❌ PROJECT NOT READY!")
        print("📝 Please ensure all required files are present")
    
    print("\n🔑 GET YOUR API KEY:")
    print("🌐 Visit: https://ai.google.dev")
    print("🔧 Generate API key and add to .env file")
    
    print("\n💡 QUICK START:")
    print("1. Get API key from https://ai.google.dev")
    print("2. Edit .env file with your keys")
    print("3. Push to GitHub")
    print("4. Deploy to Render.com")
    print("5. Your mental health chatbot is LIVE! 🎉")

if __name__ == "__main__":
    main()
