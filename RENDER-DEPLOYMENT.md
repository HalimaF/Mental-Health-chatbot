# 🚀 Step-by-Step Render Deployment Guide

## Prerequisites Check ✅

Your app is almost ready! Here's what we need to fix:

### 1. Get Your Gemini API Key (Required)
- Go to [Google AI Studio](https://ai.google.dev/)
- Sign in with your Google account
- Click "Get API Key" 
- Create a new API key
- Copy the key (starts with "AIza...")

### 2. Environment Variables Setup
Create a `.env` file in your project folder:

```env
GEMINI_API_KEY=AIzaSyC-your-actual-api-key-here
SECRET_KEY=your-super-secret-random-string-here-make-it-long
FLASK_ENV=production
PORT=5000
```

**Important:** Keep your `.env` file private! Never share your API keys.

## 🌐 Deploy to Render (Free Hosting)

### Step 1: Push to GitHub

1. **Initialize Git (if not done):**
   ```bash
   git init
   git add .
   git commit -m "Mental health chatbot ready for deployment"
   ```

2. **Create GitHub Repository:**
   - Go to [github.com](https://github.com)
   - Click "New repository"
   - Name it: `mental-health-chatbot`
   - Make it public (required for free Render)
   - Click "Create repository"

3. **Push your code:**
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/mental-health-chatbot.git
   git branch -M main
   git push -u origin main
   ```

### Step 2: Deploy on Render

1. **Go to Render:**
   - Visit [render.com](https://render.com)
   - Click "Get Started for Free"
   - Sign up with GitHub account

2. **Create Web Service:**
   - Click "New +"
   - Select "Web Service"
   - Click "Connect" next to your repository
   - If you don't see it, click "Connect account" to link GitHub

3. **Configure Deployment:**
   - **Name:** `mental-health-chatbot` (or any name you prefer)
   - **Region:** Oregon (US West)
   - **Branch:** `main`
   - **Root Directory:** Leave empty
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --bind 0.0.0.0:$PORT app:app`

4. **Environment Variables:**
   - Scroll down to "Environment Variables"
   - Click "Add Environment Variable"
   - Add these:

   | Key | Value |
   |-----|-------|
   | `GEMINI_API_KEY` | Your actual Gemini API key |
   | `SECRET_KEY` | A random string (generate one below) |
   | `FLASK_ENV` | production |

5. **Generate Secret Key:**
   Use this Python command to generate a secure secret key:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

6. **Deploy:**
   - Click "Create Web Service"
   - Wait 5-10 minutes for deployment
   - Your app will be live at: `https://your-app-name.onrender.com`

## 🔧 Troubleshooting

### Common Issues:

1. **Build Failed:**
   - Check the build logs in Render dashboard
   - Make sure `requirements.txt` has all dependencies
   - Ensure `gunicorn` is in requirements.txt ✅

2. **App Won't Start:**
   - Check application logs in Render dashboard
   - Verify environment variables are set correctly
   - Make sure GEMINI_API_KEY is valid

3. **Database Issues:**
   - Your app uses SQLite, which works fine on Render's free tier
   - Database will reset on each deployment (normal for free tier)

## 📱 After Deployment

### Test Your Live App:
1. Visit your Render URL
2. Register a new account
3. Test the chat functionality
4. Try installing as PWA (mobile app)

### Share Your App:
- **Direct Link:** `https://your-app-name.onrender.com`
- **Mobile Install:** Users can install from browser menu
- **Social Media:** Share the link with mental health hashtags

## 💰 Monetization Setup

Once deployed, set up payment processing:

### PayPal Integration:
1. Create PayPal Business account
2. Get donation button code
3. Add to your `/donate` page

### Stripe for Premium:
1. Sign up at [stripe.com](https://stripe.com)
2. Get API keys
3. Integrate with subscription model

## 🚀 Next Steps

1. **Monitor Usage:**
   - Check Render dashboard for traffic
   - Monitor for errors in logs
   - Track user registrations

2. **Promote Your App:**
   - Share on social media
   - Post in mental health communities
   - Create demo videos

3. **Collect Feedback:**
   - Add feedback form
   - Monitor user conversations
   - Implement requested features

## 💡 Pro Tips

- **Free Tier Limits:** 750 hours/month (plenty for starting)
- **Sleep Mode:** App sleeps after 15 minutes of inactivity
- **Custom Domain:** Add your own domain later
- **SSL:** Automatically included with HTTPS

## 🆘 Need Help?

If you encounter issues:
1. Check Render dashboard logs
2. Verify environment variables
3. Test locally first with `flask run`
4. Check GitHub repository is public

Your mental health chatbot will help thousands of people worldwide! 🧠💚

## Quick Command Reference

```bash
# Generate secret key
python -c "import secrets; print(secrets.token_hex(32))"

# Test locally
flask run

# Push updates
git add .
git commit -m "Updated app"
git push origin main
```

**Your app will auto-deploy on every GitHub push!** 🎉
