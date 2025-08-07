#!/usr/bin/env python3
"""
Quick deployment setup script for Mental Health Chatbot
Run this script to prepare your app for deployment to free hosting platforms
"""

import os
import json
import subprocess
import sys

def check_file_exists(filepath):
    """Check if a required file exists"""
    if os.path.exists(filepath):
        print(f"✅ {filepath} exists")
        return True
    else:
        print(f"❌ {filepath} missing!")
        return False

def check_requirements():
    """Check if all required files exist"""
    print("🔍 Checking deployment requirements...")
    
    required_files = [
        'app.py',
        'requirements.txt',
        'render-deploy.yaml',
        'static/manifest.json',
        'static/sw.js',
        'Templates/index.html',
        'Templates/chat.html'
    ]
    
    all_good = True
    for file in required_files:
        if not check_file_exists(file):
            all_good = False
    
    return all_good

def check_environment_vars():
    """Check for required environment variables"""
    print("\n🔑 Checking environment variables...")
    
    required_vars = ['GEMINI_API_KEY', 'SECRET_KEY']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
            print(f"❌ {var} not set")
        else:
            print(f"✅ {var} is set")
    
    if missing_vars:
        print(f"\n⚠️  Missing environment variables: {', '.join(missing_vars)}")
        print("📝 Create a .env file with:")
        for var in missing_vars:
            if var == 'GEMINI_API_KEY':
                print(f"   {var}=your_gemini_api_key_from_google_ai_studio")
            else:
                print(f"   {var}=your_random_secret_key_here")
    
    return len(missing_vars) == 0

def test_app_locally():
    """Test if the app starts locally"""
    print("\n🧪 Testing app locally...")
    
    try:
        # Import the app to check for syntax errors
        import app
        print("✅ App imports successfully")
        
        # Check if Flask app is created
        if hasattr(app, 'app'):
            print("✅ Flask app instance found")
        else:
            print("❌ Flask app instance not found")
            return False
            
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error testing app: {e}")
        return False
    
    return True

def check_git_status():
    """Check git repository status"""
    print("\n📚 Checking Git repository...")
    
    try:
        # Check if git repo exists
        result = subprocess.run(['git', 'status'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Git repository initialized")
            
            # Check for uncommitted changes
            if "nothing to commit" in result.stdout:
                print("✅ All changes committed")
            else:
                print("⚠️  Uncommitted changes found")
                print("📝 Run: git add . && git commit -m 'Ready for deployment'")
                
        else:
            print("❌ Not a git repository")
            print("📝 Run: git init && git add . && git commit -m 'Initial commit'")
            return False
            
    except FileNotFoundError:
        print("❌ Git not installed or not in PATH")
        return False
    
    return True

def generate_deployment_commands():
    """Generate deployment commands for different platforms"""
    print("\n🚀 Deployment Commands:")
    
    print("\n1. RENDER.COM (Recommended - Free):")
    print("   • Go to https://render.com")
    print("   • Sign up with GitHub")
    print("   • New + → Web Service")
    print("   • Connect this repository")
    print("   • Build Command: pip install -r requirements.txt")
    print("   • Start Command: gunicorn app:app")
    print("   • Add environment variables in Render dashboard")
    
    print("\n2. RAILWAY.APP:")
    print("   • Go to https://railway.app")
    print("   • Connect GitHub repository")
    print("   • Auto-deploys with Python detection")
    
    print("\n3. PYTHONANYWHERE:")
    print("   • Sign up at https://pythonanywhere.com")
    print("   • Upload code via file manager")
    print("   • Create web app with Python 3.10")

def main():
    """Main deployment check function"""
    print("🧠💚 Mental Health Chatbot - Deployment Checker")
    print("=" * 50)
    
    checks_passed = []
    
    # Run all checks
    checks_passed.append(check_requirements())
    checks_passed.append(check_environment_vars())
    checks_passed.append(test_app_locally())
    checks_passed.append(check_git_status())
    
    print("\n" + "=" * 50)
    
    if all(checks_passed):
        print("🎉 ALL CHECKS PASSED! Ready for deployment!")
        generate_deployment_commands()
        
        print("\n💡 Next Steps:")
        print("1. Push to GitHub: git push origin main")
        print("2. Deploy on Render.com (see commands above)")
        print("3. Add environment variables in hosting dashboard")
        print("4. Test your live app")
        print("5. Share with the world! 🌍")
        
    else:
        print("⚠️  Some checks failed. Please fix the issues above before deploying.")
        print("\n💡 Common fixes:")
        print("• Install missing dependencies: pip install -r requirements.txt")
        print("• Create .env file with your API keys")
        print("• Initialize git: git init && git add . && git commit -m 'Initial commit'")
    
    print(f"\n📖 For detailed instructions, see: FREE-DEPLOYMENT-GUIDE.md")

if __name__ == "__main__":
    main()
