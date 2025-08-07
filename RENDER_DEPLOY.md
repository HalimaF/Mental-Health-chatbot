# Mental Health Chatbot - Render Deployment Guide

## 🚀 Deploy on Render

### Quick Deploy Steps:

1. **Go to [Render.com](https://render.com)** and sign in with GitHub
2. **Create New Web Service** → Connect to your repository
3. **Configure Settings:**
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Environment:** `Python 3`

### Environment Variables:

Add this environment variable in Render dashboard:
- `GOOGLE_API_KEY`: Your Google Gemini API key

### That's it! 🎉

Your mental health chatbot will be live at: `https://your-app-name.onrender.com`

## 📱 Features Included:

- ✅ AI-powered mental health counseling
- ✅ Advanced sentiment analytics with graphs
- ✅ Mood tracking over time  
- ✅ Personalized insights
- ✅ Crisis detection and support
- ✅ User authentication
- ✅ Pakistan-themed design 🇵🇰

## 🔧 Local Development:

```bash
# Clone and setup
git clone https://github.com/HalimaF/Mental-Health-chatbot.git
cd Mental-Health-chatbot

# Install dependencies
pip install -r requirements.txt

# Set environment variable
export GOOGLE_API_KEY="your_api_key_here"

# Run locally
python app.py
```

## 🎯 Live Demo:

Your app will be accessible 24/7 on Render's free tier with:
- HTTPS enabled automatically
- Global CDN
- Automatic deployments from GitHub

---

**Ready for Render deployment! 🌟**
